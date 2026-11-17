/*
 * Bluetooth LE receiver (sniffer backend) on top of the nRF52840 RADIO.
 *
 * Milestone M1: passive scanning of the three advertising channels on the
 * LE 1M PHY. The RADIO is driven in BLE mode (hardware whitening and CRC-24
 * with the advertising access address 0x8E89BED6) and every packet,
 * including those with a bad CRC, is queued for the main loop.
 *
 * Everything time critical runs in interrupt context (RADIO and TIMER
 * interrupt at the highest priority); the main loop only picks up finished
 * packets with ble_radio_peek() / ble_radio_release().
 *
 * This is an independent implementation based on the public Bluetooth Core
 * Specification and the nRF52840 product specification.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef BLE_RADIO_H_
#define BLE_RADIO_H_

#include <stdbool.h>
#include <stdint.h>

/* Largest raw RADIO buffer: S0 (1) + LENGTH (1) + payload (255). */
#define BLE_RAW_MAX        257u
/* Number of advertising channels (37, 38, 39) */
#define BLE_ADV_CH_MAX     3u

/* Value of ble_config.rssi_min meaning "no RSSI filter" */
#define BLE_RSSI_OFF       (-127)

/* Report flag bits (the "flags" field of the B line, see main.c). */
#define BLE_FLAG_CRC_OK    0x01u    /* hardware CRC-24 check passed          */
#define BLE_FLAG_DIR_S2M   0x02u    /* slave -> master (connections, M2)     */
#define BLE_FLAG_DATA      0x04u    /* data channel PDU (M2)                 */
#define BLE_FLAG_AUX       0x08u    /* received on a secondary channel (M3)  */
#define BLE_FLAG_TRUNC     0x10u    /* packet truncated / overflow           */
#define BLE_FLAG_ANCHOR    0x20u    /* first packet of a connection event    */
#define BLE_FLAG_GAP       0x40u    /* a packet was probably missed (M2)     */

/* PHY values of the report (1 = LE 1M, 2 = LE 2M, 3/4 = coded S=8 / S=2) */
#define BLE_PHY_1M         1u

/* Scanner configuration */
struct ble_config {
	uint8_t channels[BLE_ADV_CH_MAX]; /* advertising channel indices 37..39, hop order */
	uint8_t channel_count;            /* 1 ... 3                                      */
	uint16_t dwell_ms;                /* time per channel, 0 = stay on the first      */
	int8_t rssi_min;                  /* advertising RSSI threshold in dBm            */
	bool only_adv;                    /* never follow connections (used from M2 on)   */
};

/* One received packet. The first part is filled by the interrupt handler. */
struct ble_packet {
	/* RADIO writes here (EasyDMA): [0] = PDU header byte 0 (S0), [1] = length, [2..] payload */
	uint8_t raw[BLE_RAW_MAX];
	uint8_t crc[3];                   /* CRC as received (RXCRC register, little endian) */
	uint8_t channel;                  /* BLE channel index 0..39                      */
	int8_t rssi;                      /* dBm                                          */
	uint8_t phy;                      /* BLE_PHY_*                                    */
	uint8_t flags;                    /* BLE_FLAG_*                                   */
	uint32_t evt;                     /* connection event counter (0 for advertising) */
	uint32_t t_us;                    /* device time of the packet start (preamble), us */
};

/* Apply the configuration and start scanning (RADIO, TIMER, PPI are fully initialised). */
void ble_radio_start(const struct ble_config *cfg);

/* Stop scanning and return RADIO/TIMER/PPI to their reset state. */
void ble_radio_stop(void);

/* Oldest unread packet or NULL. The packet stays valid until ble_radio_release(). */
const struct ble_packet *ble_radio_peek(void);

/* Release the packet returned by ble_radio_peek(). */
void ble_radio_release(void);

/* Packets lost because the queue was full since the last call (resets the counter). */
uint32_t ble_radio_take_drops(void);

#endif /* BLE_RADIO_H_ */
