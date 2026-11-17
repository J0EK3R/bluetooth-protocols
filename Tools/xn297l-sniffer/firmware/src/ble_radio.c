/*
 * Bluetooth LE receiver on the nRF52840 RADIO: advertising scan and
 * connection following (milestones M1 and M2).
 *
 * How it works
 * ------------
 * The RADIO is configured like a BLE controller would do it:
 *   - MODE = Ble_1Mbit, packet layout S0 (1 byte header 0) + LENGTH (1 byte)
 *     + payload,
 *   - hardware whitening (initial value = channel index) and CRC-24
 *     (polynomial 0x00065B, access address excluded),
 *   - access address and CRC initial value: advertising values while
 *     scanning, the values of the CONNECT_IND while following.
 * Reception is a loop driven by the RADIO interrupt:
 *
 *   RXEN -> (ramp-up) -> READY -> START (short) -> packet ... END
 *        -> DISABLED (short) -> interrupt: store packet, decide, RXEN again
 *
 * A TIMER (1 MHz, 32 bit) provides the time base. The moment the access
 * address was matched is captured by a PPI channel without CPU involvement;
 * the start of the packet (preamble) is that time minus 40 us.
 *
 * Scanning (rmode == R_SCAN)
 *   The channel changes every dwell time (TIMER compare 1). A hop never
 *   destroys a packet: an idle receiver is disabled at once, a receiving one
 *   is hopped after its packet. With a followed device (follow mode):
 *   - only packets of that device are queued (ble_follow_on_adv decides),
 *   - after its connectable / scannable advertisement the receiver stays on
 *     the channel for one T_IFS to catch the SCAN_REQ / CONNECT_IND / SCAN_RSP
 *     (TIMER compare 4 limits that wait),
 *   - the scan is aligned with the advertiser: after its packet the receiver
 *     moves to the next advertising channel at once (the advertiser sends
 *     37, 38, 39 within a few ms) and listens there for a short window.
 *
 * Following (rmode == R_CONN)
 *   After a valid CONNECT_IND ble_follow_next_event() gives channel and
 *   listening window of every connection event. The RADIO is started by
 *   TIMER compare 3 through PPI (no interrupt latency), packets of the event
 *   are received back to back (the slave answers 150 us after the master),
 *   TIMER compare 4 ends a listening window without packet. When the
 *   connection ends the scan resumes.
 *
 * Interrupt context only touches the packet ring head, the main loop only the
 * tail; both indices are single-writer so no lock is needed.
 *
 * This is an independent implementation (Core Specification Vol 6 Part B,
 * nRF52840 product specification).
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/irq.h>
#include <soc.h>    /* NRF_RADIO, NRF_TIMER3, NRF_PPI and register bit definitions */

#include "ble_csa.h"
#include "ble_follow.h"
#include "ble_radio.h"

/* ------------------------------------------------------------------------ */
/* Constants                                                                 */
/* ------------------------------------------------------------------------ */

#define ADV_ACCESS_ADDRESS   0x8E89BED6u   /* Core Spec Vol 6 Part B 2.1.2        */
#define ADV_CRC_INIT         0x555555u     /* CRC initial value on advertising    */
#define CRC_POLY             0x00065Bu     /* x^24+x^10+x^9+x^6+x^4+x^3+x+1       */

/*
 * Time from the start of the packet (first preamble bit) to the ADDRESS
 * event: preamble 8 us + access address 32 us on the LE 1M PHY. The RADIO
 * raises ADDRESS a small, fixed time after the last address bit; that offset
 * is not compensated (to be calibrated against a reference sniffer). It is
 * the same for every packet, so it cancels in all interval calculations.
 */
#define T_PACKET_START_1M_US 40u

#define RING_SLOTS           32u           /* queue entries for the main loop     */
#define PPI_CH_ADDRESS       19            /* PPI channel: ADDRESS -> TIMER capture */
#define PPI_CH_RXON          18            /* PPI channel: TIMER compare -> RADIO RXEN */
#define TIMER_CC_NOW         0             /* CC[0]: "read the clock" capture     */
#define TIMER_CC_HOP         1             /* CC[1]: channel hop compare          */
#define TIMER_CC_ADDRESS     2             /* CC[2]: filled by PPI at ADDRESS     */
#define TIMER_CC_RXON        3             /* CC[3]: start the receiver (via PPI) */
#define TIMER_CC_RXOFF       4             /* CC[4]: stop listening (interrupt)   */

