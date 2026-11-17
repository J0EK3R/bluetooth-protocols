/*
 * Host test driver for the pure C connection following code
 * (firmware/src/ble_csa.c, ble_pdu.c, ble_follow.c).
 *
 * Reads a script from stdin, one command per line, and prints one result line
 * per command. tests/test_ble_follow.py feeds the same script to this program
 * and to the Python model (tests/ble_follow_model.py) and compares the output
 * line by line; the format below is therefore a contract of both.
 *
 *   init                                   reset the follow state
 *   target <hex12>|off <type>              select device (address in on-air order)
 *   opts <follow_conn 0|1> <follow_rsp 0|1>
 *   adv <crc 0|1> <start_us> <pdu hex>     -> "adv <flags>"
 *   next                                   -> "plan ch=.. ctr=.. on=.. off=.. fl=.." | "lost <reason>"
 *   pkt <crc 0|1> <start_us> <pdu hex>     -> "pkt <flags> <rx_off_us>"
 *   info                                   -> "info aa=.. crc=.. int=.. lat=.. to=.. map=.. hop=.. csa=.. sca=.. ctr=.."
 *   csa1 <map hex10> <hop> <n>             -> "csa1 <channels>"
 *   csa2 <aa hex8> <map hex10> <first> <n> -> "csa2 <channels>"
 *   prn <chan_id hex> <counter>            -> "prn <value>"
 *   freq <channel>                         -> "freq <MHz-2400>"
 *
 * Build: cc -Wall -Wextra -Werror -I../../firmware/src follow_driver.c ../../firmware/src/ble_*.c
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ble_follow.h"

/* Decode a hex string into out[]; returns the number of bytes. */
static size_t from_hex(const char *s, uint8_t *out, size_t max)
{
	size_t n = 0;

	while (s[0] != '\0' && s[1] != '\0' && n < max) {
		char tmp[3] = { s[0], s[1], 0 };

		out[n++] = (uint8_t)strtoul(tmp, NULL, 16);
		s += 2;
	}
	return n;
}

/* Print a 5 byte channel map as 10 hex digits. */
static void print_map(const uint8_t *map)
{
	for (int i = 0; i < 5; i++) {
		printf("%02x", map[i]);
	}
}

int main(void)
{
	static struct ble_follow f;
	char line[1024];

	ble_follow_init(&f);
	while (fgets(line, sizeof(line), stdin) != NULL) {
		char cmd[16] = "";
		char a[600] = "";
		char b[600] = "";
		char c[600] = "";
		char d[600] = "";
		uint8_t pdu[300];

		line[strcspn(line, "\r\n")] = '\0';
		(void)sscanf(line, "%15s %599s %599s %599s %599s", cmd, a, b, c, d);

		if (strcmp(cmd, "init") == 0) {
			ble_follow_init(&f);
		} else if (strcmp(cmd, "target") == 0) {
			uint8_t addr[6];

			if (strcmp(a, "off") == 0) {
				ble_follow_set_target(&f, NULL, 0);
			} else {
				from_hex(a, addr, 6);
				ble_follow_set_target(&f, addr, (uint8_t)atoi(b));
			}
		} else if (strcmp(cmd, "opts") == 0) {
			ble_follow_set_options(&f, atoi(a) != 0, atoi(b) != 0);
		} else if (strcmp(cmd, "adv") == 0) {
			size_t n = from_hex(c, pdu, sizeof(pdu));
			uint8_t flags = ble_follow_on_adv(&f, pdu, n, atoi(a) != 0,
							  (uint32_t)strtoul(b, NULL, 10));

			printf("adv %u\n", flags);
		} else if (strcmp(cmd, "next") == 0) {
			struct ble_rx_plan plan;

			if (ble_follow_next_event(&f, &plan)) {
				printf("plan ch=%u ctr=%u on=%" PRIu32 " off=%" PRIu32 " fl=%u\n",
				       plan.channel, plan.counter, plan.rx_on_us, plan.rx_off_us,
				       plan.flags);
			} else {
				printf("lost %u\n", f.lost_reason);
			}
		} else if (strcmp(cmd, "pkt") == 0) {
			struct ble_pkt_result res;
			size_t n = from_hex(c, pdu, sizeof(pdu));

			ble_follow_on_data_packet(&f, pdu, n, atoi(a) != 0,
						  (uint32_t)strtoul(b, NULL, 10), &res);
			printf("pkt %u %" PRIu32 "\n", res.flags, res.rx_off_us);
		} else if (strcmp(cmd, "info") == 0) {
			struct ble_conn_info info;

			ble_follow_info(&f, &info);
			printf("info aa=%08" PRIx32 " crc=%06" PRIx32 " int=%u lat=%u to=%u map=",
			       info.access_address, info.crc_init, info.interval, info.latency,
			       info.timeout);
			print_map(info.chmap);
			printf(" hop=%u csa=%u sca=%u ctr=%u\n", info.hop, info.csa, info.sca,
			       info.counter);
		} else if (strcmp(cmd, "csa1") == 0) {
			uint8_t map[5];
			uint8_t last = 0;
			int count = atoi(c);

			from_hex(a, map, 5);
			printf("csa1");
			for (int i = 0; i < count; i++) {
				printf(" %u", ble_csa1_next(&last, (uint8_t)atoi(b), map));
			}
			printf("\n");
		} else if (strcmp(cmd, "csa2") == 0) {
			uint8_t map[5];
			uint32_t aa = (uint32_t)strtoul(a, NULL, 16);
			uint16_t first = (uint16_t)atoi(c);
			int count = atoi(d);

			from_hex(b, map, 5);
			printf("csa2");
			for (int i = 0; i < count; i++) {
				printf(" %u", ble_csa2_channel(ble_csa2_channel_id(aa),
							       (uint16_t)(first + i), map));
			}
			printf("\n");
		} else if (strcmp(cmd, "prn") == 0) {
			printf("prn %u\n", ble_csa2_prn_e((uint16_t)strtoul(a, NULL, 16),
							(uint16_t)atoi(b)));
		} else if (strcmp(cmd, "freq") == 0) {
			printf("freq %u\n", ble_channel_frequency((uint8_t)atoi(a)));
		}
	}
	return 0;
}
