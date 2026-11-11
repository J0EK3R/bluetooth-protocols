/*
 * Raw receiver on top of the nRF52840 RADIO peripheral.
 *
 * How an XN297L frame is received
 * -------------------------------
 * The XN297L sends (on-air order, MSB first):
 *
 *     71 0F 55 | address 3..5 B | payload | CRC 2 B
 *     preamble  \______ scrambled (if enabled) ______/
 *
 * The nRF52840 in "Nrf_1Mbit" mode expects:
 *
 *     preamble 1 B (0x55/0xAA) | address (BASE + PREFIX) | payload ...
 *
 * The last XN297L preamble byte 0x55 serves as the nRF preamble, and the
 * (scrambled) XN297L address is used as the nRF address. Everything after the
 * address is captured as raw payload with CRC and whitening disabled; the
 * host software descrambles and checks the XN297L CRC.
 *
 * Alternatively the sync word can be set to the XN297L preamble 71 0F 55
 * itself ("promiscuous" mode, address unknown). Then the address is part of
 * the captured bytes. This mode is experimental: the nRF expects an
 * alternating preamble in front of the sync word, which is not present.
 *
 * Bit order
 * ---------
 * The RADIO always transmits/receives the address LSB first, starting with the
 * least significant used byte of BASEn, followed by PREFIXn (this is how the
 * BLE access address 0x8E89BED6 ends up on air as D6 BE 89 8E, LSB first).
 * To match on-air bytes given MSB first, every byte is bit-reversed and placed
 * accordingly (see set_sync_word()).
 * The payload is received MSB first by setting PCNF1.ENDIAN = Big, so the
 * captured bytes are already in on-air MSB-first notation.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/drivers/clock_control.h>
#include <zephyr/drivers/clock_control/nrf_clock_control.h>
#include <soc.h>    /* NRF_RADIO and register bit definitions (nrfx MDK) */

#include "radio.h"

/* Active configuration (copied in radio_start()) */
static struct radio_config active_cfg;

/* Index into active_cfg.channels[] and time of the last hop */
static uint8_t channel_index;
static int64_t last_hop_ms;

/* Receive buffer the RADIO writes into via EasyDMA (must be in RAM) */
static uint8_t rx_buffer[RADIO_LEN_MAX + 1];

/* True while the receiver is running */
static bool running;

/* ------------------------------------------------------------------------ */
/* Helpers                                                                   */
/* ------------------------------------------------------------------------ */

/* Reverse the bit order of one byte (0b00000001 -> 0b10000000). */
static uint8_t rev8(uint8_t b)
{
	b = (uint8_t)((b & 0xF0u) >> 4 | (b & 0x0Fu) << 4);
	b = (uint8_t)((b & 0xCCu) >> 2 | (b & 0x33u) << 2);
	b = (uint8_t)((b & 0xAAu) >> 1 | (b & 0x55u) << 1);
	return b;
}

/* Disable the RADIO and wait until it is really disabled. */
static void radio_disable_and_wait(void)
{
	NRF_RADIO->SHORTS = 0;
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->TASKS_DISABLE = 1;
	while (NRF_RADIO->EVENTS_DISABLED == 0) {
		/* busy wait, takes only a few microseconds */
	}
	NRF_RADIO->EVENTS_DISABLED = 0;
}

/*
 * Program BASE0/PREFIX0 so that the RADIO matches the given on-air bytes.
 *
 * sync[0] is the first byte on air, given MSB first. With n bytes:
 *   - the first n-1 bytes go to BASE0 (BALEN = n-1),
 *   - the last byte goes to PREFIX0 (AP0).
 *
 * BASE0 uses its most significant BALEN bytes; on air the least significant
 * of those comes first. Example for BALEN = 3 (same layout as BLE):
 *   BASE0 = rev8(s0) << 8 | rev8(s1) << 16 | rev8(s2) << 24, PREFIX0 = rev8(s3)
 */
static void set_sync_word(const uint8_t *sync, uint8_t n)
{
	uint8_t balen = (uint8_t)(n - 1u);
	uint32_t base = 0;

	for (uint8_t i = 0; i < balen; i++) {
		/* byte i of the base address goes to bit position 8 * (4 - balen + i) */
		base |= (uint32_t)rev8(sync[i]) << (8u * (4u - balen + i));
	}

	NRF_RADIO->BASE0 = base;
	NRF_RADIO->PREFIX0 = rev8(sync[n - 1u]);   /* AP0 = bits 7:0 */
	NRF_RADIO->RXADDRESSES = 1u;                /* only logical address 0 */
}

/* Tune to the channel at channel_index and (re)start the receiver. */
static void start_rx_on_current_channel(void)
{
	radio_disable_and_wait();

	NRF_RADIO->FREQUENCY = active_cfg.channels[channel_index];

	/*
	 * Shortcuts:
	 *   READY   -> START     : start receiving as soon as RX is ramped up
	 *   ADDRESS -> RSSISTART : sample RSSI right after the sync word matched
	 *   DISABLED-> RSSISTOP  : stop RSSI measurement when disabled
	 */
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk |
			    RADIO_SHORTS_ADDRESS_RSSISTART_Msk |
			    RADIO_SHORTS_DISABLED_RSSISTOP_Msk;

	NRF_RADIO->EVENTS_READY = 0;
	NRF_RADIO->EVENTS_ADDRESS = 0;
	NRF_RADIO->EVENTS_END = 0;
	NRF_RADIO->TASKS_RXEN = 1;

	last_hop_ms = k_uptime_get();
}