/* After a packet of the followed advertiser the next channel is listened to for this long */
#define ALIGN_WINDOW_US      20000u

/* ------------------------------------------------------------------------ */
/* State                                                                     */
/* ------------------------------------------------------------------------ */

enum rx_mode {
	R_SCAN,                                    /* advertising channels                */
	R_CONN,                                    /* following a connection              */
};

static struct ble_config cfg;                 /* active configuration             */
static struct ble_follow follow;              /* connection following logic       */
static struct ble_rx_plan plan;               /* current connection event         */
static struct ble_packet ring[RING_SLOTS];    /* queue (DMA target = ring[head])  */
static volatile uint8_t ring_head;            /* next slot the RADIO writes (ISR) */
static volatile uint8_t ring_tail;            /* next slot the main loop reads    */
static volatile uint32_t drop_count;          /* entries lost on overflow         */
static enum rx_mode rmode;                    /* scanning or following            */
static volatile bool hop_due;                 /* a channel hop is requested       */
static bool tifs_wait;                        /* scan: staying for a response     */
static bool align_pending;                    /* scan: move to the next channel after the packet */
static bool aligned;                          /* scan: currently in an alignment window */
static uint32_t hop_period_us;                /* time to the next scheduled hop   */
static uint8_t channel_pos;                   /* index into cfg.channels[]        */
static bool irq_connected;                    /* IRQ_CONNECT done (only once)     */

/* ------------------------------------------------------------------------ */
/* Helpers                                                                   */
/* ------------------------------------------------------------------------ */

/* Read the free running 1 MHz clock (software capture). */
static uint32_t timer_now(void)
{
	NRF_TIMER3->TASKS_CAPTURE[TIMER_CC_NOW] = 1;
	return NRF_TIMER3->CC[TIMER_CC_NOW];
}

/* Disable the RADIO and wait (a few microseconds) until it is disabled. */
static void radio_disable_and_wait(void)
{
	NRF_RADIO->SHORTS = 0;
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->TASKS_DISABLE = 1;
	/* Bounded wait: a radio that was never enabled must not hang the firmware. */
	for (uint32_t i = 0; i < 100000u && NRF_RADIO->EVENTS_DISABLED == 0; i++) {
		/* busy wait */
	}
	NRF_RADIO->EVENTS_DISABLED = 0;
}

/* Program the access address (BLE layout: PREFIX0 = AA[31:24], BASE0 = AA[23:0] << 8). */
static void set_access_address(uint32_t aa)
{
	NRF_RADIO->PREFIX0 = (aa >> 24) & 0xFFu;
	NRF_RADIO->BASE0 = aa << 8;
	NRF_RADIO->RXADDRESSES = 1u;               /* logical address 0 only */
}

/* Access address and CRC initial value of advertising channel packets. */
static void use_advertising_parameters(void)
{
	set_access_address(ADV_ACCESS_ADDRESS);
	NRF_RADIO->CRCINIT = ADV_CRC_INIT;
}

/* Access address and CRC initial value of the followed connection. */
static void use_connection_parameters(void)
{
	set_access_address(follow.access_address);
	NRF_RADIO->CRCINIT = follow.crc_init;
}

/* Tune frequency and whitening to a BLE channel index (RADIO must be disabled). */
static void tune(uint8_t channel)
{
	NRF_RADIO->FREQUENCY = ble_channel_frequency(channel);
	NRF_RADIO->DATAWHITEIV = channel;          /* whitening LFSR starts from the channel index */
}

/* Clear the RADIO events and point EasyDMA to the next free queue slot. */
static void prepare_rx(void)
{
	NRF_RADIO->PACKETPTR = (uint32_t)ring[ring_head].raw;
	NRF_RADIO->EVENTS_READY = 0;
	NRF_RADIO->EVENTS_ADDRESS = 0;
	NRF_RADIO->EVENTS_END = 0;
	NRF_RADIO->EVENTS_DISABLED = 0;
}

