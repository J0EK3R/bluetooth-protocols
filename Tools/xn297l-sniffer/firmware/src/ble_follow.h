/*
 * Bluetooth LE connection following logic (pure C, no hardware access).
 *
 * This is the "brain" of the sniffer's follow mode. It is fed with plain
 * data (received PDUs, microsecond timestamps) and answers with plain data
 * (what to forward, where and when to listen next), so it can be compiled
 * and tested on a host. ble_radio.c is the only user and adds the RADIO,
 * TIMER and interrupt handling around it. Python twin and test oracle:
 * tests/ble_follow_model.py (compared by tests/test_ble_follow.py against a
 * host build of this file).
 *
 * Life cycle
 * ----------
 *   scan      ble_follow_on_adv() filters advertising packets of the followed
 *             device and recognises its CONNECT_IND (legacy). On a valid one
 *             the connection is set up.
 *   connected ble_follow_next_event() computes channel and listening window
 *             of the next connection event (channel selection #1 or #2,
 *             window widening, instants of connection / channel map updates)
 *             and ble_follow_on_data_packet() digests every received data
 *             channel packet (anchor, direction, More Data, LL control PDUs).
 *             Supervision timeout and LL_TERMINATE_IND end the connection;
 *             the sniffer then returns to scanning.
 *
 * All times are 32 bit microsecond values of one free running clock; they
 * wrap, so only differences are used.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef BLE_FOLLOW_H_
#define BLE_FOLLOW_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ble_pdu.h"

/* --- Timing constants (LE 1M PHY) ------------------------------------------ */
#define BLE_TIFS_US            150u    /* inter frame space                              */
#define BLE_OWN_PPM            50u     /* assumed accuracy of the sniffer clock          */
#define BLE_JITTER_US          16u     /* fixed window widening for timer jitter         */
#define BLE_RX_LEAD_US         50u     /* RADIO ramp-up (40 us) plus slack before the window */
#define BLE_AA_DETECT_US       40u     /* preamble + access address: time until ADDRESS  */
#define BLE_RX_MARGIN_US       30u     /* slack at the end of a listening window         */
#define BLE_IFS_LISTEN_US      240u    /* T_IFS + AA detection + slack after a packet    */
#define BLE_GAP_TOLERANCE_US   20u     /* allowed deviation of the gap between packets   */
#define BLE_ESTABLISH_EVENTS   6u      /* events without any packet before giving up     */
#define BLE_TRANSMIT_WINDOW_DELAY_US 1250u /* transmitWindowDelay for CONNECT_IND        */

/* --- Result flags of ble_follow_on_adv() ----------------------------------- */
#define BLE_FOLLOW_FORWARD     0x01u   /* report this packet                              */
#define BLE_FOLLOW_WAIT        0x02u   /* keep listening for a response after T_IFS       */
#define BLE_FOLLOW_CONNECT     0x04u   /* a connection was set up: call next_event()      */

/* --- Result flags of ble_follow_on_data_packet() --------------------------- */
#define BLE_PKT_DIR_S2M        0x01u   /* packet was sent by the slave                    */
#define BLE_PKT_ANCHOR         0x02u   /* first packet of the event                       */
#define BLE_PKT_GAP            0x04u   /* gap to the previous packet is not T_IFS         */
#define BLE_PKT_CONTINUE       0x08u   /* another packet is expected in this event        */

/* --- Flags of struct ble_rx_plan ------------------------------------------- */
#define BLE_PLAN_UPDATED       0x01u   /* a connection/channel map update was applied     */

/* --- Reasons why a connection ended ---------------------------------------- */
#define BLE_LOST_NONE          0u
#define BLE_LOST_TIMEOUT       1u      /* supervision timeout                              */
#define BLE_LOST_TERMINATE     2u      /* LL_TERMINATE_IND seen                            */
#define BLE_LOST_ESTABLISH     3u      /* no packet at all after the CONNECT_IND           */

/* Target selection: address type values */
#define BLE_TARGET_PUBLIC      0u
#define BLE_TARGET_RANDOM      1u
#define BLE_TARGET_ANY         2u      /* match the address regardless of its type        */

/* Where and when to listen for the next connection event. */
struct ble_rx_plan {
	uint8_t channel;               /* data channel index 0..36                        */
	uint16_t counter;              /* connection event counter of this event          */
	uint32_t rx_on_us;             /* switch the receiver on (ramp-up not included in the window) */
	uint32_t rx_off_us;            /* stop listening if no access address arrived     */
	uint8_t flags;                 /* BLE_PLAN_*                                      */
};

/* Result of ble_follow_on_data_packet(). */
struct ble_pkt_result {
	uint8_t flags;                 /* BLE_PKT_*                                       */
	uint32_t rx_off_us;            /* with BLE_PKT_CONTINUE: stop listening at this time */
};

