/*
 * Bluetooth LE receiver on the nRF52840 RADIO (milestone M1: advertising scan).
 *
 * How it works
 * ------------
 * The RADIO is configured like a BLE controller would do it:
 *   - MODE = Ble_1Mbit, access address 0x8E89BED6 (advertising),
 *   - packet layout S0 (1 byte header 0) + LENGTH (1 byte) + payload,
 *   - hardware whitening (initial value = channel index) and CRC-24
 *     (polynomial 0x00065B, init 0x555555, access address excluded).
 * Reception is a loop driven by the RADIO interrupt:
 *
 *   RXEN -> (ramp-up) -> READY -> START (short) -> packet ... END
 *        -> DISABLED (short) -> interrupt: store packet, pick channel, RXEN
 *
 * A TIMER (1 MHz, 32 bit) provides the time base. The moment the access
 * address was matched is captured by a PPI channel without CPU involvement;
 * the start of the packet (preamble) is that time minus 40 us.
 *
 * Channel hopping: a TIMER compare interrupt asks for a hop every dwell
 * time. If the RADIO is idle it is disabled, if it is receiving a packet the
 * hop is done right after that packet. Hence a hop never destroys a packet.
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
 * is not compensated (to be calibrated against a reference sniffer).
 */
#define T_PACKET_START_1M_US 40u

#define RING_SLOTS           16u           /* packets queued for the main loop    */
#define PPI_CH_ADDRESS       19            /* PPI channel: ADDRESS -> TIMER capture */
#define TIMER_CC_NOW         0             /* CC[0]: "read the clock" capture     */
#define TIMER_CC_HOP         1             /* CC[1]: channel hop compare          */
#define TIMER_CC_ADDRESS     2             /* CC[2]: filled by PPI at ADDRESS     */

/* ------------------------------------------------------------------------ */
/* State                                                                     */
/* ------------------------------------------------------------------------ */

static struct ble_config cfg;                 /* active configuration             */
static struct ble_packet ring[RING_SLOTS];    /* packet queue (DMA target = ring[head]) */
static volatile uint8_t ring_head;            /* next slot the RADIO writes (ISR) */
static volatile uint8_t ring_tail;            /* next slot the main loop reads    */
static volatile uint32_t drop_count;          /* packets lost on overflow         */
static volatile bool hop_due;                 /* a channel hop is requested       */
static uint8_t channel_pos;                   /* index into cfg.channels[]        */
static bool irq_connected;                    /* IRQ_CONNECT done (only once)     */

/* ------------------------------------------------------------------------ */
/* Helpers                                                                   */
/* ------------------------------------------------------------------------ */

/*
 * RADIO FREQUENCY register value (MHz - 2400) of an advertising channel index:
 * 37 -> 2402 MHz, 38 -> 2426 MHz, 39 -> 2480 MHz (Core Spec Vol 6 Part B 1.4.1).
 */
static uint8_t adv_frequency(uint8_t channel)
{
	switch (channel) {
	case 37:
		return 2;
	case 38:
		return 26;
	default:
		return 80;
	}
}

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

/* Tune to the current scan channel and start the receiver (RADIO must be disabled). */
static void arm_rx(void)
{
	uint8_t channel = cfg.channels[channel_pos];

	NRF_RADIO->FREQUENCY = adv_frequency(channel);
	NRF_RADIO->DATAWHITEIV = channel;          /* whitening LFSR starts from the channel index */
	NRF_RADIO->PACKETPTR = (uint32_t)ring[ring_head].raw;

	NRF_RADIO->EVENTS_READY = 0;
	NRF_RADIO->EVENTS_ADDRESS = 0;
	NRF_RADIO->EVENTS_END = 0;
	NRF_RADIO->EVENTS_DISABLED = 0;
	NRF_RADIO->TASKS_RXEN = 1;
}

/* ------------------------------------------------------------------------ */
/* Interrupt handlers                                                        */
/* ------------------------------------------------------------------------ */

/*
 * A packet has been received completely (END happened and the RADIO is now
 * disabled): complete the metadata and publish the slot to the main loop.
 * Packets below the RSSI threshold are dropped here (the slot is reused).
 */