/* Tune to the current scan channel and start the receiver at once. */
static void arm_scan_rx(void)
{
	tune(cfg.channels[channel_pos]);
	prepare_rx();
	NRF_RADIO->TASKS_RXEN = 1;
}

/*
 * Stop listening at time `t_us` (TIMER compare 4) unless an access address
 * arrived by then. A time that is already over becomes "in 20 us".
 */
static void set_rx_deadline(uint32_t t_us)
{
	uint32_t now = timer_now();

	if ((int32_t)(t_us - now) <= 0) {
		t_us = now + 20u;
	}
	NRF_TIMER3->CC[TIMER_CC_RXOFF] = t_us;
	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_RXOFF] = 0;
	NRF_TIMER3->INTENSET = TIMER_INTENSET_COMPARE4_Msk;
}

/* Cancel the listening deadline. */
static void clear_rx_deadline(void)
{
	NRF_TIMER3->INTENCLR = TIMER_INTENCLR_COMPARE4_Msk;
	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_RXOFF] = 0;
	NVIC_ClearPendingIRQ(TIMER3_IRQn);
}

/* Restart the channel hop timer: next hop in `period_us`. */
static void restart_hop_timer(uint32_t period_us)
{
	hop_period_us = period_us;
	NRF_TIMER3->CC[TIMER_CC_HOP] = timer_now() + period_us;
	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_HOP] = 0;
}

/* ------------------------------------------------------------------------ */
/* Queue                                                                     */
/* ------------------------------------------------------------------------ */

/*
 * Reserve the slot at the head for a new entry. Returns NULL (and counts the
 * loss) if the queue is full; the slot is then reused by the next packet.
 */
static struct ble_packet *reserve_slot(void)
{
	uint8_t next = (uint8_t)((ring_head + 1u) % RING_SLOTS);

	if (next == ring_tail) {
		drop_count++;
		return NULL;
	}
	return &ring[ring_head];
}

/* Make the reserved slot visible to the main loop. */
static void commit_slot(void)
{
	__DMB();                                   /* publish the data before the index */
	ring_head = (uint8_t)((ring_head + 1u) % RING_SLOTS);
}

/* Queue a status record (kind != BLE_KIND_PACKET) with a snapshot of the connection. */
static void publish_status(uint8_t kind, uint32_t t_us)
{
	struct ble_packet *p = reserve_slot();

	if (p == NULL) {
		return;
	}
	p->kind = kind;
	p->t_us = t_us;
	p->channel = 0;
	p->rssi = 0;
	p->phy = BLE_PHY_1M;
	p->flags = 0;
	p->evt = follow.counter;
	p->aa = follow.access_address;
	ble_follow_info(&follow, &p->info);
	commit_slot();
}

/*
 * Queue the packet the RADIO just wrote into ring[head] (END happened, the
 * RADIO is disabled). `start_us` = start of the packet, the RADIO result
 * registers (CRC, RSSI) are read here.
 */
static void publish_packet(uint8_t channel, uint32_t aa, uint8_t flags, uint32_t evt,
			   uint32_t start_us, int8_t rssi)
{
	struct ble_packet *p = reserve_slot();
	uint32_t crc = NRF_RADIO->RXCRC;

	if (p == NULL) {
		return;
	}
	p->crc[0] = (uint8_t)(crc & 0xFFu);
	p->crc[1] = (uint8_t)((crc >> 8) & 0xFFu);
	p->crc[2] = (uint8_t)((crc >> 16) & 0xFFu);
	p->kind = BLE_KIND_PACKET;
	p->aa = aa;
	p->channel = channel;
	p->rssi = rssi;
	p->phy = BLE_PHY_1M;
	p->flags = flags;
	p->evt = evt;
	p->t_us = start_us;
	commit_slot();
}

/* ------------------------------------------------------------------------ */
/* Connection following                                                      */
/* ------------------------------------------------------------------------ */

/*
 * Prepare the receiver for the connection event described by `plan`: tune,
 * and start the RADIO at plan.rx_on_us through TIMER compare 3 and PPI (no
 * interrupt latency); a window that is due already starts immediately.
 */
