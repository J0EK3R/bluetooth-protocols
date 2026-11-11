/*
 * XN297L sniffer firmware for the nRF52840 MDK USB Dongle.
 *
 * The dongle enumerates as a USB CDC ACM device (virtual COM port).
 * Communication is line based ASCII, terminated by '\n' ('\r' is ignored).
 *
 * Commands (host -> dongle)
 * -------------------------
 *   help                 list commands
 *   info                 print the current configuration
 *   sync <hex>           sync word, 3..5 bytes, on-air order, MSB first
 *                        e.g. "sync 710F55" or "sync 2675882844"
 *   len <n>              number of bytes captured after the sync word (1..250)
 *   ch <c1,c2,...>       RF channel list, channel = MHz - 2400 (0..100)
 *   dwell <ms>           time per channel when hopping, 0 = stay on first
 *   rate <r>             nrf1m (default) | ble1m | nrf2m
 *   start                start receiving
 *   stop                 stop receiving
 *
 * Responses (dongle -> host)
 * --------------------------
 *   OK                   command accepted
 *   E <text>             error
 *   I <key>=<value> ...  information
 *   P <t_us> <ch> <rssi> <hex>
 *                        received packet: device time in microseconds,
 *                        RF channel, RSSI in dBm, sync word + captured bytes
 *                        as hex (on-air order, MSB first)
 *
 * Data is only sent while the host has the port open (DTR asserted).
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/usb/usb_device.h>

#include "radio.h"

#define FW_VERSION "1.0.0"

/* ------------------------------------------------------------------------ */
/* Devices                                                                   */
/* ------------------------------------------------------------------------ */

/* CDC ACM UART defined in boards/nrf52840_mdk_usb_dongle.overlay */
static const struct device *const cdc_dev = DEVICE_DT_GET(DT_NODELABEL(cdc_acm_uart0));

/* RGB LED of the dongle (active low, handled by the GPIO flags) */
static const struct gpio_dt_spec led_red   = GPIO_DT_SPEC_GET(DT_NODELABEL(led0_red), gpios);
static const struct gpio_dt_spec led_green = GPIO_DT_SPEC_GET(DT_NODELABEL(led0_green), gpios);
static const struct gpio_dt_spec led_blue  = GPIO_DT_SPEC_GET(DT_NODELABEL(led0_blue), gpios);

/* ------------------------------------------------------------------------ */
/* State                                                                     */
/* ------------------------------------------------------------------------ */

/*
 * Default configuration: promiscuous XN297L mode.
 *   sync = XN297L preamble 71 0F 55
 *   len  = 5 address + 32 payload + 2 CRC = 39 bytes
 *   channels 2402, 2426, 2480 MHz (the BLE advertising frequencies)
 */
static struct radio_config cfg = {
	.sync = { 0x71, 0x0F, 0x55 },
	.sync_len = 3,
	.capture_len = 39,
	.channels = { 2, 26, 80 },
	.channel_count = 3,
	.dwell_ms = 300,
	.rate = RADIO_RATE_NRF_1M,
};

static bool running;            /* receiver active                      */
static bool host_connected;     /* DTR asserted by the host             */
static int64_t green_off_ms;    /* time to switch the packet LED off    */

/* Command line buffer */
static char line[128];
static size_t line_len;

/* ------------------------------------------------------------------------ */
/* Output helpers (no printf: keeps the image small and the output exact)    */
/* ------------------------------------------------------------------------ */

/* Send a string to the host (dropped if no host has the port open). */
static void out_str(const char *s)
{
	if (!host_connected) {
		return;
	}
	while (*s != '\0') {
		uart_poll_out(cdc_dev, (unsigned char)*s++);
	}
}

/* Send an unsigned decimal number. */
static void out_u32(uint32_t v)
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

/* Send a signed decimal number. */
static void out_i32(int32_t v)
{
	if (v < 0) {
		out_str("-");
		out_u32((uint32_t)(-v));
	} else {
		out_u32((uint32_t)v);
	}
}

/* Send bytes as upper case hex without separators. */
static void out_hex(const uint8_t *data, size_t len)
{
	static const char digits[] = "0123456789ABCDEF";
	char pair[3] = { 0, 0, 0 };

	for (size_t i = 0; i < len; i++) {
		pair[0] = digits[data[i] >> 4];
		pair[1] = digits[data[i] & 0x0Fu];
		out_str(pair);
	}
}

/* ------------------------------------------------------------------------ */
/* Parsing helpers                                                           */
/* ------------------------------------------------------------------------ */

/* Convert one hex digit, returns -1 on error. */
static int hex_digit(char c)
{
	if (c >= '0' && c <= '9') {
		return c - '0';
	}
	if (c >= 'a' && c <= 'f') {
		return c - 'a' + 10;
	}
	if (c >= 'A' && c <= 'F') {
		return c - 'A' + 10;
	}
	return -1;
}

/*
 * Parse a hex string ("710F55", spaces/colons allowed) into out[].
 * Returns the number of bytes or -1 on error.
 */
