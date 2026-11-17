/*
 * Buffered text output to the host (USB CDC ACM).
 *
 * All output goes into a ring buffer first and is drained by out_flush()
 * with uart_fifo_fill(). The producers (command replies, packet reports)
 * therefore never block on USB, which matters in BLE mode where several
 * hundred packets per second have to be reported. If the ring is full (host
 * too slow or not reading) data is dropped instead of stalling the receiver;
 * callers use out_reserve() to drop whole lines, never half lines.
 *
 * The text format is the same as with the former char-wise uart_poll_out()
 * output, so existing hosts are not affected.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef OUT_H_
#define OUT_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/device.h>

/* Select the CDC ACM UART used for output (call once at start-up). */
void out_init(const struct device *cdc);

/*
 * Enable or disable output. Output is only produced while a host has the
 * port open (DTR asserted). Disabling discards everything still queued so a
 * new host never sees stale lines.
 */
void out_enable(bool enable);

/* True while a host has the port open (output is accepted). */
bool out_is_enabled(void);

/* True if at least n bytes can be queued right now (and output is enabled). */
bool out_reserve(size_t n);

/* Queue helpers (text without printf: keeps the image small). */
void out_str(const char *s);
void out_u32(uint32_t v);
void out_i32(int32_t v);
void out_hex(const uint8_t *data, size_t len);   /* upper case, no separators */

/* Hand queued bytes to the USB stack. Call regularly from the main loop. */
void out_flush(void);

/* Number of lines/chunks that had to be dropped because the ring was full. */
uint32_t out_take_drops(void);

/* Count one dropped report (used by callers that checked out_reserve()). */
void out_note_drop(void);

#endif /* OUT_H_ */