static void schedule_event_rx(const struct ble_rx_plan *p)
{
	tune(p->channel);
	prepare_rx();
	set_rx_deadline(p->rx_off_us);

	if ((int32_t)(p->rx_on_us - timer_now()) <= 5) {
		NRF_RADIO->TASKS_RXEN = 1;             /* too late for the timer: start now */
		return;
	}
	NRF_TIMER3->CC[TIMER_CC_RXON] = p->rx_on_us;
	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_RXON] = 0;
	NRF_PPI->CHENSET = 1u << PPI_CH_RXON;
}

/* The followed connection is over: back to scanning for the selected device. */
static void leave_connection(void)
{
	rmode = R_SCAN;
	tifs_wait = false;
	aligned = false;
	align_pending = false;
	hop_due = false;
	NRF_PPI->CHENCLR = 1u << PPI_CH_RXON;
	clear_rx_deadline();
	use_advertising_parameters();
	if (cfg.channel_count > 1u && cfg.dwell_ms != 0u) {
		restart_hop_timer((uint32_t)cfg.dwell_ms * 1000u);
		NRF_TIMER3->INTENSET = TIMER_INTENSET_COMPARE1_Msk;
	}
	arm_scan_rx();
}

/* A CONNECT_IND of the followed device was accepted: switch to following. */
static void enter_connection(uint32_t connect_start_us)
{
	rmode = R_CONN;
	tifs_wait = false;
	NRF_TIMER3->INTENCLR = TIMER_INTENCLR_COMPARE1_Msk;   /* no hopping while connected */
	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_HOP] = 0;
	clear_rx_deadline();
	use_connection_parameters();
	publish_status(BLE_KIND_CONN_NEW, connect_start_us);

	if (!ble_follow_next_event(&follow, &plan)) {
		leave_connection();                    /* cannot happen: parameters were validated */
		return;
	}
	schedule_event_rx(&plan);
}

/*
 * DISABLED interrupt while following. `got_packet`: a packet was received
 * (END happened); otherwise the listening window ended without one.
 */
static void connection_isr(bool got_packet)
{
	if (got_packet) {
		struct ble_packet *slot = &ring[ring_head];   /* the RADIO wrote here */
		uint32_t start_us = NRF_TIMER3->CC[TIMER_CC_ADDRESS] - T_PACKET_START_1M_US;
		bool crc_ok = NRF_RADIO->CRCSTATUS == RADIO_CRCSTATUS_CRCSTATUS_CRCOk;
		int8_t rssi = (int8_t)(-(int)NRF_RADIO->RSSISAMPLE);
		struct ble_pkt_result res;

		ble_follow_on_data_packet(&follow, slot->raw, 2u + (size_t)slot->raw[1], crc_ok,
					  start_us, &res);

		/* map the follow result flags to the report flags; connection packets are never RSSI filtered */
		uint8_t flags = BLE_FLAG_DATA | (crc_ok ? BLE_FLAG_CRC_OK : 0u);

		flags |= (res.flags & BLE_PKT_DIR_S2M) ? BLE_FLAG_DIR_S2M : 0u;
		flags |= (res.flags & BLE_PKT_ANCHOR) ? BLE_FLAG_ANCHOR : 0u;
		flags |= (res.flags & BLE_PKT_GAP) ? BLE_FLAG_GAP : 0u;
		publish_packet(plan.channel, follow.access_address, flags, follow.counter, start_us, rssi);

		if (res.flags & BLE_PKT_CONTINUE) {
			/* another packet follows after T_IFS: re-arm at once on the same channel */
			prepare_rx();
			NRF_RADIO->TASKS_RXEN = 1;
			set_rx_deadline(res.rx_off_us);
			return;
		}
	}

	/* The event is over: plan the next one (also if this one produced no packet) */
	clear_rx_deadline();
	if (!ble_follow_next_event(&follow, &plan)) {
		publish_status(BLE_KIND_CONN_LOST, timer_now());
		leave_connection();
		return;
	}
	if (plan.flags & BLE_PLAN_UPDATED) {
		publish_status(BLE_KIND_CONN_UPD, timer_now());
	}
	schedule_event_rx(&plan);
}

/* ------------------------------------------------------------------------ */
/* Scanning                                                                  */
/* ------------------------------------------------------------------------ */