static int parse_hex(const char *s, uint8_t *out, size_t max)
{
	size_t n = 0;
	int hi = -1;

	for (; *s != '\0'; s++) {
		if (*s == ' ' || *s == ':' || *s == '-') {
			continue;
		}
		int d = hex_digit(*s);

		if (d < 0) {
			return -1;
		}
		if (hi < 0) {
			hi = d;
		} else {
			if (n >= max) {
				return -1;
			}
			out[n++] = (uint8_t)(hi << 4 | d);
			hi = -1;
		}
	}
	return (hi < 0) ? (int)n : -1;   /* odd number of digits = error */
}

/* Parse an unsigned decimal number, advancing *s. Returns false on error. */
static bool parse_uint(const char **s, uint32_t *value)
{
	uint32_t v = 0;
	const char *p = *s;

	if (*p < '0' || *p > '9') {
		return false;
	}
	while (*p >= '0' && *p <= '9') {
		v = v * 10u + (uint32_t)(*p - '0');
		if (v > 100000u) {
			return false;
		}
		p++;
	}
	*s = p;
	*value = v;
	return true;
}

/* ------------------------------------------------------------------------ */
/* Commands                                                                  */
/* ------------------------------------------------------------------------ */

static const char *rate_name(enum radio_rate r)
{
	switch (r) {
	case RADIO_RATE_NRF_2M:
		return "nrf2m";
	case RADIO_RATE_BLE_1M:
		return "ble1m";
	default:
		return "nrf1m";
	}
}

/* Print the configuration as one "I" line. */
static void print_info(void)
{
	out_str("I version=" FW_VERSION " sync=");
	out_hex(cfg.sync, cfg.sync_len);
	out_str(" len=");
	out_u32(cfg.capture_len);
	out_str(" ch=");
	for (uint8_t i = 0; i < cfg.channel_count; i++) {
		if (i != 0u) {
			out_str(",");
		}
		out_u32(cfg.channels[i]);
	}
	out_str(" dwell=");
	out_u32(cfg.dwell_ms);
	out_str(" rate=");
	out_str(rate_name(cfg.rate));
	out_str(running ? " state=running\n" : " state=stopped\n");
}

/* Update the status LEDs: blue = running, red = stopped. */
static void update_state_leds(void)
{
	gpio_pin_set_dt(&led_blue, running ? 1 : 0);
	gpio_pin_set_dt(&led_red, running ? 0 : 1);
}

/* Restart the receiver with the new configuration if it is running. */
static void apply_config(void)
{
	if (running) {
		radio_start(&cfg);
	}
}

/* Execute one command line. */
static void handle_command(char *cmd)
{
	/* Split "keyword argument" */
	char *arg = strchr(cmd, ' ');

	if (arg != NULL) {
		*arg++ = '\0';
		while (*arg == ' ') {
			arg++;
		}
	} else {
		arg = cmd + strlen(cmd);   /* empty argument */
	}

	if (cmd[0] == '\0') {
		return;                    /* empty line: ignore silently */
	}

	if (strcmp(cmd, "help") == 0) {
		out_str("I commands: help info start stop sync <hex> len <n> "
			"ch <c1,c2,..> dwell <ms> rate <nrf1m|ble1m|nrf2m>\n");
		out_str("OK\n");

	} else if (strcmp(cmd, "info") == 0) {
		print_info();
		out_str("OK\n");

	} else if (strcmp(cmd, "start") == 0) {
		running = true;
		radio_start(&cfg);
		update_state_leds();
		out_str("OK\n");

	} else if (strcmp(cmd, "stop") == 0) {
		running = false;
		radio_stop();
		update_state_leds();
		out_str("OK\n");

	} else if (strcmp(cmd, "sync") == 0) {
		uint8_t tmp[RADIO_SYNC_MAX];
		int n = parse_hex(arg, tmp, sizeof(tmp));

		if (n < (int)RADIO_SYNC_MIN || n > (int)RADIO_SYNC_MAX) {
			out_str("E sync must be 3..5 hex bytes\n");
			return;
		}
		memcpy(cfg.sync, tmp, (size_t)n);
		cfg.sync_len = (uint8_t)n;
		apply_config();
		out_str("OK\n");

	} else if (strcmp(cmd, "len") == 0) {
		const char *p = arg;
		uint32_t v;

		if (!parse_uint(&p, &v) || v < 1u || v > RADIO_LEN_MAX) {
			out_str("E len must be 1..250\n");
			return;
		}
		cfg.capture_len = (uint8_t)v;
		apply_config();
		out_str("OK\n");

	} else if (strcmp(cmd, "ch") == 0) {
		struct radio_config tmp = cfg;
		const char *p = arg;
		uint32_t v;

		tmp.channel_count = 0;
		while (*p != '\0') {
			if (!parse_uint(&p, &v) || v > 100u ||
			    tmp.channel_count >= RADIO_CHANNELS_MAX) {
				out_str("E ch must be a list of 1..16 channels 0..100\n");
				return;
			}
			tmp.channels[tmp.channel_count++] = (uint8_t)v;
			while (*p == ',' || *p == ' ') {
				p++;
			}
		}
		if (tmp.channel_count == 0u) {
			out_str("E ch needs at least one channel\n");
			return;
		}
		cfg = tmp;
		apply_config();
		out_str("OK\n");

	} else if (strcmp(cmd, "dwell") == 0) {
		const char *p = arg;
		uint32_t v;

		if (!parse_uint(&p, &v) || v > 60000u) {
			out_str("E dwell must be 0..60000 ms\n");
			return;
		}
		cfg.dwell_ms = (uint16_t)v;
		apply_config();
		out_str("OK\n");

	} else if (strcmp(cmd, "rate") == 0) {
		if (strcmp(arg, "nrf1m") == 0) {
			cfg.rate = RADIO_RATE_NRF_1M;
		} else if (strcmp(arg, "ble1m") == 0) {
			cfg.rate = RADIO_RATE_BLE_1M;
		} else if (strcmp(arg, "nrf2m") == 0) {
			cfg.rate = RADIO_RATE_NRF_2M;
		} else {
			out_str("E rate must be nrf1m, ble1m or nrf2m\n");
			return;
		}
		apply_config();
		out_str("OK\n");

	} else {
		out_str("E unknown command (try 'help')\n");
	}
}