static void finish_packet(void)
{
	struct ble_packet *p = &ring[ring_head];
	int8_t rssi = (int8_t)(-(int)NRF_RADIO->RSSISAMPLE);
	uint32_t crc = NRF_RADIO->RXCRC;
	uint8_t next = (uint8_t)((ring_head + 1u) % RING_SLOTS);

	/* TODO(M2): apply the RSSI filter to advertising packets only; connection packets must never be filtered. */
	if (rssi < cfg.rssi_min) {
		return;                                /* advertising RSSI filter */
	}
	if (next == ring_tail) {
		drop_count++;                          /* queue full: reuse the slot, count the loss */
		return;
	}

	p->crc[0] = (uint8_t)(crc & 0xFFu);
	p->crc[1] = (uint8_t)((crc >> 8) & 0xFFu);
	p->crc[2] = (uint8_t)((crc >> 16) & 0xFFu);
	p->channel = cfg.channels[channel_pos];
	p->rssi = rssi;
	p->phy = BLE_PHY_1M;
	p->flags = (NRF_RADIO->CRCSTATUS == RADIO_CRCSTATUS_CRCSTATUS_CRCOk) ? BLE_FLAG_CRC_OK : 0u;
	p->evt = 0;
	p->t_us = NRF_TIMER3->CC[TIMER_CC_ADDRESS] - T_PACKET_START_1M_US;

	__DMB();                                   /* publish the data before the index */
	ring_head = next;
}

/*
 * RADIO interrupt: DISABLED event. Either a packet ended (END short) or a hop
 * disabled the idle receiver. Store the packet, hop if requested, re-arm.
 */
static void radio_isr(const void *arg)
{
	ARG_UNUSED(arg);

	if (NRF_RADIO->EVENTS_DISABLED == 0) {
		return;
	}
	NRF_RADIO->EVENTS_DISABLED = 0;

	if (NRF_RADIO->EVENTS_END != 0) {
		NRF_RADIO->EVENTS_END = 0;
		finish_packet();
	}
	if (hop_due) {
		hop_due = false;
		channel_pos = (uint8_t)((channel_pos + 1u) % cfg.channel_count);
	}
	arm_rx();
}

/*
 * TIMER compare interrupt: the dwell time on the channel is over. Request a
 * hop; interrupt an idle receiver, but never one that is inside a packet.
 */
static void timer_isr(const void *arg)
{
	ARG_UNUSED(arg);

	NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_HOP] = 0;
	NRF_TIMER3->CC[TIMER_CC_HOP] += (uint32_t)cfg.dwell_ms * 1000u;   /* next hop time */

	hop_due = true;
	if (NRF_RADIO->EVENTS_ADDRESS == 0) {
		/* no packet in progress: the DISABLED interrupt will do the hop */
		NRF_RADIO->TASKS_DISABLE = 1;
	}
	/* else: a packet is being received, its DISABLED interrupt hops afterwards */
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
	set_access_address(ADV_ACCESS_ADDRESS);

	/* CRC-24 over the PDU only (the access address is skipped) */
	NRF_RADIO->CRCCNF = (RADIO_CRCCNF_LEN_Three << RADIO_CRCCNF_LEN_Pos) |
			    (RADIO_CRCCNF_SKIPADDR_Skip << RADIO_CRCCNF_SKIPADDR_Pos);
	NRF_RADIO->CRCPOLY = CRC_POLY;
	NRF_RADIO->CRCINIT = ADV_CRC_INIT;

	/*
	 * READY -> START: start receiving after ramp-up
	 * ADDRESS -> RSSISTART: sample the RSSI while the packet is received
	 * END -> DISABLE: one packet per RXEN, the DISABLED interrupt re-arms
	 * DISABLED -> RSSISTOP: stop the RSSI measurement
	 */
	NRF_RADIO->SHORTS = RADIO_SHORTS_READY_START_Msk |
			    RADIO_SHORTS_ADDRESS_RSSISTART_Msk |
			    RADIO_SHORTS_END_DISABLE_Msk |
			    RADIO_SHORTS_DISABLED_RSSISTOP_Msk;

	/* Channel hopping timer (only with more than one channel and a dwell time) */
	if (cfg.channel_count > 1u && cfg.dwell_ms != 0u) {
		NRF_TIMER3->CC[TIMER_CC_HOP] = timer_now() + (uint32_t)cfg.dwell_ms * 1000u;
		NRF_TIMER3->EVENTS_COMPARE[TIMER_CC_HOP] = 0;
		NRF_TIMER3->INTENSET = TIMER_INTENSET_COMPARE1_Msk;
		NVIC_ClearPendingIRQ(TIMER3_IRQn);
		irq_enable(TIMER3_IRQn);
	}

	NRF_RADIO->INTENSET = RADIO_INTENSET_DISABLED_Msk;
	NVIC_ClearPendingIRQ(RADIO_IRQn);
	irq_enable(RADIO_IRQn);
	arm_rx();
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

	NRF_PPI->CHENCLR = 1u << PPI_CH_ADDRESS;
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