/*
 * DISABLED interrupt while scanning. `got_packet`: an advertising channel
 * packet was received completely. Judge it, queue it, then choose the next
 * receive: same channel for a response (T_IFS), the next channel (alignment
 * or dwell hop), or the same channel again.
 */
static void scan_isr(bool got_packet)
{
	bool wait = false;

	if (got_packet) {
		struct ble_packet *slot = &ring[ring_head];   /* the RADIO wrote here */
		uint32_t start_us = NRF_TIMER3->CC[TIMER_CC_ADDRESS] - T_PACKET_START_1M_US;
		bool crc_ok = NRF_RADIO->CRCSTATUS == RADIO_CRCSTATUS_CRCSTATUS_CRCOk;
		int8_t rssi = (int8_t)(-(int)NRF_RADIO->RSSISAMPLE);
		uint8_t result = ble_follow_on_adv(&follow, slot->raw, 2u + (size_t)slot->raw[1],
						   crc_ok, start_us);

		/* The RSSI threshold applies to advertising packets only; it never hides a connection. */
		if ((result & BLE_FOLLOW_FORWARD) && rssi >= cfg.rssi_min) {
			publish_packet(cfg.channels[channel_pos], ADV_ACCESS_ADDRESS,
				       crc_ok ? BLE_FLAG_CRC_OK : 0u, 0, start_us, rssi);
		}
		if (result & BLE_FOLLOW_CONNECT) {
			enter_connection(start_us);        /* switches the RADIO to the connection */
			return;
		}
		if (cfg.follow && (result & BLE_FOLLOW_FORWARD)) {
			align_pending = true;
		}
		if (result & BLE_FOLLOW_WAIT) {
			wait = true;
			set_rx_deadline(ble_pkt_end_us(start_us, slot->raw[1]) + BLE_IFS_LISTEN_US);
		}
	}

	tifs_wait = wait;
	if (!wait) {
		clear_rx_deadline();
		if (align_pending) {
			align_pending = false;
			if (cfg.channel_count > 1u && cfg.dwell_ms != 0u) {
				/* the advertiser sends on the next channel soon: go there and wait briefly */
				channel_pos = (uint8_t)((channel_pos + 1u) % cfg.channel_count);
				aligned = true;
				hop_due = false;
				restart_hop_timer(ALIGN_WINDOW_US);
			}
		} else if (hop_due) {
			hop_due = false;
			if (aligned) {
				/* nothing came in the alignment window: back to the first channel */
				aligned = false;
				channel_pos = 0;
				restart_hop_timer((uint32_t)cfg.dwell_ms * 1000u);
			} else {
				channel_pos = (uint8_t)((channel_pos + 1u) % cfg.channel_count);
			}
		}
	}
	arm_scan_rx();
}

/* ------------------------------------------------------------------------ */
/* Interrupt handlers                                                        */
/* ------------------------------------------------------------------------ */

/*
 * RADIO interrupt: DISABLED event. Either a packet ended (END short) or the
 * receiver was disabled by a hop / listening deadline.
 */
static void radio_isr(const void *arg)
{
	ARG_UNUSED(arg);

	if (NRF_RADIO->EVENTS_DISABLED == 0) {
		return;
	}
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_PPI->CHENCLR = 1u << PPI_CH_RXON;      /* the timed start is a one shot */

	bool got_packet = NRF_RADIO->EVENTS_END != 0;

	NRF_RADIO->EVENTS_END = 0;
	if (rmode == R_CONN) {
		connection_isr(got_packet);
	} else {
		scan_isr(got_packet);
	}
}

/*
 * TIMER compare interrupt:
 *   compare 1: the dwell time on the channel is over. Request a hop; interrupt
 *              an idle receiver, but never one that is inside a packet or
 *              waiting for a response.
 *   compare 4: the listening deadline passed. Stop the receiver unless a
 *              packet has started.
 */