/* ------------------------------------------------------------------------ */
/* Public API                                                                */
/* ------------------------------------------------------------------------ */

int radio_hfclk_start(void)
{
	/*
	 * The RADIO needs the external 32 MHz crystal (HFXO). Request it through
	 * the Zephyr clock control driver so it stays on together with USB.
	 */
	struct onoff_manager *mgr =
		z_nrf_clock_control_get_onoff(CLOCK_CONTROL_NRF_SUBSYS_HF);
	struct onoff_client cli;
	int res = 0;
	int err;

	if (mgr == NULL) {
		return -ENXIO;
	}

	sys_notify_init_spinwait(&cli.notify);
	err = onoff_request(mgr, &cli);
	if (err < 0) {
		return err;
	}

	/* Wait until the crystal is running */
	do {
		err = sys_notify_fetch_result(&cli.notify, &res);
	} while (err == -EAGAIN);

	return (err < 0) ? err : res;
}

void radio_start(const struct radio_config *cfg)
{
	active_cfg = *cfg;
	channel_index = 0;

	radio_disable_and_wait();

	/* --- Data rate / modulation ------------------------------------------ */
	switch (active_cfg.rate) {
	case RADIO_RATE_NRF_2M:
		NRF_RADIO->MODE = RADIO_MODE_MODE_Nrf_2Mbit << RADIO_MODE_MODE_Pos;
		break;
	case RADIO_RATE_BLE_1M:
		NRF_RADIO->MODE = RADIO_MODE_MODE_Ble_1Mbit << RADIO_MODE_MODE_Pos;
		break;
	case RADIO_RATE_NRF_1M:
	default:
		NRF_RADIO->MODE = RADIO_MODE_MODE_Nrf_1Mbit << RADIO_MODE_MODE_Pos;
		break;
	}

	/*
	 * --- Packet layout ---------------------------------------------------
	 * PCNF0: no LENGTH, S0 or S1 field, 8-bit preamble.
	 */
	NRF_RADIO->PCNF0 = (0u << RADIO_PCNF0_LFLEN_Pos) |
			   (0u << RADIO_PCNF0_S0LEN_Pos) |
			   (0u << RADIO_PCNF0_S1LEN_Pos) |
			   (RADIO_PCNF0_PLEN_8bit << RADIO_PCNF0_PLEN_Pos);

	/*
	 * PCNF1: static payload length = capture_len, base address length =
	 * sync_len - 1, payload MSB first (ENDIAN = Big), whitening off.
	 */
	NRF_RADIO->PCNF1 =
		((uint32_t)active_cfg.capture_len << RADIO_PCNF1_MAXLEN_Pos) |
		((uint32_t)active_cfg.capture_len << RADIO_PCNF1_STATLEN_Pos) |
		((uint32_t)(active_cfg.sync_len - 1u) << RADIO_PCNF1_BALEN_Pos) |
		(RADIO_PCNF1_ENDIAN_Big << RADIO_PCNF1_ENDIAN_Pos) |
		(RADIO_PCNF1_WHITEEN_Disabled << RADIO_PCNF1_WHITEEN_Pos);

	/* --- Sync word (address) --------------------------------------------- */
	set_sync_word(active_cfg.sync, active_cfg.sync_len);

	/* --- No hardware CRC: the XN297L CRC is checked on the host ---------- */
	NRF_RADIO->CRCCNF = RADIO_CRCCNF_LEN_Disabled << RADIO_CRCCNF_LEN_Pos;

	/* --- Receive buffer --------------------------------------------------- */
	NRF_RADIO->PACKETPTR = (uint32_t)rx_buffer;

	running = true;
	start_rx_on_current_channel();
}

void radio_stop(void)
{
	running = false;
	radio_disable_and_wait();
}

uint8_t radio_current_channel(void)
{
	return active_cfg.channels[channel_index];
}

bool radio_poll(struct radio_packet *pkt)
{
	if (!running) {
		return false;
	}

	/* --- Packet received? ------------------------------------------------- */
	if (NRF_RADIO->EVENTS_END != 0) {
		NRF_RADIO->EVENTS_END = 0;

		/* Copy the packet before re-arming the receiver */
		pkt->timestamp_us = (uint32_t)k_ticks_to_us_floor64(k_uptime_ticks());
		pkt->channel = active_cfg.channels[channel_index];
		pkt->rssi_dbm = (int8_t)(-(int)NRF_RADIO->RSSISAMPLE);
		pkt->len = active_cfg.capture_len;
		memcpy(pkt->data, rx_buffer, active_cfg.capture_len);

		/* After END the RADIO is in RXIDLE: start the next reception */
		NRF_RADIO->EVENTS_ADDRESS = 0;
		NRF_RADIO->TASKS_START = 1;
		return true;
	}

	/* --- Channel hopping -------------------------------------------------- */
	if (active_cfg.dwell_ms != 0u && active_cfg.channel_count > 1u &&
	    (k_uptime_get() - last_hop_ms) >= active_cfg.dwell_ms) {
		/*
		 * Do not hop in the middle of a packet: if the sync word has
		 * already matched (ADDRESS event), wait for END first.
		 */
		if (NRF_RADIO->EVENTS_ADDRESS == 0) {
			channel_index = (uint8_t)((channel_index + 1u) %
						  active_cfg.channel_count);
			start_rx_on_current_channel();
		}
	}

	return false;
}
