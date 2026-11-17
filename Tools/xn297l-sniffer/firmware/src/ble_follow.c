/*
 * Bluetooth LE connection following logic (pure C, no hardware access).
 * See ble_follow.h for the overview. Independent implementation of the
 * public Core Specification Vol 6 Part B (4.5 connection state, 5.1 control
 * procedures).
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <string.h>

#include "ble_csa.h"
#include "ble_follow.h"

/* Worst case master clock accuracy in ppm for the SCA field of the CONNECT_IND (Vol 6 B 2.3.3.1) */
static const uint16_t sca_ppm[8] = { 500, 250, 150, 100, 75, 50, 30, 20 };

/* Longest supported connection interval in 1.25 ms units (4 s), shortest 7.5 ms. */
#define INTERVAL_MIN 6u
#define INTERVAL_MAX 3200u

/* ------------------------------------------------------------------------ */
/* Small helpers                                                             */
/* ------------------------------------------------------------------------ */

/* Signed 16 bit distance of event counters: true if `instant` is now or in the past. */
static bool instant_reached(uint16_t counter, uint16_t instant)
{
	return (uint16_t)(counter - instant) < 0x8000u;
}

/* Number of events from `from` to `to` (wrap safe, to is not before from). */
static uint16_t events_between(uint16_t to, uint16_t from)
{
	return (uint16_t)(to - from);
}

uint32_t ble_pkt_end_us(uint32_t start_us, uint8_t payload_len)
{
	/* preamble 1 + access address 4 + header 2 + payload + CRC 3 bytes, 8 us per byte */
	return start_us + (10u + payload_len) * 8u;
}

/* ------------------------------------------------------------------------ */
/* Configuration                                                             */
/* ------------------------------------------------------------------------ */

void ble_follow_init(struct ble_follow *f)
{
	memset(f, 0, sizeof(*f));
	f->follow_conn = true;
	f->follow_rsp = true;
	f->target_type = BLE_TARGET_ANY;
}

void ble_follow_set_target(struct ble_follow *f, const uint8_t target[6], uint8_t type)
{
	f->connected = false;                      /* a running connection is dropped */
	f->adv_chsel = false;
	if (target == NULL) {
		f->has_target = false;
		return;
	}
	memcpy(f->target, target, 6);
	f->target_type = type;
	f->has_target = true;
}

void ble_follow_set_options(struct ble_follow *f, bool follow_conn, bool follow_rsp)
{
	f->follow_conn = follow_conn;
	f->follow_rsp = follow_rsp;
}

/* ------------------------------------------------------------------------ */
/* Scanning                                                                  */
/* ------------------------------------------------------------------------ */

/* Does the 6 byte address (and its random/public bit) belong to the followed device? */
static bool is_target(const struct ble_follow *f, const uint8_t *addr, bool random)
{
	return memcmp(addr, f->target, 6) == 0 &&
	       (f->target_type == BLE_TARGET_ANY || f->target_type == (random ? 1u : 0u));
}

/*
 * Set up the connection from a CONNECT_IND whose first byte is at pdu.
 * Returns false (and changes nothing) if the parameters are not valid
 * (Vol 6 Part B 2.3.3.1: interval 7.5 ms..4 s, hop 5..16, >= 2 used channels).
 */
