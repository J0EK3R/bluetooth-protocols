/*
 * Raw receiver on top of the nRF52840 RADIO peripheral.
 *
 * The RADIO is used as a "dumb" GFSK receiver:
 *   - it synchronises on a configurable sync word (3 ... 5 bytes),
 *   - hardware CRC and hardware whitening are switched off,
 *   - a fixed number of bytes following the sync word is captured.
 *
 * All byte values in this API are given in ON-AIR ORDER, MSB FIRST, i.e. the
 * order in which the bits leave the antenna of the transmitter. This is the
 * same notation as used in Chips/XN297L.md ("on-air form").
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef RADIO_H_
#define RADIO_H_

#include <stdbool.h>
#include <stdint.h>

/* Limits */
#define RADIO_SYNC_MIN      3u      /* BALEN 2 + 1 prefix byte              */
#define RADIO_SYNC_MAX      5u      /* BALEN 4 + 1 prefix byte              */
#define RADIO_LEN_MAX       250u    /* bytes captured after the sync word  */
#define RADIO_CHANNELS_MAX  16u     /* entries in the hopping list          */

/* Supported on-air data rates / modulation settings */
enum radio_rate {
	RADIO_RATE_NRF_1M = 0,  /* Nordic proprietary 1 Mbps (deviation ~170 kHz) */
	RADIO_RATE_NRF_2M = 1,  /* Nordic proprietary 2 Mbps (old XN297 only)     */
	RADIO_RATE_BLE_1M = 2,  /* BLE 1M PHY (deviation ~250 kHz)                */
};

/* Receiver configuration */
struct radio_config {
	uint8_t sync[RADIO_SYNC_MAX];   /* sync word, on-air order, MSB first  */
	uint8_t sync_len;               /* 3 ... 5                              */
	uint8_t capture_len;            /* bytes captured after the sync word   */
	uint8_t channels[RADIO_CHANNELS_MAX]; /* RF channel = MHz - 2400        */
	uint8_t channel_count;          /* 1 ... RADIO_CHANNELS_MAX            */
	uint16_t dwell_ms;              /* time per channel, 0 = no hopping     */
	enum radio_rate rate;
};

/* One received packet */
struct radio_packet {
	uint32_t timestamp_us;          /* device uptime when the packet ended  */
	uint8_t channel;                /* RF channel (MHz - 2400)              */
	int8_t rssi_dbm;                /* RSSI sampled after the sync word     */
	uint8_t len;                    /* number of bytes in data[]            */
	uint8_t data[RADIO_LEN_MAX];    /* captured bytes, on-air order, MSB first */
};

/* Start the high-frequency crystal oscillator (required by the RADIO). */
int radio_hfclk_start(void);

/* Apply a configuration and start receiving on the first channel. */
void radio_start(const struct radio_config *cfg);

/* Stop receiving and disable the RADIO. */
void radio_stop(void);

/*
 * Poll the RADIO. Must be called frequently from the main loop.
 * Handles channel hopping and returns true if a packet was received
 * (copied to *pkt). The receiver is re-armed automatically.
 */
bool radio_poll(struct radio_packet *pkt);

/* Currently selected RF channel (MHz - 2400). */
uint8_t radio_current_channel(void);

#endif /* RADIO_H_ */