static void timer_isr(const void *arg)
{
	ARG_UNUSED(arg);

	/*
	 * Only react to a compare whose interrupt is enabled: the compare events
	 * of a disabled one (e.g. the hop timer while following) still get set.
	 */
	if ((NRF_TIMER3->INTENSET & TIMER_INTENSET_COMPARE1_Msk) != 0u &&
	    NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_HOP] != 0) {
		NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_HOP] = 0;
		NRF_TIMER3->CC[TIMER_CC_HOP] += hop_period_us;     /* next hop time */
		hop_due = true;
		if (!tifs_wait && NRF_RADIO->EVENTS_ADDRESS == 0) {
			/* no packet in progress: the DISABLED interrupt will do the hop */
			NRF_RADIO->TASKS_DISABLE = 1;
		}
		/* else: a packet is being received (or a response awaited), hop afterwards */
	}
	if ((NRF_TIMER3->INTENSET & TIMER_INTENSET_COMPARE4_Msk) != 0u &&
	    NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_RXOFF] != 0) {
		NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_RXOFF] = 0;
		NRF_TIMER3->INTENCLR = TIMER_INTENCLR_COMPARE4_Msk;
		if (NRF_RADIO->EVENTS_ADDRESS == 0) {
			NRF_RADIO->TASKS_DISABLE = 1;      /* nothing arrived: DISABLED ends the window */
		}
	}
}

/* ------------------------------------------------------------------------ */
/* Public API                                                                */
/* ------------------------------------------------------------------------ */

void ble_radio_start(const struct ble_config *c)
{
	ble_radio_stop();                          /* clean slate, also if called twice */

	cfg = *c;
	channel_pos = 0;
	ring_head = 0;
	ring_tail = 0;
	drop_count = 0;
	hop_due = false;
	tifs_wait = false;
	align_pending = false;
	aligned = false;
	rmode = R_SCAN;

	/* Follow logic: selected device, "only advertising" overrides connection following */
	ble_follow_init(&follow);
	ble_follow_set_options(&follow, cfg.follow_conn && !cfg.only_adv, cfg.follow_rsp);
	ble_follow_set_target(&follow, cfg.follow ? cfg.follow_addr : NULL, cfg.follow_type);

	if (!irq_connected) {
		IRQ_CONNECT(RADIO_IRQn, 0, radio_isr, NULL, 0);
		IRQ_CONNECT(TIMER3_IRQn, 0, timer_isr, NULL, 0);
		irq_connected = true;
	}

	/* --- Time base: TIMER3, 32 bit, 16 MHz / 2^4 = 1 MHz ------------------ */
	NRF_TIMER3->MODE = TIMER_MODE_MODE_Timer << TIMER_MODE_MODE_Pos;
	NRF_TIMER3->BITMODE = TIMER_BITMODE_BITMODE_32Bit << TIMER_BITMODE_BITMODE_Pos;
	NRF_TIMER3->PRESCALER = 4;
	NRF_TIMER3->TASKS_CLEAR = 1;
	NRF_TIMER3->TASKS_START = 1;

	/* PPI: ADDRESS event -> capture the timer without CPU involvement */
	NRF_PPI->CH[PPI_CH_ADDRESS].EEP = (uint32_t)&NRF_RADIO->EVENTS_ADDRESS;
	NRF_PPI->CH[PPI_CH_ADDRESS].TEP = (uint32_t)&NRF_TIMER3->TASKS_CAPTURE[TIMER_CC_ADDRESS];
	NRF_PPI->CHENSET = 1u << PPI_CH_ADDRESS;
	/* PPI: timer compare -> RXEN, used to start the receiver exactly at a connection event (enabled per event) */
	NRF_PPI->CH[PPI_CH_RXON].EEP = (uint32_t)&NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_RXON];
	NRF_PPI->CH[PPI_CH_RXON].TEP = (uint32_t)&NRF_RADIO->TASKS_RXEN;

	/* --- RADIO: BLE 1M PHY, advertising access address -------------------- */
	NRF_RADIO->MODE = RADIO_MODE_MODE_Ble_1Mbit << RADIO_MODE_MODE_Pos;
	NRF_RADIO->MODECNF0 = RADIO_MODECNF0_RU_Fast << RADIO_MODECNF0_RU_Pos;   /* fast ramp-up */

	/* Packet layout: 1 byte S0 (PDU header 0), 8 bit LENGTH, no S1, 8 bit preamble */
	NRF_RADIO->PCNF0 = (8u << RADIO_PCNF0_LFLEN_Pos) |
			   (1u << RADIO_PCNF0_S0LEN_Pos) |
			   (0u << RADIO_PCNF0_S1LEN_Pos) |
			   (RADIO_PCNF0_PLEN_8bit << RADIO_PCNF0_PLEN_Pos);
	/* Up to 255 payload bytes (extended advertising), 3 byte base address, whitening on */
	NRF_RADIO->PCNF1 = (255u << RADIO_PCNF1_MAXLEN_Pos) |
			   (0u << RADIO_PCNF1_STATLEN_Pos) |
			   (3u << RADIO_PCNF1_BALEN_Pos) |
			   (RADIO_PCNF1_ENDIAN_Little << RADIO_PCNF1_ENDIAN_Pos) |
			   (RADIO_PCNF1_WHITEEN_Enabled << RADIO_PCNF1_WHITEEN_Pos);

	/* CRC-24 over the PDU only (the access address is skipped) */
	NRF_RADIO->CRCCNF = (RADIO_CRCCNF_LEN_Three << RADIO_CRCCNF_LEN_Pos) |
			    (RADIO_CRCCNF_SKIPADDR_Skip << RADIO_CRCCNF_SKIPADDR_Pos);
	NRF_RADIO->CRCPOLY = CRC_POLY;
	use_advertising_parameters();

	/*
	 * READY -> START: start receiving after ramp-up
	 * ADDRESS -> RSSISTART: sample the RSSI while the packet is received
	 * END -> DISABLE: one packet per RXEN, the DISABLED interrupt decides
	 * DISABLED -> RSSISTOP: stop the RSSI measurement
	 */
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk |
			    RADIO_SHORTS_ADDRESS_RSSISTART_Msk |
			    RADIO_SHORTS_END_DISABLE_Msk |
			    RADIO_SHORTS_DISABLED_RSSISTOP_Msk;

	/* Channel hopping timer (only with more than one channel and a dwell time) */
	NRF_TIMER3->INTENCLR = 0xFFFFFFFFu;
	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_HOP] = 0;
	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_RXOFF] = 0;
	if (cfg.channel_count > 1u && cfg.dwell_ms != 0u) {
		restart_hop_timer((uint32_t)cfg.dwell_ms * 1000u);
		NRF_TIMER3->INTENSET = TIMER_INTENSET_COMPARE1_Msk;
	}
	NVIC_ClearPendingIRQ(TIMER3_IRQn);
	irq_enable(TIMER3_IRQn);

	NRF_RADIO->INTENSET = RADIO_INTENSET_DISABLED_Msk;
	NVIC_ClearPendingIRQ(RADIO_IRQn);
	irq_enable(RADIO_IRQn);
	arm_scan_rx();
}