static bool start_connection(struct ble_follow *f, const uint8_t *pdu, size_t pdu_len,
			     uint32_t start_us)
{
	struct ble_connect_ind ci;

	if (!ble_pdu_parse_connect_ind(pdu, pdu_len, &ci) ||
	    ci.interval < INTERVAL_MIN || ci.interval > INTERVAL_MAX ||
	    ci.hop < 5u || ci.hop > 16u || ble_csa_count_used(ci.chmap) < 2u) {
		return false;
	}
	uint32_t end_us = ble_pkt_end_us(start_us, BLE_CONNECT_IND_LEN);

	f->connected = true;
	f->lost_reason = BLE_LOST_NONE;
	f->access_address = ci.access_address;
	f->crc_init = ci.crc_init;
	/* CSA #2 is used if both the advertiser (its last ADV PDU) and the initiator ask for it */
	f->csa2 = ci.ch_sel && f->adv_chsel;
	f->channel_id = ble_csa2_channel_id(ci.access_address);
	f->hop = ci.hop;
	f->last_unmapped = 0;
	memcpy(f->chmap, ci.chmap, BLE_CHMAP_LEN);
	f->sca = ci.sca;
	f->interval = ci.interval;
	f->latency = ci.latency;
	f->timeout = ci.timeout;
	f->interval_us = (uint32_t)ci.interval * 1250u;
	f->encrypted = false;
	f->terminated = false;
	f->upd_pending = false;
	f->map_pending = false;

	/*
	 * First event: the master sends its first packet somewhere inside the
	 * transmit window that starts transmitWindowDelay + WinOffset after the
	 * end of the CONNECT_IND and is WinSize long.
	 */
	uint32_t offset_us = BLE_TRANSMIT_WINDOW_DELAY_US + (uint32_t)ci.win_offset * 1250u;

	f->next_counter = 0;
	f->counter = 0;
	f->ref_us = end_us + offset_us;
	f->ref_counter = 0;
	f->win_us = (uint32_t)ci.win_size * 1250u;
	f->sync_us = end_us;
	f->last_valid_us = end_us;
	f->establish_limit_us = offset_us + f->win_us + BLE_ESTABLISH_EVENTS * f->interval_us;
	f->anchored = false;
	f->pkt_index = 0;
	return true;
}

uint8_t ble_follow_on_adv(struct ble_follow *f, const uint8_t *pdu, size_t pdu_len,
			  bool crc_ok, uint32_t start_us)
{
	if (!f->has_target) {
		return BLE_FOLLOW_FORWARD;             /* "all devices": forward everything */
	}
	if (pdu_len < 2u + 6u || pdu_len < 2u + (size_t)pdu[1]) {
		return 0;                              /* too short to contain an address */
	}
	const uint8_t *payload = &pdu[2];
	uint8_t len = pdu[1];
	bool tx_random = (pdu[0] & BLE_ADV_HDR_TXADD) != 0u;
	bool rx_random = (pdu[0] & BLE_ADV_HDR_RXADD) != 0u;
	/* a response is worth waiting for if we forward scan traffic or follow connections */
	uint8_t wait = (f->follow_conn || f->follow_rsp) ? BLE_FOLLOW_WAIT : 0u;

	switch (pdu[0] & 0x0Fu) {
	case BLE_ADV_IND:
	case BLE_ADV_DIRECT_IND:
		if (!is_target(f, payload, tx_random)) {
			return 0;
		}
		/* remember whether the advertiser supports CSA #2 (needed at CONNECT_IND time) */
		f->adv_chsel = (pdu[0] & BLE_ADV_HDR_CHSEL) != 0u;
		return BLE_FOLLOW_FORWARD | wait;
	case BLE_ADV_SCAN_IND:
		/* scannable only: a SCAN_REQ may follow, a CONNECT_IND cannot */
		return is_target(f, payload, tx_random)
			? (BLE_FOLLOW_FORWARD | (f->follow_rsp ? BLE_FOLLOW_WAIT : 0u)) : 0u;
	case BLE_ADV_NONCONN_IND:
		return is_target(f, payload, tx_random) ? BLE_FOLLOW_FORWARD : 0u;
	case BLE_SCAN_RSP:
		return (f->follow_rsp && is_target(f, payload, tx_random)) ? BLE_FOLLOW_FORWARD : 0u;
	case BLE_SCAN_REQ:
		/* ScanA (6), AdvA (6): the advertiser is the second address */
		if (len < 12u || !f->follow_rsp || !is_target(f, &payload[6], rx_random)) {
			return 0;
		}
		return BLE_FOLLOW_FORWARD | BLE_FOLLOW_WAIT;   /* SCAN_RSP follows after T_IFS */
	case BLE_CONNECT_IND:
		if (len < 12u || !is_target(f, &payload[6], rx_random)) {
			return 0;
		}
		if (crc_ok && f->follow_conn && start_connection(f, pdu, pdu_len, start_us)) {
			return BLE_FOLLOW_FORWARD | BLE_FOLLOW_CONNECT;
		}
		return BLE_FOLLOW_FORWARD;
	default:
		return 0;                              /* extended advertising etc.: not followed yet */
	}
}

/* ------------------------------------------------------------------------ */
/* Connection events                                                         */
/* ------------------------------------------------------------------------ */

