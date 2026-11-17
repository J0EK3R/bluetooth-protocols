/*
 * Bluetooth LE data channel selection (pure C, no hardware access).
 * See ble_csa.h. Independent implementation of the public Core Specification
 * Vol 6 Part B 4.5.8.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "ble_csa.h"

uint8_t ble_csa_count_used(const uint8_t map[BLE_CHMAP_LEN])
{
	uint8_t n = 0;

	for (uint8_t ch = 0; ch < BLE_DATA_CHANNELS; ch++) {
		if (ble_csa_is_used(map, ch)) {
			n++;
		}
	}
	return n;
}

bool ble_csa_is_used(const uint8_t map[BLE_CHMAP_LEN], uint8_t channel)
{
	return channel < BLE_DATA_CHANNELS && ((map[channel >> 3] >> (channel & 7u)) & 1u) != 0u;
}

/*
 * Remapping table lookup: the index-th used channel in ascending order.
 * Returns 0 for an empty map or an index beyond the used channels (cannot
 * happen for valid input; keeps the function total).
 */
static uint8_t remap(const uint8_t map[BLE_CHMAP_LEN], uint8_t index)
{
	for (uint8_t ch = 0; ch < BLE_DATA_CHANNELS; ch++) {
		if (ble_csa_is_used(map, ch)) {
			if (index == 0u) {
				return ch;
			}
			index--;
		}
	}
	return 0;
}

uint8_t ble_csa1_next(uint8_t *last_unmapped, uint8_t hop, const uint8_t map[BLE_CHMAP_LEN])
{
	/* unmappedChannel = (lastUnmappedChannel + hopIncrement) mod 37 */
	uint8_t unmapped = (uint8_t)((*last_unmapped + hop) % BLE_DATA_CHANNELS);
	uint8_t used = ble_csa_count_used(map);

	*last_unmapped = unmapped;                 /* the unmapped value is the state, not the result */
	if (ble_csa_is_used(map, unmapped) || used == 0u) {
		return unmapped;
	}
	/* unused channel: remappingIndex = unmapped mod numUsedChannels */
	return remap(map, (uint8_t)(unmapped % used));
}

uint16_t ble_csa2_channel_id(uint32_t access_address)
{
	return (uint16_t)((access_address >> 16) ^ (access_address & 0xFFFFu));
}

/* PERM: reverse the bit order inside each of the two bytes. */
static uint16_t perm(uint16_t v)
{
	uint16_t out = 0;

	for (uint8_t byte = 0; byte < 2u; byte++) {
		uint8_t in = (uint8_t)(v >> (8u * byte));
		uint8_t rev = 0;

		for (uint8_t bit = 0; bit < 8u; bit++) {
			rev = (uint8_t)((rev << 1) | ((in >> bit) & 1u));
		}
		out = (uint16_t)(out | ((uint16_t)rev << (8u * byte)));
	}
	return out;
}

/* MAM (multiply, add, modulo): (17 * a + b) mod 2^16. */
static uint16_t mam(uint16_t a, uint16_t b)
{
	return (uint16_t)(17u * a + b);
}

uint16_t ble_csa2_prn_e(uint16_t channel_id, uint16_t event_counter)
{
	uint16_t prn = (uint16_t)(event_counter ^ channel_id);

	for (uint8_t round = 0; round < 3u; round++) {
		prn = mam(perm(prn), channel_id);
	}
	return (uint16_t)(prn ^ channel_id);
}

uint8_t ble_csa2_channel(uint16_t channel_id, uint16_t event_counter,
			 const uint8_t map[BLE_CHMAP_LEN])
{
	uint16_t prn_e = ble_csa2_prn_e(channel_id, event_counter);
	uint8_t unmapped = (uint8_t)(prn_e % BLE_DATA_CHANNELS);
	uint8_t used = ble_csa_count_used(map);

	if (ble_csa_is_used(map, unmapped) || used == 0u) {
		return unmapped;
	}
	/* remappingIndex = floor(numUsedChannels * prn_e / 2^16) */
	return remap(map, (uint8_t)(((uint32_t)used * prn_e) >> 16));
}

uint8_t ble_channel_frequency(uint8_t channel)
{
	if (channel == 37u) {
		return 2;                              /* 2402 MHz */
	}
	if (channel == 38u) {
		return 26;                             /* 2426 MHz */
	}
	if (channel == 39u) {
		return 80;                             /* 2480 MHz */
	}
	/* data channels 0..10 -> 2404..2424 MHz, 11..36 -> 2428..2478 MHz */
	return (uint8_t)(channel <= 10u ? 4u + 2u * channel : 6u + 2u * channel);
}