void ble_radio_stop(void)
{
	/* No interrupts first, then bring everything back to its reset state */
	irq_disable(RADIO_IRQn);
	irq_disable(TIMER3_IRQn);
	NRF_RADIO->INTENCLR = 0xFFFFFFFFu;
	NRF_TIMER3->INTENCLR = 0xFFFFFFFFu;

	radio_disable_and_wait();
	NRF_RADIO->MODECNF0 = 0;                   /* default ramp-up again (XN297L backend) */

	NRF_PPI->CHENCLR = (1u << PPI_CH_ADDRESS) | (1u << PPI_CH_RXON);
	NRF_TIMER3->TASKS_STOP = 1;
	NRF_TIMER3->TASKS_CLEAR = 1;
}

const struct ble_packet *ble_radio_peek(void)
{
	if (ring_tail == ring_head) {
		return NULL;                           /* queue empty */
	}
	return &ring[ring_tail];
}

void ble_radio_release(void)
{
	if (ring_tail != ring_head) {
		__DMB();                               /* finish reading before freeing the slot */
		ring_tail = (uint8_t)((ring_tail + 1u) % RING_SLOTS);
	}
}

uint32_t ble_radio_take_drops(void)
{
	unsigned int key = irq_lock();             /* counter is written by the interrupt handler */
	uint32_t d = drop_count;

	drop_count = 0;
	irq_unlock(key);
	return d;
}
