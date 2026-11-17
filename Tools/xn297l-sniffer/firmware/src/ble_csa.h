/*
 * Bluetooth LE data channel selection (pure C, no hardware access).
 *
 * Implements channel selection algorithm #1 (Core Specification Vol 6 Part B
 * 4.5.8.2) and #2 (4.5.8.3), the channel map helpers they need and the
 * channel index -> RADIO frequency mapping. The Python twin used as test
 * oracle is tests/ble_csa_model.py; both are checked against the Core
 * Specification sample data (Vol 6 Part C 3) by tests/test_ble_csa.py.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef BLE_CSA_H_
#define BLE_CSA_H_

#include <stdbool.h>
#include <stdint.h>

/* Number of data channels (indices 0..36) */
#define BLE_DATA_CHANNELS    37u
/* Bytes of a channel map: 37 bits, channel 0 = bit 0 of byte 0 */
#define BLE_CHMAP_LEN        5u

/* Number of used channels in a channel map (reserved bits above 36 are ignored). */
uint8_t ble_csa_count_used(const uint8_t map[BLE_CHMAP_LEN]);

/* True if data channel `channel` (0..36) is marked as used in the map. */
bool ble_csa_is_used(const uint8_t map[BLE_CHMAP_LEN], uint8_t channel);

/*
 * Channel selection algorithm #1. `*last_unmapped` is the state kept between
 * events (starts at 0 for a new connection); it is advanced by one event.
 * Returns the data channel index of the event.
 */
uint8_t ble_csa1_next(uint8_t *last_unmapped, uint8_t hop, const uint8_t map[BLE_CHMAP_LEN]);

/* Channel identifier of algorithm #2: AA[31:16] xor AA[15:0]. */
uint16_t ble_csa2_channel_id(uint32_t access_address);

/* Pseudo random number prn_e of algorithm #2 for one event counter value. */
uint16_t ble_csa2_prn_e(uint16_t channel_id, uint16_t event_counter);

/* Channel selection algorithm #2: data channel index of event `event_counter`. */
uint8_t ble_csa2_channel(uint16_t channel_id, uint16_t event_counter,
			 const uint8_t map[BLE_CHMAP_LEN]);

/* RADIO FREQUENCY register value (MHz - 2400) of a channel index 0..39. */
uint8_t ble_channel_frequency(uint8_t channel);

#endif /* BLE_CSA_H_ */