/* Read all pending characters from the host and execute complete lines. */
static void poll_input(void)
{
	unsigned char c;

	while (uart_poll_in(cdc_dev, &c) == 0) {
		if (c == '\r') {
			continue;
		}
		if (c == '\n') {
			line[line_len] = '\0';
			handle_command(line);
			line_len = 0;
			continue;
		}
		if (line_len < sizeof(line) - 1u) {
			/* store lower case so commands are case-insensitive */
			line[line_len++] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : (char)c;
		}
	}
}

/* Track the DTR line: the host opened or closed the port. */
static void poll_dtr(void)
{
	uint32_t dtr = 0;

	if (uart_line_ctrl_get(cdc_dev, UART_LINE_CTRL_DTR, &dtr) != 0) {
		return;
	}

	if (dtr != 0u && !host_connected) {
		host_connected = true;
		line_len = 0;
		out_str("I XN297L sniffer ready\n");
		print_info();
	} else if (dtr == 0u && host_connected) {
		host_connected = false;
	}
}

/* Send one packet report line. */
static void report_packet(const struct radio_packet *pkt)
{
	out_str("P ");
	out_u32(pkt->timestamp_us);
	out_str(" ");
	out_u32(pkt->channel);
	out_str(" ");
	out_i32(pkt->rssi_dbm);
	out_str(" ");
	out_hex(cfg.sync, cfg.sync_len);   /* sync word first ...           */
	out_hex(pkt->data, pkt->len);      /* ... then the captured bytes   */
	out_str("\n");
}

/* ------------------------------------------------------------------------ */
/* Main                                                                      */
/* ------------------------------------------------------------------------ */

int main(void)
{
	static struct radio_packet pkt;   /* static: keep it off the stack */
	int64_t last_dtr_check = 0;

	/* LEDs */
	gpio_pin_configure_dt(&led_red, GPIO_OUTPUT_INACTIVE);
	gpio_pin_configure_dt(&led_green, GPIO_OUTPUT_INACTIVE);
	gpio_pin_configure_dt(&led_blue, GPIO_OUTPUT_INACTIVE);
	update_state_leds();

	/* The RADIO needs the HF crystal */
	if (radio_hfclk_start() != 0) {
		/* Without HFXO the RADIO cannot work: blink red forever */
		for (;;) {
			gpio_pin_toggle_dt(&led_red);
			k_msleep(200);
		}
	}

	/* USB CDC ACM */
	if (!device_is_ready(cdc_dev) || usb_enable(NULL) != 0) {
		for (;;) {
			gpio_pin_toggle_dt(&led_red);
			k_msleep(1000);
		}
	}

	for (;;) {
		/* Commands from the host */
		poll_input();

		/* Port opened/closed? (checked every 50 ms) */
		if (k_uptime_get() - last_dtr_check >= 50) {
			last_dtr_check = k_uptime_get();
			poll_dtr();
		}

		/* Received packets (drain everything that is available) */
		while (radio_poll(&pkt)) {
			report_packet(&pkt);
			gpio_pin_set_dt(&led_green, 1);
			green_off_ms = k_uptime_get() + 20;
		}

		/* Packet LED: short green flash */
		if (green_off_ms != 0 && k_uptime_get() >= green_off_ms) {
			gpio_pin_set_dt(&led_green, 0);
			green_off_ms = 0;
		}

		/*
		 * Give the USB stack time to run. While receiving, poll the
		 * RADIO roughly every 60 us (a 40 byte packet takes ~350 us
		 * at 1 Mbps); while stopped, a slower loop is fine.
		 */
		if (running) {
			k_usleep(50);
		} else {
			k_msleep(5);
		}
	}

	return 0;
}