/* Snapshot of the connection parameters for status reports. */
struct ble_conn_info {
	uint32_t access_address;
	uint32_t crc_init;
	uint16_t interval;             /* 1.25 ms units                                   */
	uint16_t latency;
	uint16_t timeout;              /* 10 ms units                                     */
	uint8_t chmap[BLE_CHMAP_LEN];
	uint8_t hop;
	uint8_t csa;                   /* 1 or 2: channel selection algorithm             */
	uint8_t sca;                   /* master sleep clock accuracy index               */
	uint8_t reason;                /* BLE_LOST_* (for "connection lost")              */
	uint16_t counter;              /* event counter at the time of the snapshot       */
};

/* All state of the follow logic. Treat as opaque outside ble_follow.c. */
struct ble_follow {
	/* --- configuration (ble_follow_configure) --- */
	bool has_target;               /* a device is selected                            */
	uint8_t target[6];             /* its address, on-air order (LSB first)           */
	uint8_t target_type;           /* BLE_TARGET_*                                    */
	bool follow_conn;              /* follow its connections                          */
	bool follow_rsp;               /* forward scan requests / responses               */

	/* --- scanning --- */
	bool adv_chsel;                /* ChSel bit of the last advertising PDU of the target */

	/* --- connection --- */
	bool connected;
	uint8_t lost_reason;
	uint32_t access_address;
	uint32_t crc_init;
	bool csa2;                     /* channel selection algorithm #2 in use           */
	uint16_t channel_id;           /* algorithm #2 channel identifier                 */
	uint8_t hop;
	uint8_t last_unmapped;         /* algorithm #1 state                              */
	uint8_t chmap[BLE_CHMAP_LEN];
	uint8_t sca;
	uint16_t interval;             /* 1.25 ms units                                   */
	uint16_t latency;
	uint16_t timeout;              /* 10 ms units                                     */
	uint32_t interval_us;
	bool encrypted;                /* LL_START_ENC_REQ seen: control PDUs unreadable  */
	bool terminated;               /* LL_TERMINATE_IND seen                           */

	bool upd_pending;              /* connection update waiting for its instant       */
	struct ble_conn_update upd;
	bool map_pending;              /* channel map update waiting for its instant      */
	struct ble_chmap_update map;

	/* --- event schedule --- */
	uint16_t next_counter;         /* counter of the next event to plan               */
	uint16_t counter;              /* counter of the event being received             */
	uint32_t ref_us;               /* earliest expected start of event ref_counter    */
	uint16_t ref_counter;
	uint32_t win_us;               /* length of the uncertainty window after ref_us   */
	uint32_t sync_us;              /* last time the clock was synchronised to the master */
	uint32_t last_valid_us;        /* last packet with valid CRC (supervision)        */
	uint32_t establish_limit_us;   /* give-up time before the first packet            */
	bool anchored;                 /* at least one packet was received                */

	/* --- current event --- */
	uint8_t pkt_index;             /* packets seen in this event (even = master)      */
	bool md_master;                /* More Data in the last master packet             */
	bool md_slave;                 /* More Data in the last slave packet              */
	uint32_t prev_end_us;          /* end of the previous packet                      */
};

/* Reset everything; follow mode off, connection following and responses on. */
void ble_follow_init(struct ble_follow *f);

/*
 * Select the device to follow (address in on-air order, type BLE_TARGET_*) or
 * switch following off (target == NULL). Drops a running connection.
 */
void ble_follow_set_target(struct ble_follow *f, const uint8_t target[6], uint8_t type);

/* Enable / disable following connections and scan request / response forwarding. */
void ble_follow_set_options(struct ble_follow *f, bool follow_conn, bool follow_rsp);

/*
 * Judge a received advertising channel packet. `pdu` = header + payload (no
 * access address, no CRC). Returns BLE_FOLLOW_* flags. With no target every
 * packet is forwarded. With a target only packets of that device are, and a
 * CONNECT_IND with valid CRC sets up the connection (BLE_FOLLOW_CONNECT);
 * start_us is the start of that packet.
 */
uint8_t ble_follow_on_adv(struct ble_follow *f, const uint8_t *pdu, size_t pdu_len,
			  bool crc_ok, uint32_t start_us);

/*
 * Plan the next connection event: applies updates whose instant is reached,
 * selects the channel and computes the listening window. Returns false if the
 * connection is over (f->lost_reason tells why).
 */
bool ble_follow_next_event(struct ble_follow *f, struct ble_rx_plan *plan);

/*
 * Digest a data channel packet received in the current event. `pdu` = header
 * + payload, `start_us` = start of the packet (preamble). Fills `res`.
 */
void ble_follow_on_data_packet(struct ble_follow *f, const uint8_t *pdu, size_t pdu_len,
			       bool crc_ok, uint32_t start_us, struct ble_pkt_result *res);

/* Fill `info` with the current connection parameters. */
void ble_follow_info(const struct ble_follow *f, struct ble_conn_info *info);

/* End time of a packet on the LE 1M PHY: preamble + AA + header + payload + CRC. */
uint32_t ble_pkt_end_us(uint32_t start_us, uint8_t payload_len);

#endif /* BLE_FOLLOW_H_ */
