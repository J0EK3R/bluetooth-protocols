/*
 * Buffered text output to the host, see out.h.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <string.h>

#include <zephyr/drivers/uart.h>
#include <zephyr/sys/ring_buffer.h>

#include "out.h"

/* Ring buffer size: room for ~14 maximum size BLE report lines. */
#define TX_RING_SIZE 8192u

RING_BUF_DECLARE(tx_ring, TX_RING_SIZE);

static const struct device *uart;   /* CDC ACM device */
static bool enabled;                /* host has the port open */
static uint32_t drops;              /* dropped lines since the last out_take_drops() */

void out_init(const struct device *cdc)
{
	uart = cdc;
}

void out_enable(bool enable)
{
	enabled = enable;
	ring_buf_reset(&tx_ring);       /* never replay old data to a new host */
}

bool out_reserve(size_t n)
{
	return enabled && ring_buf_space_get(&tx_ring) >= n;
}

void out_note_drop(void)
{
	drops++;
}

uint32_t out_take_drops(void)
{
	uint32_t d = drops;

	drops = 0;
	return d;
}

void out_str(const char *s)
{
	if (!enabled) {
		return;
	}
	/* Partial writes are possible when the ring is nearly full: count them. */
	size_t len = strlen(s);

	if (ring_buf_put(&tx_ring, (const uint8_t *)s, (uint32_t)len) < len) {
		drops++;
	}
}

void out_u32(uint32_t v)
{
	char buf[11];
	int i = (int)sizeof(buf) - 1;

	buf[i] = '\0';
	do {
		buf[--i] = (char)('0' + (v % 10u));
		v /= 10u;
	} while (v != 0u && i > 0);
	out_str(&buf[i]);
}

void out_i32(int32_t v)
{
	if (v < 0) {
		out_str("-");
		out_u32((uint32_t)(-v));
	} else {
		out_u32((uint32_t)v);
	}
}

void out_hex(const uint8_t *data, size_t len)
{
	static const char digits[] = "0123456789ABCDEF";
	char chunk[64];                 /* converted in pieces to save ring calls */
	size_t n = 0;

	for (size_t i = 0; i < len; i++) {
		chunk[n++] = digits[data[i] >> 4];
		chunk[n++] = digits[data[i] & 0x0Fu];
		if (n + 2u > sizeof(chunk) || i + 1u == len) {
			chunk[n] = '\0';
			out_str(chunk);
			n = 0;
		}
	}
}

void out_flush(void)
{
	uint8_t *data;
	uint32_t n;
	int written;

	if (!enabled || uart == NULL) {
		return;
	}
	/* Claim the oldest contiguous block and give it to the USB stack. */
	n = ring_buf_get_claim(&tx_ring, &data, TX_RING_SIZE);
	if (n == 0u) {
		return;
	}
	written = uart_fifo_fill(uart, data, (int)n);
	/* uart_fifo_fill() returns how many bytes it accepted (0 if USB is busy) */
	ring_buf_get_finish(&tx_ring, written > 0 ? (uint32_t)written : 0u);
}
