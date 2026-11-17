/*
 * Bluetooth LE PDU parsing needed for connection following (pure C).
 *
 * All functions take the PDU as it is on air without access address and CRC:
 *     pdu[0]   header byte 0 (type / LLID and flags)
 *     pdu[1]   length of the payload
 *     pdu[2..] payload
 * Layouts: Core Specification Vol 6 Part B 2.3 (advertising channel PDUs),
 * 2.4 (data channel PDUs) and 2.4.2 (LL control PDUs). Multi byte fields are
 * little endian on air; the structs below hold native integers.
 * Python twin: extcap/ble_pdu.py (parse_connect_ind, parse_ll_control).
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef BLE_PDU_H_
#define BLE_PDU_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ble_csa.h"

/* Advertising channel PDU types (header byte 0, bits 3..0) */
#define BLE_ADV_IND          0x0u
#define BLE_ADV_DIRECT_IND   0x1u
#define BLE_ADV_NONCONN_IND  0x2u
#define BLE_SCAN_REQ         0x3u
#define BLE_SCAN_RSP         0x4u
#define BLE_CONNECT_IND      0x5u
#define BLE_ADV_SCAN_IND     0x6u

/* Header byte 0 flags of advertising PDUs */
#define BLE_ADV_HDR_CHSEL    0x20u   /* ChSel: supports channel selection algorithm #2 */
#define BLE_ADV_HDR_TXADD    0x40u   /* TxAdd: transmitter address is random           */
#define BLE_ADV_HDR_RXADD    0x80u   /* RxAdd: receiver address is random              */

/* Data channel PDU header byte 0 */
#define BLE_DATA_LLID_MASK   0x03u
#define BLE_DATA_LLID_CTRL   0x03u   /* LL control PDU                                 */
#define BLE_DATA_MD          0x10u   /* More Data                                      */

/* LL control opcodes used while following */
#define BLE_LL_CONNECTION_UPDATE_IND 0x00u
#define BLE_LL_CHANNEL_MAP_IND       0x01u
#define BLE_LL_TERMINATE_IND         0x02u
#define BLE_LL_START_ENC_REQ         0x05u

/* Size of the CONNECT_IND payload: InitA 6 + AdvA 6 + LLData 22 */
#define BLE_CONNECT_IND_LEN  34u

/* Content of a CONNECT_IND (LLData in native integers). */
struct ble_connect_ind {
	uint8_t init_a[6];                /* initiator address, on-air order (LSB first)    */
	uint8_t adv_a[6];                 /* advertiser address, on-air order               */
	bool tx_add;                      /* initiator address is random                    */
	bool rx_add;                      /* advertiser address is random                   */
	bool ch_sel;                      /* ChSel bit of the CONNECT_IND header            */
	uint32_t access_address;
	uint32_t crc_init;                /* 24 bit                                         */
	uint8_t win_size;                 /* transmit window size, 1.25 ms units            */
	uint16_t win_offset;              /* transmit window offset, 1.25 ms units          */
	uint16_t interval;                /* connection interval, 1.25 ms units             */
	uint16_t latency;                 /* slave latency in events                        */
	uint16_t timeout;                 /* supervision timeout, 10 ms units               */
	uint8_t chmap[BLE_CHMAP_LEN];     /* channel map                                    */
	uint8_t hop;                      /* hop increment 5..16                            */
	uint8_t sca;                      /* sleep clock accuracy index 0..7                */
};

/* LL_CONNECTION_UPDATE_IND content (Vol 6 Part B 2.4.2.1). */
struct ble_conn_update {
	uint8_t win_size;
	uint16_t win_offset;
	uint16_t interval;
	uint16_t latency;
	uint16_t timeout;
	uint16_t instant;
};

/* LL_CHANNEL_MAP_IND content (Vol 6 Part B 2.4.2.2). */
struct ble_chmap_update {
	uint8_t chmap[BLE_CHMAP_LEN];
	uint16_t instant;
};

/*
 * Parse a CONNECT_IND. Fails (false) if the PDU type is not CONNECT_IND, the
 * length is not 34 or the PDU is shorter than its length field says.
 */
bool ble_pdu_parse_connect_ind(const uint8_t *pdu, size_t pdu_len, struct ble_connect_ind *out);

/* LL_CONNECTION_UPDATE_IND: `payload` starts at the opcode byte. False if malformed. */
bool ble_pdu_parse_conn_update(const uint8_t *payload, size_t len, struct ble_conn_update *out);

/* LL_CHANNEL_MAP_IND: `payload` starts at the opcode byte. False if malformed. */
bool ble_pdu_parse_chmap_update(const uint8_t *payload, size_t len, struct ble_chmap_update *out);

#endif /* BLE_PDU_H_ */
