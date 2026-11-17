/*
 * Bluetooth LE PDU parsing needed for connection following (pure C).
 * See ble_pdu.h. Independent implementation of the public Core Specification.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <string.h>

#include "ble_pdu.h"

/* Little endian 16 bit read. */
static uint16_t le16(const uint8_t *p)
{
	return (uint16_t)(p[0] | (p[1] << 8));
}

bool ble_pdu_parse_connect_ind(const uint8_t *pdu, size_t pdu_len, struct ble_connect_ind *out)
{
	if (pdu_len < 2u || (pdu[0] & 0x0Fu) != BLE_CONNECT_IND ||
	    pdu[1] != BLE_CONNECT_IND_LEN || pdu_len < 2u + BLE_CONNECT_IND_LEN) {
		return false;
	}
	const uint8_t *p = &pdu[2];                /* payload: InitA, AdvA, LLData */

	out->tx_add = (pdu[0] & BLE_ADV_HDR_TXADD) != 0u;
	out->rx_add = (pdu[0] & BLE_ADV_HDR_RXADD) != 0u;
	out->ch_sel = (pdu[0] & BLE_ADV_HDR_CHSEL) != 0u;
	memcpy(out->init_a, &p[0], 6);
	memcpy(out->adv_a, &p[6], 6);
	/* LLData starts at payload offset 12 */
	out->access_address = (uint32_t)p[12] | ((uint32_t)p[13] << 8) |
			      ((uint32_t)p[14] << 16) | ((uint32_t)p[15] << 24);
	out->crc_init = (uint32_t)p[16] | ((uint32_t)p[17] << 8) | ((uint32_t)p[18] << 16);
	out->win_size = p[19];
	out->win_offset = le16(&p[20]);
	out->interval = le16(&p[22]);
	out->latency = le16(&p[24]);
	out->timeout = le16(&p[26]);
	memcpy(out->chmap, &p[28], BLE_CHMAP_LEN);
	out->chmap[4] &= 0x1Fu;                    /* only 37 channels: drop reserved bits */
	out->hop = p[33] & 0x1Fu;                  /* low 5 bits: hop increment */
	out->sca = (uint8_t)(p[33] >> 5);          /* high 3 bits: sleep clock accuracy */
	return true;
}

bool ble_pdu_parse_conn_update(const uint8_t *payload, size_t len, struct ble_conn_update *out)
{
	/* opcode (1) + WinSize 1 + WinOffset 2 + Interval 2 + Latency 2 + Timeout 2 + Instant 2 */
	if (len != 12u || payload[0] != BLE_LL_CONNECTION_UPDATE_IND) {
		return false;
	}
	out->win_size = payload[1];
	out->win_offset = le16(&payload[2]);
	out->interval = le16(&payload[4]);
	out->latency = le16(&payload[6]);
	out->timeout = le16(&payload[8]);
	out->instant = le16(&payload[10]);
	return true;
}

bool ble_pdu_parse_chmap_update(const uint8_t *payload, size_t len, struct ble_chmap_update *out)
{
	/* opcode (1) + ChM 5 + Instant 2 */
	if (len != 8u || payload[0] != BLE_LL_CHANNEL_MAP_IND) {
		return false;
	}
	memcpy(out->chmap, &payload[1], BLE_CHMAP_LEN);
	out->chmap[4] &= 0x1Fu;
	out->instant = le16(&payload[6]);
	return true;
}