/* Expected (earliest) start of event `counter` according to the current schedule. */
static uint32_t expected_start(const struct ble_follow *f, uint16_t counter)
{
	return f->ref_us + (uint32_t)events_between(counter, f->ref_counter) * f->interval_us;
}

/*
 * Apply a connection update at its instant. The old schedule is extrapolated
 * to the instant event, then the transmit window of the new parameters opens
 * WinOffset after that point (Vol 6 Part B 5.1.1; no transmitWindowDelay).
 */
static void apply_connection_update(struct ble_follow *f, uint16_t counter)
{
	uint32_t old_start = expected_start(f, counter);

	f->interval = f->upd.interval;
	f->interval_us = (uint32_t)f->upd.interval * 1250u;
	f->latency = f->upd.latency;
	f->timeout = f->upd.timeout;
	f->ref_us = old_start + (uint32_t)f->upd.win_offset * 1250u;
	f->ref_counter = counter;
	f->win_us = (uint32_t)f->upd.win_size * 1250u;
	f->upd_pending = false;
}

bool ble_follow_next_event(struct ble_follow *f, struct ble_rx_plan *plan)
{
	uint16_t counter = f->next_counter;

	plan->flags = 0;
	if (!f->connected) {
		return false;
	}
	if (f->terminated) {
		f->lost_reason = BLE_LOST_TERMINATE;
		f->connected = false;
		return false;
	}

	/* Updates take effect with the event whose counter equals their instant */
	if (f->map_pending && instant_reached(counter, f->map.instant)) {
		memcpy(f->chmap, f->map.chmap, BLE_CHMAP_LEN);
		f->map_pending = false;
		plan->flags |= BLE_PLAN_UPDATED;
	}
	if (f->upd_pending && instant_reached(counter, f->upd.instant)) {
		apply_connection_update(f, counter);
		plan->flags |= BLE_PLAN_UPDATED;
	}

	uint32_t start = expected_start(f, counter);

	/* Supervision: no valid packet for the timeout (or 6 events after the CONNECT_IND) */
	uint32_t limit = f->anchored ? (uint32_t)f->timeout * 10000u : f->establish_limit_us;

	if ((uint32_t)(start - f->last_valid_us) > limit) {
		f->lost_reason = f->anchored ? BLE_LOST_TIMEOUT : BLE_LOST_ESTABLISH;
		f->connected = false;
		return false;
	}

	/* Channel: the algorithm state advances once per event, also for missed events */
	plan->channel = f->csa2 ? ble_csa2_channel(f->channel_id, counter, f->chmap)
				: ble_csa1_next(&f->last_unmapped, f->hop, f->chmap);
	plan->counter = counter;

	/*
	 * Window widening: the clocks of master and sniffer drift apart by
	 * (ppm_master + ppm_sniffer) per second since the last synchronisation;
	 * plus a fixed jitter. Never wider than half an interval minus T_IFS
	 * (neighbouring events must not overlap).
	 */
	uint32_t age_us = start - f->sync_us;
	uint32_t widening = (uint32_t)(((uint64_t)(sca_ppm[f->sca & 7u] + BLE_OWN_PPM) * age_us) /
				       1000000u) + BLE_JITTER_US;
	uint32_t cap = f->interval_us / 2u - BLE_TIFS_US;

	if (widening > cap) {
		widening = cap;
	}
	plan->rx_on_us = start - widening - BLE_RX_LEAD_US;
	plan->rx_off_us = start + f->win_us + widening + BLE_AA_DETECT_US + BLE_RX_MARGIN_US;

	/* The event is now "current"; reset the per event state */
	f->counter = counter;
	f->next_counter = (uint16_t)(counter + 1u);
	f->pkt_index = 0;
	f->md_master = false;
	f->md_slave = false;
	return true;
}

/*
 * Handle an LL control PDU with valid CRC (payload starts at the opcode).
 * Not called after encryption started: the content would be ciphertext.
 */
static void handle_control(struct ble_follow *f, bool from_master, const uint8_t *payload,
			   size_t len)
{
	struct ble_conn_update upd;
	struct ble_chmap_update map;
	/* the instant must be ahead of the current event (1 .. 32767 events) */
	uint16_t ahead;

	if (len == 0u) {
		return;
	}
	switch (payload[0]) {
	case BLE_LL_CONNECTION_UPDATE_IND:
		if (from_master && ble_pdu_parse_conn_update(payload, len, &upd)) {
			ahead = (uint16_t)(upd.instant - f->counter);
			if (ahead != 0u && ahead < 0x8000u &&
			    upd.interval >= INTERVAL_MIN && upd.interval <= INTERVAL_MAX) {
				f->upd = upd;               /* a retransmission just rewrites the same data */
				f->upd_pending = true;
			}
		}
		break;
	case BLE_LL_CHANNEL_MAP_IND:
		if (from_master && ble_pdu_parse_chmap_update(payload, len, &map)) {
			ahead = (uint16_t)(map.instant - f->counter);
			if (ahead != 0u && ahead < 0x8000u && ble_csa_count_used(map.chmap) >= 2u) {
				f->map = map;
				f->map_pending = true;
			}
		}
		break;
	case BLE_LL_TERMINATE_IND:
		if (len == 2u) {
			f->terminated = true;               /* either side may terminate */
		}
		break;
	case BLE_LL_START_ENC_REQ:
		if (!from_master) {
			f->encrypted = true;                /* from now on payloads are encrypted */
		}
		break;
	default:
		break;
	}
}

void ble_follow_on_data_packet(struct ble_follow *f, const uint8_t *pdu, size_t pdu_len,
			       bool crc_ok, uint32_t start_us, struct ble_pkt_result *res)
{
	bool master = (f->pkt_index & 1u) == 0u;   /* packets alternate: master, slave, master ... */
	uint8_t payload_len = pdu_len >= 2u ? pdu[1] : 0u;
	uint32_t end_us = ble_pkt_end_us(start_us, payload_len);

	res->flags = (uint8_t)(master ? 0u : BLE_PKT_DIR_S2M);
	res->rx_off_us = 0;

	if (f->pkt_index == 0u) {
		/* The first packet of an event is the anchor point: resynchronise to it */
		res->flags |= BLE_PKT_ANCHOR;
		f->ref_us = start_us;
		f->ref_counter = f->counter;
		f->win_us = 0;
		f->sync_us = start_us;
		f->anchored = true;
	} else {
		/* Packets inside an event follow each other after T_IFS */
		int32_t gap = (int32_t)(start_us - f->prev_end_us) - (int32_t)BLE_TIFS_US;

		if (gap > (int32_t)BLE_GAP_TOLERANCE_US || gap < -(int32_t)BLE_GAP_TOLERANCE_US) {
			res->flags |= BLE_PKT_GAP;
		}
	}

	bool more_data = false;

	if (crc_ok && pdu_len >= 2u) {
		f->last_valid_us = start_us;
		more_data = (pdu[0] & BLE_DATA_MD) != 0u;
		if ((pdu[0] & BLE_DATA_LLID_MASK) == BLE_DATA_LLID_CTRL && !f->encrypted &&
		    pdu_len >= 2u + (size_t)payload_len) {
			handle_control(f, master, &pdu[2], payload_len);
		}
	}
	if (master) {
		f->md_master = more_data;
	} else {
		f->md_slave = more_data;
	}
	f->prev_end_us = end_us;
	f->pkt_index++;

	/*
	 * The slave answers every master packet, so always wait for it. After the
	 * slave's packet the event goes on only if either side has More Data and
	 * the slave packet was received correctly (a CRC error closes the event).
	 */
	if (master || (crc_ok && !f->terminated && (f->md_master || f->md_slave))) {
		res->flags |= BLE_PKT_CONTINUE;
		res->rx_off_us = end_us + BLE_IFS_LISTEN_US;
	}
}

void ble_follow_info(const struct ble_follow *f, struct ble_conn_info *info)
{
	info->access_address = f->access_address;
	info->crc_init = f->crc_init;
	info->interval = f->interval;
	info->latency = f->latency;
	info->timeout = f->timeout;
	memcpy(info->chmap, f->chmap, BLE_CHMAP_LEN);
	info->hop = f->hop;
	info->csa = f->csa2 ? 2u : 1u;
	info->sca = f->sca;
	info->reason = f->lost_reason;
	info->counter = f->counter;
}
