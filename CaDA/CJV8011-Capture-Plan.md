# CaDA CJV8011 / CJV1010 – Capture plan for the 2.4 GHz radio link

> Purpose: step-by-step measurement guide for the radio link between the [CJV8011](CJV8011.md) handset and the [CJV1010](CJV1010.md) receiver, mainly with the nRF52840 MDK USB dongle ([XN297L sniffer](../Tools/xn297l-sniffer/README.md) in raw mode, [nRF Sniffer for Bluetooth LE](../Tools/nrf-sniffer-ble/README.md)); SDR and logic analyzer as fallbacks.
> Status: **stopped on 2026-11-15** (telegram decoded; assessment and open points in [CJV8011.md §3](CJV8011.md#3-control-by-smartphone-or-an-own-transmitter-assessment)) – session 0: R0.3, R0.4 done (no XN297L frames, C2 answered); R0.1, R0.2 (BLE) deferred. Session 1: R1.0 … R1.6 done – **handset found** on 2446 / 2466 MHz, 1 Mbps, repeating 32-byte block after an `AA` preamble (section 6.1); Session 2: R2.1 … R2.4 done – frame structure decoded: constant 512-bit header, then 64-bit codeword symbols (DSSS-like), operating channels 2406 / 2427 / 2446 / 2462 MHz, control state in symbol positions 14 … 17 (section 7.1); R2.5 … R2.7 done – complete frame (header + 30 symbols, 2440 chips), hopping order 2406 → 2427 → 2446 → 2462 MHz, cycle 33.6 ms (section 7.3); Session 4: R4.1 … R4.3 done – **telegram decoded**: 64-chip symbol = 4 bits, control state = two 4-bit direction masks (section 9.1). Session 3: R3.1, R3.2 done – handset ID in positions 8 … 13 (H1 `33A400`, H2 `572444`), automatic pairing after power-on via link frames, link ID `255111` from the receiver (section 8.1); R3.3a, R3.6 … R3.10 done – H2 gets the same link value `255111`, no explicit pairing needed, no receiver beacon; the supposed second codeword set was a 2-bit capture offset (section 8.5); unidentified weak frames after receiver power-on, next: R3.11 … R3.13. Results go to [CJV8011.md §2](CJV8011.md#2-radio-protocol).
> Last updated: 2026-11-14 (raw mode of the console tool instead of the separate `raw.py` script)

## Contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [What is different from the SCM8 / MK4.0 handsets](#2-what-is-different-from-the-scm8--mk40-handsets)
3. [Equipment and preparation](#3-equipment-and-preparation)
4. [Session order](#4-session-order)
5. [Session 0 – Quick exclusions (BLE, XN297L)](#5-session-0--quick-exclusions-ble-xn297l)
6. [Session 1 – Find the transmitter (preamble sniffing)](#6-session-1--find-the-transmitter-preamble-sniffing)
7. [Session 2 – Lock onto the sync word, frame structure](#7-session-2--lock-onto-the-sync-word-frame-structure)
8. [Session 3 – Pairing mode](#8-session-3--pairing-mode)
9. [Session 4 – Telegram mapping](#9-session-4--telegram-mapping)
10. [Session 5 (fallback) – SDR](#10-session-5-fallback--sdr)
11. [Session 6 (optional) – Logic analyzer on the CJV1010 board](#11-session-6-optional--logic-analyzer-on-the-cjv1010-board)
12. [Recording the results](#12-recording-the-results)
13. [Open questions](#13-open-questions)

---

## 1. Purpose and scope

Known so far (product page, photos, own observations – see [CJV8011](CJV8011.md) and [CJV1010](CJV1010.md)):
4 channels (1 red, 2 blue, 3 black, 4 yellow), three states each (neutral / plus / minus), one
direction-reversal switch per channel, a pairing mode, **12 MHz** crystals in handset and receiver,
unmarked SOP-16 ICs (RF), boards from the same maker (`SY-JV…`, `DE LI`). Nothing is known about
the radio layer.

| # | Question | Status |
|---|---|---|
| C1 | Is the handset a BLE device? | open (session 0, expected: no) |
| C2 | Is it an XN297L-compatible frame (preamble `71 0F 55`) like Mould King / JIESTAR? | **answered: no** – no frame with valid CRC in R0.3 (handset only) and R0.4 (handset + receiver), promiscuous mode, all channels, `nrf1m` (2026-11-14) |
| C3 | Frequency / frequencies, data rate, modulation | **answered:** 1 Mbps (chip rate) GFSK; bind: **2446 and 2466 MHz**; operation: **2406, 2427, 2446, 2462 MHz** (R1.1 … R2.4) |
| C4 | Preamble, sync word (length, value), frame structure: length field, payload length, trailer, CRC, bit order | **mostly:** preamble `AA …`, 512-bit header, `1101`, **30 symbols** of 64-bit codewords from a small codebook, `1001` (sections 7.1, 7.3); meaning of the symbols and the check open |
| C5 | Pairing: how is the pairing mode entered, is there a bind channel / bind address, does the handset have a fixed ID, is the receiver bound to one handset afterwards? | **partly:** handset ID fixed in positions 8 … 13 (H1 `33A400`, H2 `572444`); bind channels 2466 MHz + one handset-specific channel (H1 2446, H2 2443 MHz); after power-on bind → link (≈ 0.3 s) → operation automatically, link ID `255111` in positions 2 … 7 (R3.1, R3.2); explicit pairing and binding to one handset open (R3.3a) |
| C6 | Telegram layout: encoding of the 4 channels × 3 states, effect of the direction switches (handset-side or flag in the telegram) | **answered:** two 4-bit masks (A in position 14, B in 15; red 1, blue 2, black 4, yellow 8), check symbols 15 − A / 15 − B; reversal switches act in the handset (bit moves to the other mask) (R4.1 … R4.3) |
| C7 | Frequency hopping (channels, order, period) | **answered:** bind 2446 / 2466 MHz, a frame every 29.6 ms per channel; operation **2406 → 2427 → 2446 → 2462 MHz**, frames 7.2 ms apart, 12.2 ms pause, cycle 33.6 ms (R2.7) |
| C8 | Does the receiver transmit (acknowledge, telemetry)? | **open, very likely** – the handset leaves the bind mode only when a receiver is on (R3.2, R3.9); no beacon without a handset (R3.6); receiver frames not yet identified – candidates: weak frames of R3.7 (section 8.5, R3.11 … R3.13) |
| C9 | Chip family (LT8900 / LT8910 class or other)? | **hypothesis:** Cypress CYRF6936 / CYRF7936 class DSSS (64-chip codewords, 12 MHz crystal); LT8900 does not fit (section 7.1); confirm with session 6 |

Writing convention as in the [SCM8 capture plan](../JieStar/SCM8-Capture-Plan.md): only measured
values go into the result document, interpretations are marked as such.

---

## 2. What is different from the SCM8 / MK4.0 handsets

The SCM8 and MK4.0 handsets were found within minutes because they use the XN297L frame layer –
the sniffer simply waits for the known preamble `71 0F 55`. For the CaDA system that shortcut is
probably not available:

- **12 MHz crystal.** XN297L and nRF24L01 (and their clones) need 16 MHz. A 12 MHz reference is
  typical for the **LT8900 / LT8910** class (*interpretation*, not verified). Such chips send
  *preamble – sync word (16 … 64 bit, configurable) – trailer – payload (optional length byte) –
  CRC-16*, 1 Mbps GFSK (LT8910 also 250 / 125 / 62.5 kbps).
- **Unknown sync word.** The nRF52840 can only receive a packet when it knows 3 … 5 bytes of the
  sync word. Trick used here (well known from nRF24 promiscuous sniffing): use the **preamble**
  (`AA AA AA` or `55 55 55`, alternating bits) as the nRF sync word. Every GFSK transmitter at the
  right data rate whose preamble is long enough then triggers a capture, and the captured bytes
  start with the transmitter's real sync word.
- **Limits of this trick:** the nRF radio needs 8 bit preamble + 24 bit sync = 32 alternating bits.
  If the transmitter's preamble is shorter (LT8900: 1 … 8 bytes, configurable), captures may be
  rare or fail → try `AA AA AA` and `55 55 55` (bit phase), all three data rates, and fall back to
  the SDR (session 5). Data rates below 1 Mbps cannot be received by the nRF52840 at all.

The firmware already supports this: the serial command `sync <hex>` takes any 3 … 5 bytes and
captures up to 250 bytes MSB first, without whitening and without CRC check
([serial protocol](../Tools/xn297l-sniffer/README.md#24-serial-protocol)). The console tool /
Wireshark extcap `xn297l_sniffer.py` (1.1.0) exposes this as **raw mode** (`--mode raw --sync
<hex> --raw-length <n>`, [sync modes](../Tools/xn297l-sniffer/README.md#1-sync-modes)).

---

## 3. Equipment and preparation

| Item | Needed for |
|---|---|
| nRF52840 MDK USB dongle | sessions 0 … 4 |
| firmware **XN297L sniffer 1.1** ([Tools/xn297l-sniffer](../Tools/xn297l-sniffer/README.md)) | sessions 0 … 4 |
| firmware **nRF Sniffer for BLE** ([Tools/nrf-sniffer-ble](../Tools/nrf-sniffer-ble/README.md)) | session 0 (R0.1, R0.2) |
| CJV8011 handset **H1** (2 × AA, fresh), mark it; a 2nd handset **H2** if available | all sessions; H2 for R3.4 |
| CJV1010 receiver **E1** (charged); a 2nd receiver **E2** if available | sessions 2 … 4; E2 for R3.5 |
| motors or LEDs on all four ports (red, blue, black, yellow) | session 4 |
| PC with Python 3 + `pyserial`, `xn297l_sniffer.py` **1.1.0** or newer (raw mode) | all sessions |
| *optional:* SDR covering 2.4 GHz (HackRF One, ADALM-Pluto, …) + [Universal Radio Hacker](https://github.com/jopohl/urh) or inspectrum | session 5 |
| *optional:* logic analyzer (≥ 8 channels, ≥ 24 MS/s) + PulseView / sigrok, fine probes | session 6 |

Flashing: double-click the dongle button (LED green, UF2 drive appears), copy the `.uf2` of the
firmware the session needs.

**Console command** (run from the repository root, replace `<PORT>`, e.g. `COM5`; stop with
Ctrl+C):

```bash
RAW="python -u Tools/xn297l-sniffer/extcap/xn297l_sniffer.py --print --port <PORT> --mode raw"
# each run: $RAW <options> | tee R<run>.log
$RAW --sync AAAAAA --raw-length 64 --channels 0-83 --dwell 50 --rate nrf1m | tee R1.1.log
```

Output lines: `<device time> <frequency> <RSSI>  raw <sync word> | <captured bytes>`. In Wireshark
choose *Sync mode* = *Raw (any sync word)* and set *Sync word* and *Capture length*; the
captures are shown as protocol *RAW 2.4G*.

For every run note what you did and when (the log has device time only). Raw logs are **not**
committed; send them to me for the analysis.

Hints: dongle 0.5 … 1 m from the handset, then closer (10 … 20 cm) for weak signals; switch 2.4 GHz
Wi-Fi off for the session if possible (or at least keep it in the same state); keep each run below
70 minutes (device time wraps after 71.6 min).

---

## 4. Session order

| Session | Device state | Runs | Questions | Time | Status |
|---|---|---|---|---|---|
| 0 Exclusions | handset on, receiver off | R0.1 … R0.4 | C1, C2 | 15 min | **partly** – R0.3, R0.4 done (no XN297L); R0.1, R0.2 (BLE) deferred, only needed if session 1 finds nothing |
| 1 Find | handset on / off, receiver off and on | R1.0 … R1.8 | C3, C4, C7 | 45 min | **done** (R1.0 … R1.6) – transmitter found; R1.7, R1.8 replaced by R2.4 |
| 2 Lock on | handset + receiver | R2.1 … R2.7 | C4, C7, C8, C9 | 45 min | **done** – R2.1 … R2.7 |
| 3 Pairing | pairing sequences | R3.1 … R3.13 | C5, C8 | 30 min | **partly** – R3.1 … R3.10 done (R3.3 aborted, replaced by R3.3a); R3.11 … R3.13 open |
| 4 Mapping | paired, motors on all ports | R4.1 … R4.4 | C6 | 30 min | **done** – R4.1 … R4.3; R4.4 not needed (no intermediate values: each symbol is a mask) |
| 5 SDR | only if session 1 finds nothing | R5.1 … R5.3 | C3, C4 | 60 min | fallback |
| 6 Logic analyzer | receiver board open | R6.1, R6.2 | C3, C4, C9 | 60 min | optional |

Session 6 can be done instead of or in parallel to session 1: the register writes of the receiver
MCU to its RF chip give data rate, channel and sync word directly, without any radio search.

---

## 5. Session 0 – Quick exclusions (BLE, XN297L)

Cheap checks with the existing tools before the raw search.

| Run | Firmware | State | Settings | Duration |
|---|---|---|---|---|
| R0.1 | nRF Sniffer for BLE | everything off (reference) | Wireshark, all advertising devices | 30 s |
| R0.2 | nRF Sniffer for BLE | handset **on**, operate all controls | same; filter `btle.advertising_header && btle.rssi > -60` | 60 s |
| R0.3 | XN297L sniffer | handset on, receiver off | `xn297l_sniffer.py --print --show-bad --port <PORT> --mode promiscuous --channels 0-83 --dwell 50 --rate nrf1m` | 2 min |
| R0.4 | XN297L sniffer | same, receiver on | same | 2 min |

| Observation | Meaning |
|---|---|
| new advertiser in R0.2 with strong RSSI and changing data | C1 = BLE → BLE plan instead of sessions 1 … 4 |
| frames with `CRC ok` in R0.3 / R0.4 | C2 = XN297L → continue as in the [SCM8 plan](../JieStar/SCM8-Capture-Plan.md) (address mode) |
| nothing (only noise hits without valid CRC) | expected → session 1 |

---

## 6. Session 1 – Find the transmitter (preamble sniffing)

Firmware: **XN297L sniffer**, console tool in raw mode. Sweep all 84 channels with 50 ms dwell (one
sweep ≈ 4.2 s). Each run 2 minutes; operate the controls of the handset continuously (all four
channels, both directions) so that it transmits as much as possible.

| Run | Handset / receiver | Sync | Rate |
|---|---|---|---|
| R1.0 | **both off** (noise reference) | `AAAAAA` | `nrf1m` |
| R1.1 | handset on, receiver off | `AAAAAA` | `nrf1m` |
| R1.2 | handset on, receiver off | `555555` | `nrf1m` |
| R1.3 | handset on, receiver off | `AAAAAA` | `ble1m` |
| R1.4 | handset on, receiver off | `555555` | `ble1m` |
| R1.5 | handset on, receiver off | `AAAAAA` | `nrf2m` |
| R1.6 | handset on, receiver off | `555555` | `nrf2m` |
| R1.7 | handset off, **receiver on** | best setting from R1.1 … R1.6 | |
| R1.8 | handset on, receiver on (paired, if possible) | best setting | |

Command pattern (R1.1):

```bash
$RAW --sync AAAAAA --raw-length 64 --channels 0-83 --dwell 50 --rate nrf1m | tee R1.1.log
```

The other runs only change `--sync` (`AAAAAA` / `555555`) and `--rate` (`nrf1m` / `ble1m` /
`nrf2m`). What to look for (I do the analysis, you only send the logs):

| Observation | Meaning |
|---|---|
| hits cluster on a few channels with clearly stronger RSSI than in R1.0 | transmitter found → frequencies (C3) |
| the bytes right after the sync word repeat in many captures (possibly bit-shifted) | that is the transmitter's **sync word** (C4) → session 2 |
| hits on several channels with the same following bytes | frequency hopping (C7) |
| captures only in R1.7 / R1.8 with receiver on | the handset only transmits when a receiver answers, or the receiver transmits too (C8) |
| nothing above the R1.0 noise level in any run | preamble too short or data rate < 1 Mbps → session 5 (SDR) or session 6 |

If the hits are rare but present on one channel, repeat that setting with `--channels <n>
--dwell 0` for 1 minute to get more captures.

---

### 6.1 Results R1.0 … R1.6 (2026-11-14)

Captured with Wireshark (raw mode, `--raw-length 64`, all channels, 50 ms dwell), handset H1 on and
operated, receiver off; R1.0 with everything off. The runs lasted 20 … 80 s (device time).

| Run | Sync / rate | Frames | Frames of the handset (pattern below) |
|---|---|---|---|
| R1.0 | `AAAAAA` / `nrf1m`, everything off | 60 | 0 |
| R1.1 | `AAAAAA` / `nrf1m` | 62 | **6** (2446 MHz ×2, 2466 MHz ×4, −62 … −69 dBm) |
| R1.2 | `555555` / `nrf1m` | 29 | **1** (2446 MHz, −61 dBm, shifted by 1 bit) |
| R1.3 | `AAAAAA` / `ble1m` | 42 | **1** (2466 MHz, −62 dBm) |
| R1.4 | `555555` / `ble1m` | 51 | **2** (2446 / 2466 MHz, −64 / −76 dBm, shifted by 1 bit) |
| R1.5 | `AAAAAA` / `nrf2m` | 401 | 0 |
| R1.6 | `555555` / `nrf2m` | 849 | 0 |

All 10 handset frames are **bit-identical**. After the sync word `AA AA AA` the dongle received
(64 bytes captured):

```
93 88 B0 CA D0 19 F2 E6  B5 2B E1 01 83 8E E2 C9  A4 71 7A 73 02 5C 45 16  13 88 B0 CA D0 19 F2 E6
93 88 B0 CA D0 19 F2 E6  B5 2B E1 01 83 8E E2 C9  A4 71 7A 73 02 5C 45 16  13 88 B0 CA D0 19 F2 E6
```

- The 32-byte block repeats **without gap** (period exactly 256 bits). The bitstream is not an LFSR
  sequence (linear complexity 255), i.e. real data, not a test pattern.
- The 7-byte group `88 B0 CA D0 19 F2 E6` occurs twice per period, preceded by `13` and `93`.
- The content did not change although the controls were operated – *interpretation:* with the
  receiver off the handset sends a constant bind / search telegram (like the SCM8 and MK4.0
  handsets on 2411 MHz).
- The other frames in R1.1 … R1.4 are noise (also present in R1.0). The many frames with `nrf2m`
  (R1.5, R1.6) are a wide-band signal on 2431 … 2442 MHz with long `AA` / `55` runs and no
  recognisable frame structure – probably 2.4 GHz Wi-Fi (channel 6), not the handset (there is no
  `nrf2m` reference run with everything off).

## 7. Session 2 – Lock onto the sync word, frame structure

New sync word from session 1: **`AA 93 88 B0 CA`** – two preamble bytes plus the first bytes after
the preamble, so that only frame starts are captured (the nRF preamble byte in front matches the
`AA` preamble as well). Runs with `--raw-length 250` show whether the 32-byte block repeats
over the whole transmission and where it ends.

| Run | State | Settings | Duration |
|---|---|---|---|
| R2.1 | handset on, receiver off, controls untouched | `$RAW --sync AA9388B0CA --raw-length 250 --channels 0-83 --dwell 50` | 2 min |
| R2.2 | same, then each channel plus / minus for 5 s (note the times) | same sync, `--channels 46 --dwell 0` | 1 min |
| R2.3 | same as R2.2 on 2466 MHz | `--channels 66 --dwell 0` | 1 min |
| R2.4 | receiver on (paired, motors running), operate all channels | sync as R2.1, `--channels 0-83 --dwell 50`; if nothing is found: R1.1 settings (`AAAAAA`) | 2 min |

The original table below is kept for the later steps of this session.

### 7.1 Results R2.1 … R2.4 (2026-11-15)

Raw mode, sync `AA 93 88 B0 CA`, `--raw-length 250` (255 bytes incl. sync, 2040 bits), `nrf1m`.

| Run | State | Frames | Result |
|---|---|---|---|
| R2.1 | receiver off, sweep 0 … 83 | 27 | only **2446** (13) and **2466 MHz** (14), −58 … −73 dBm; all frames identical |
| R2.2 | receiver off, 2446 MHz, controls operated | 1030 | all frames **identical**, one frame every **29.6 ms** |
| R2.3 | receiver off, 2466 MHz, controls operated | 1019 | identical to R2.2, every 29.6 ms |
| R2.4 | receiver on, paired, controls operated, sweep | 55 | the first 2 frames still bind frames on 2446 MHz, then **2406, 2427, 2446, 2462 MHz**, on each channel one frame every **33.6 ms**; 11 different frame contents |

**Frame structure** (bit 0 = first bit after the `AA` preamble):

| Bits | Content |
|---|---|
| 0 … 511 | header: K0 K1 K2 K0′ K0 K1 K2 K0′ (K0′ = K0 with the first bit inverted), constant in all frames |
| 512 … 515 | 4 bits `1101`, constant |
| 516 + 64·k | symbol k (k = 0 … 22 within the 2040 captured bits; the frame end is not yet captured) |

Every symbol is one 64-bit codeword from a small codebook; all captured symbols match a codeword with
0 … 1 bit errors. The codewords are pairwise 23 … 41 bits apart (nearly orthogonal) and not
rotations or inversions of each other.

| Symbol | 64-bit codeword (on air, MSB first) | Seen in |
|---|---|---|
| K0 | `93 88 B0 CA D0 19 F2 E6` | header, filler (most frequent) |
| K1 | `B5 2B E1 01 83 8E E2 C9` | header; data positions 5 … 7 in operation; position 14 / 15 |
| K2 | `A4 71 7A 73 02 5C 45 16` | header only |
| K3 | `63 31 24 02 8D 10 5F 97` | positions 0, 8, 9 |
| K4 | `81 C0 51 4D 66 CA 15 F8` | position 10 |
| K5 | `C4 F3 03 04 A5 EC D5 5C` | position 11; position 14 / 15 |
| K6 | `8A 27 C0 39 D2 C6 C8 44` | positions 18 … 21 |
| K7 | `C5 3A D4 11 2D 89 E1 97` | positions 18 … 21; position 16 / 17 |
| K8 | `A7 E0 31 71 41 0A 77 2C` | position 22 (bind), position 2 (operation); position 14 / 15 |
| K9 | `A0 0C 1E D3 88 8E 90 2E` | positions 3, 4 (operation) |
| K10 | `8C B0 A4 8A 7E 24 46 38` | position 16 / 17 |
| K11 | `0B 18 AA 98 6C 33 02 DE` | position 22 (operation); position 16 / 17 |
| K12 | `CC 18 FE 2A 95 64 52 52` | position 16 / 17 |
| K13 | `A2 E1 F4 02 A4 2E F3 9A` | position 14 / 15 |
| K14 | `93 03 5E 1B 43 95 C4 02` | position 16 / 17 |

Symbol sequences (positions 0 … 22):

```
bind (R2.1 … R2.3, all 2076 frames):
  K3 K0 K0 K0 K0 K0 K0 K0 K3 K3 K4 K5 K0 K0 K0  K0  K0  K0  K6 K7 K7 K6 K8
operation (R2.4), positions 14 … 17 vary:
  K3 K0 K8 K9 K9 K1 K1 K1 K3 K3 K4 K5 K0 K0 a   b   f(a) f(b) K7 K6 K6 K7 K11
```

- In operation, positions 2 … 7 change from K0 to `K8 K9 K9 K1 K1 K1` and the tail from
  `K6 K7 K7 K6 K8` to `K7 K6 K6 K7 K11` – *interpretation:* receiver / handset ID or a mode flag.
- Positions 14 and 15 carry the control state: values K0, K1, K5, K8, K13 seen.
- Positions 16 and 17 repeat 14 and 15 with a fixed mapping: K0 → K10, K1 → K12, K5 → K11, K8 → K7,
  K13 → K14 (every pair seen in both 14 → 16 and 15 → 17) – *interpretation:* a check or
  complement symbol per data symbol.
- *Interpretation (not verified):* the structure – 1 Mchip/s, a long `AA` preamble, a
  start-of-packet code, data as 64-chip PN codewords, 12 MHz crystal – matches a DSSS transceiver
  of the **Cypress CYRF6936 / CYRF7936** class (WirelessUSB, also used in Spektrum DSM2 / DSMX
  handsets), which needs a 12 MHz crystal. The LT8900 hypothesis does not fit (no plain byte
  payload). Session 6 (SPI on the receiver) or a readable chip marking would confirm it.

### 7.2 Next runs

| Run | State | Settings | Duration | Goal |
|---|---|---|---|---|
| R2.5 | receiver on, paired, controls neutral | `$RAW --sync C53AD4112D --raw-length 250 --channels 46 --dwell 0` (sync = codeword K7, positions 18 / 21) | 30 s | **frame end**: symbols after position 22, length / CRC |
| R2.6 | receiver off (bind) | `$RAW --sync 8A27C039D2 --raw-length 250 --channels 46 --dwell 0` (sync = codeword K6, positions 18 / 21 of the bind frame) | 30 s | end of the bind frame |
| R2.7 | receiver on, paired | `$RAW --sync AA9388B0CA --raw-length 250 --channels 6,27,46,62 --dwell 9` | 1 min | hopping order (frames per channel in sequence) |

Session 4 (mapping) can start right away with the R2.4 settings on one operating channel
(`--channels 46 --dwell 0`), see section 9.

### 7.3 Results R2.5 … R2.7 (2026-11-15)

| Run | State | Sync | Frames | Result |
|---|---|---|---|---|
| R2.5 | paired, controls neutral, 2446 MHz | `C53AD4112D` (K7) | 552 | positions 18 … 29 identical in all frames, then 4 bits `1001`, then noise → **frame end** |
| R2.6 | bind, 2446 MHz | `8A27C039D2` (K6) | 566 | positions 18 … 29 identical in all frames, then `1001`, then noise |
| R2.7 | paired, channels 2406 / 2427 / 2446 / 2462, 9 ms dwell | `AA9388B0CA` | 539 | hopping order and spacing |

**Complete frame** (bit 0 = first bit after the `AA` preamble, 2440 chips ≈ 2.44 ms at 1 Mchip/s):

| Bits | Content |
|---|---|
| 0 … 511 | header K0 K1 K2 K0′ K0 K1 K2 K0′ |
| 512 … 515 | `1101` |
| 516 … 2435 | **30 symbols** (positions 0 … 29) of 64 bits |
| 2436 … 2439 | `1001` |

Symbol sequences, all 30 positions:

```
pos       0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16   17   18 19 20 21 22  23 24 25 26  27 28 29
bind      K3 K0 K0 K0 K0 K0 K0 K0 K3 K3 K4 K5 K0 K0 K0 K0 K0   K0   K6 K7 K7 K6 K8  K2 K0 K0 K13 K3 K7 K4
operation K3 K0 K8 K9 K9 K1 K1 K1 K3 K3 K4 K5 K0 K0 a  b  f(a) f(b) K7 K6 K6 K7 K11 K6 K0 K0 K11 K6 K7 K0
```

(neutral controls: a = b = K0, f(K0) = K10.) Positions 23 … 29 differ between bind and operation
as well – *interpretation:* together with positions 2 … 7 and 18 … 22 an ID / mode block and a
check over the frame.

**Hopping (R2.7):** order **2406 → 2427 → 2446 → 2462 MHz**, then again 2406. Frame starts about
**7.2 ms** apart within the sequence (2406 → 2427 7.2 ms, 2427 → 2446 7.2 ms, 2446 → 2462 7.0 ms),
then a pause of **12.2 ms** before the next 2406 frame; one cycle = **33.6 ms** (= the per-channel
period of R2.4). *Interpretation:* the longer pause may be a receive slot for a receiver response
(C8, not yet observed).



Prerequisite: candidate sync word and channel(s) from session 1. Use the first 3 … 5 bytes of the
sync word as nRF sync, a single channel first, then all found channels.

| Run | State | Settings | Duration |
|---|---|---|---|
| R2.1 | handset on, receiver off, **no control touched** | `$RAW --sync <SW> --raw-length 40 --channels <n> --dwell 0` | 1 min |
| R2.2 | same, all found channels | `--channels <n1>,<n2>,… --dwell 2000` | 2 min |
| R2.3 | handset on, receiver on and working | `--channels <n> --dwell 0` | 2 min |
| R2.4 | same, channel 1 plus, held 10 s, release, channel 1 minus, held 10 s | same | 1 min |
| R2.5 | handset off, receiver on | same | 1 min |
| R2.6 | handset on, receiver on, 2 m distance, then 20 cm | same | 1 min |

Analysis (by me): frame length (where the bytes become random), length byte, repetition interval
(device time stamps), CRC search over the candidate payload (CRC-16 variants with
[CRC RevEng](https://reveng.sourceforge.io/)), bit order (MSB / LSB first), trailer bits, which
bytes change with R2.4 (C6 preview), acknowledgement frames of the receiver in R2.3 / R2.5 (C8).
A sync word and frame layout that match the LT8900 datasheet would answer C9 (*interpretation*
until confirmed by session 6).

Tool follow-up: once the frame layout and the CRC are identified, add a decoder for the CaDA
frames to `xn297l_sniffer.py` / the Wireshark dissector (raw mode only shows the bytes).

---

## 8. Session 3 – Pairing mode

The pairing procedure is not yet documented. First find out *how* pairing is done, then capture it.

**R3.0 – Procedure (no capture):** try and note the LED behaviour of handset and receiver for:

| Try | Sequence |
|---|---|
| a | receiver on first, then handset on |
| b | handset on first, then receiver on |
| c | hold the handset power button `K5` while switching on (several seconds) |
| d | hold the receiver button while switching on / press it several times |
| e | does a receiver that was paired with H1 react to H2 without pairing (if H2 exists)? |

| Run | State | Settings | Duration |
|---|---|---|---|
| R3.1 | pairing sequence from R3.0, start the capture **before** switching on | session 2 settings, all found channels; additionally the sweep from session 1 (`--sync` = preamble) to find a separate bind channel | 1 min |
| R3.2 | same, 3 repetitions with power cycle (same handset) | same | 3 min |
| R3.3 | normal power-on without pairing (already paired) | same | 1 min |
| R3.4 | pairing with H2 (if available) | same | 1 min |
| R3.5 | H1 with a second receiver E2 (if available) | same | 1 min |

Questions: is there a separate bind channel / sync word (like 2411 MHz for SCM8 / MK4.0)? Does a
handset ID appear in the frames, fixed over power cycles (R3.2) and different between H1 and H2
(R3.4)? Does the receiver answer during pairing (C8)?

### 8.1 Results R3.1, R3.2 (2026-11-15)

Raw mode, sync `AA9388B0CA`, `--raw-length 250`. Nibble notation of the symbol positions as in
[CJV8011.md §2.3](CJV8011.md#23-frame-content-as-nibbles).

| Run | State | Frames | Result |
|---|---|---|---|
| R3.1 | **H2** on, receiver off, sweep 0 … 83 | 28 | bind frames on **2443** (13) and **2466 MHz** (15) – H1 uses 2446 / 2466 |
| R3.2 | H1, receiver on (paired with H1), H1 switched off / on 3 × and one channel operated, 2446 MHz | 1075 | after every power-on the same sequence bind → link → operation, ID `255111` every time |
| R3.3 | H2 to be paired with the receiver, 2446 MHz | – | aborted, nothing received (H2 binds on 2443 MHz, not on the captured 2446 MHz) |

Frames (positions 0 … 22; header identical for H1 and H2):

```
                     0-7       8-13   14 15 16 17 18-22
H1 bind              30000000  33A400 0  0  0  0  6DD62
H2 bind              30000000  572444 0  0  0  0  6DD68
H1 link (≈ 0.3 s)    30255111  33A400 0  0  0  0  6DD64
H1 operation         30255111  33A400 A  B  ~A ~B D66DB
```

- **Positions 8 … 13 = handset ID** (24 bits): H1 `33A400`, H2 `572444`; the same in bind, link
  and operation frames.
- The second bind channel depends on the handset (H1 2446 MHz, H2 2443 MHz); 2466 MHz is used by
  both. *Interpretation:* derived from the handset ID.
- **Pairing is automatic after every power-on** (receiver already paired): the handset sends bind
  frames (positions 2 … 7 = `000000`) until the receiver answers (1.5 … 8 s in R3.2), then about
  0.3 s of **link frames** (positions 2 … 7 = `255111`, masks `0 0`, position 22 = `4`), then
  operation frames. No user action is needed.
- **Positions 2 … 7 = link / receiver ID** `255111`: identical after all 3 power cycles. Because
  the bind frames contain `000000` and the ID appears right after the receiver has answered,
  *interpretation:* the ID comes from the **receiver**, which therefore transmits (C8) – the
  receiver frames have not been captured yet.
- Position 22 is a frame type or check nibble: H1 bind `2`, H2 bind `8`, link `4`, operation `B`.

### 8.2 Next runs (done, results in section 8.3)

| Run | State | Settings | Duration | Question |
|---|---|---|---|---|
| R3.3a | receiver on (paired with H1), H1 off, **H2 on**; does the receiver react to H2 (motors)? | `$RAW --sync AA9388B0CA --raw-length 250 --channels 43,46,66 --dwell 300` | 1 min | does H2 get the link ID `255111` or another one, and does the receiver accept H2 without explicit pairing? |
| R3.6 | receiver on, both handsets off | `--sync AAAAAA --raw-length 64 --channels 0-83 --dwell 50`, then the same with `--sync AA9388B0CA` | 2 × 1 min | does the receiver send anything on its own (beacon)? |
| R3.7 | H1 on, receiver switched on **later** (after 10 s), on the bind channel 2466 MHz | `--sync AAAAAA --raw-length 250 --channels 66 --dwell 0` | 30 s | capture the **receiver answer** (frames that are neither handset bind nor link frames) |

### 8.3 Results R3.3a, R3.6, R3.7 (2026-11-15)

| Run | State | Settings | Frames | Result |
|---|---|---|---|---|
| R3.3a | receiver on (last paired with H1), H1 off, **H2 on**; the motor runs (user) | `AA9388B0CA` / 250, channels 43, 46, 66, 300 ms dwell | 311 | H2 bind frames on 2443 / 2466 MHz, after 3.2 s operation frames on **2443 MHz** with link ID **`255111`** – the same as with H1 |
| R3.6a | receiver on, both handsets off | `AAAAAA` / 64, 0 … 83, 50 ms | 51 | noise only (same level as R1.0) |
| R3.6b | same | `AA9388B0CA` / 250, 0 … 83, 50 ms | 0 | nothing |
| R3.7 | H1 on, receiver switched on later, 2466 MHz | `AAAAAA` / 250, dwell 0 | 59 | H1 bind frames until ≈ 7.5 s (then the handset leaves the bind channel); one H1 bind frame captured 2 bits late (see section 8.5); **4 weak unidentified frames** (−85 dBm) from 7.3 s on |

H2 operation frame:

```
H2 operation  30255111  572444  A  B  ~A ~B  D66D1
H1 operation  30255111  33A400  A  B  ~A ~B  D66DB
```

- **Both handsets use the same link value `255111`** after connecting. The receiver accepts H2
  without any explicit pairing step – it reacts to every CaDA handset that starts in its range.
  *Interpretation:* `255111` is the receiver ID (or a constant); a second receiver would decide.
  The handset changes from bind to link frames only when a receiver is on, so the receiver must
  transmit something (C8).
- H2 operates on 2443 MHz (and not on 2446 / 2466 MHz) – the operating channel set depends on the
  handset (*interpretation:* derived from the handset ID, like the bind channel).
- Position 22 of the operation frame differs between the handsets (H1 `B`, H2 `1`) –
  *interpretation:* check nibble over the frame.
- The receiver does not send anything on its own (R3.6).

### 8.4 Runs R3.8 … R3.10 (done, results in section 8.5)

| Run | State | Settings | Duration |
|---|---|---|---|
| R3.8 | receiver off, H1 on | `$RAW --sync AA4E22C32B --raw-length 250 --channels 66 --dwell 0` | 1 min |
| R3.9 | receiver off, H1 on, receiver on after 20 s | same | 1 min |
| R3.10 | H1 on, receiver on, operation, some channels operated | same sync, `--channels 6,27,46,62 --dwell 9` | 1 min |

### 8.5 Results R3.8 … R3.10 (2026-11-15) – no second codeword set

| Run | Frames | Result |
|---|---|---|
| R3.8 | 613 on 2466 MHz (receiver off) | all H1 **bind** frames, read 2 bits late |
| R3.9 | 211 on 2466 MHz | H1 bind frames, read 2 bits late; user: frames only after the receiver was switched on |
| R3.10 | 553 on 2406 MHz | H1 **operation** frames, read 2 bits late (control masks `04`, `00`, `06`, `05`, `14`, `0C`, `84`, `24` – black was held in direction B most of the time) |

Correction of section 8.3: the frame of R3.7 at 2.6 s and all frames of R3.8 … R3.10 are **normal
handset frames captured 2 bits late**, not a second codeword set:

- The preamble `AA …` is alternating, so a sync word that starts with `AA` also matches 2 bits
  later. `AA 4E 22 C3 2B` is exactly the handset stream `AA 93 88 B0 CA …` shifted by 2 bits.
- The "set 2" codewords are the set-1 codewords rotated by 2 chips (all 14 found values), and the
  gap bits `0101` are `1101` with the 2 neighbour chips.
- Read with the 2 missing bits prepended, every frame decodes with codeword set 1, gap `1101`,
  mean 0.2 chip errors per symbol.

Lesson for the tool: with the raw mode, a sync word that begins with preamble bytes can lock at
several bit phases. Use a sync word that starts after the preamble (e.g. `9388B0CAD0`) or check
the alignment in the analysis.

**Unidentified weak frames (R3.7).** Frames #40 (7.3 s), #55, #56, #58 (13.9 … 17.7 s), −85 …
−87 dBm, appear from the moment the handset left the bind channel, i.e. right after the receiver
was switched on. After `AA AA AA` they share ≈ 370 bits (≈ 46 bytes), e.g. `… 3A CE 7D 02 5D …`
(#40 / #56 shifted by 4 bits), then noise. They contain no codeword of set 1 at any bit offset and
no 64-chip periodicity. *Interpretation:* candidate for the receiver's transmission (weaker because
the receiver was farther away), or an unrelated device.

### 8.6 Next runs

| Run | State | Settings | Duration | Question |
|---|---|---|---|---|
| R3.11 | dongle **close to the receiver** (10 cm), handset H1 far away (2 m); H1 on, receiver switched on after 10 s | `$RAW --sync 3ACE7D025D --raw-length 250 --channels 66 --dwell 0` | 1 min | do the unidentified frames appear, and are they stronger near the receiver? |
| R3.12 | same position, receiver on, both handsets off | same | 1 min | does the receiver send them without a handset? |
| R3.13 | same position, H1 on, receiver on, operation | `--sync 3ACE7D025D --raw-length 64 --channels 0-83 --dwell 50` | 1 min | channels of the unidentified frames during operation |

---|---|---|---|---|
| R3.8 | **receiver off**, H1 on | `$RAW --sync AA4E22C32B --raw-length 250 --channels 66 --dwell 0` (sync = header of set 2) | 1 min | does the handset itself send set-2 frames? |
| R3.9 | receiver off, H1 on, then **receiver on after 20 s** (note the time) | same | 1 min | set-2 frames only after the receiver is on → receiver answer |
| R3.10 | H1 on, receiver on, operation | same sync, `--channels 6,27,46,62 --dwell 9` | 1 min | does the receiver answer during operation (12.2 ms pause, C8)? |

---

## 9. Session 4 – Telegram mapping

Receiver paired and running, motors or LEDs on all four ports. Capture with the session 2
settings on one channel (or all found channels). One action at a time, 3 s each, 3 s neutral in
between; note the start time of every action.

| Run | Actions |
|---|---|
| R4.1 | channel 1 (red) plus, minus; channel 2 (blue) plus, minus; channel 3 (black) plus, minus; channel 4 (yellow) plus, minus |
| R4.2 | combinations: 1 plus + 2 plus; 1 minus + 2 minus; 3 plus + 4 minus; all four plus |
| R4.3 | each direction switch in turn: switch over, then channel plus, minus, switch back (find out first which switch belongs to which channel – the photos show only two slide switches `S1`, `S2`) |
| R4.4 | lever moved slowly from neutral to full plus (is there any intermediate value in the telegram?) |

Expected answers: which bits / bytes carry the four channels and the three states (C6); whether
the direction switches change the telegram (handset-side reversal) or set a separate flag; whether
the levers are really only three-state on air.

### 9.1 Results R4.1 … R4.3 (2026-11-15)

Raw mode, sync `AA9388B0CA`, `--raw-length 250`, 2446 MHz, dwell 0, receiver paired. The frames
were segmented by changes of symbol positions 14 … 17; all other positions stayed constant
(operation values of section 7.3).

| Run | Action (user log) | Positions 14 15 16 17 (values, see the codebook below) |
|---|---|---|
| R4.1 | neutral | `0 0 F F` |
| R4.1 | red plus / minus | `0 1 F E` / `1 0 E F` |
| R4.1 | blue plus / minus | `0 2 F D` / `2 0 D F` |
| R4.1 | black plus / minus | `0 4 F B` / `4 0 B F` |
| R4.1 | yellow plus / minus (reversal switch jammed in the reversed position) | `8 0 7 F` / `0 8 F 7` |
| R4.2 | red + blue plus | `0 3 F C` |
| R4.2 | red + blue minus | `3 0 C F` |
| R4.2 | black plus + yellow minus | `0 C F 3` |
| R4.2 | all four plus | `7 8 8 7` |
| R4.3 | reversal red, all plus | `9 6 6 9` |
| R4.3 | reversal blue, all plus | `A 5 5 A` |
| R4.3 | reversal black, all plus | `C 3 3 C` |
| R4.3 | reversal yellow, all plus | `0 F F 0` |

Result: **each 64-chip symbol carries 4 bits**; the 16 codewords form the complete codebook below.
Position 14 = mask A, position 15 = mask B (red 1, blue 2, black 4, yellow 8), positions 16 / 17 =
15 − A / 15 − B in all 5057 operation frames (the 29 exceptions are the bind frames with `0 0`).

- In R4.1 / R4.2 yellow "plus" set the A bit, opposite to the other channels. Cause: the
  direction-reversal switch of yellow **jams** and was in the reversed position (user, 2026-11-15)
  – yellow is not special, all four channels are encoded the same way.
- R4.3 is consistent with R4.1 (red / blue / black "plus" = B, yellow "plus" = A): reversing a
  channel moves its bit to the other mask; with the yellow switch reversed all four channels are in
  mask B (`0 F`). The anchor for the values 5 / A and 6 / 9 is the black step, which reproduces the
  values 3 and C of R4.2.
- R4.2 "all four plus" (`7 8`) is the mirror image of R4.3 – the levers were probably all moved
  in the other direction there.

| Value | 64-bit codeword (on air, MSB first) | Earlier label |
|---|---|---|
| `0` | `93 88 B0 CA D0 19 F2 E6` | K0 |
| `1` | `B5 2B E1 01 83 8E E2 C9` | K1 |
| `2` | `A7 E0 31 71 41 0A 77 2C` | K8 |
| `3` | `63 31 24 02 8D 10 5F 97` | K3 |
| `4` | `C4 F3 03 04 A5 EC D5 5C` | K5 |
| `5` | `A0 0C 1E D3 88 8E 90 2E` | K9 |
| `6` | `8A 27 C0 39 D2 C6 C8 44` | K6 |
| `7` | `93 03 5E 1B 43 95 C4 02` | K14 |
| `8` | `A2 E1 F4 02 A4 2E F3 9A` | K13 |
| `9` | `F0 20 76 4C A1 56 56 72` | new in R4.3 |
| `A` | `81 C0 51 4D 66 CA 15 F8` | K4 |
| `B` | `0B 18 AA 98 6C 33 02 DE` | K11 |
| `C` | `A4 71 7A 73 02 5C 45 16` | K2 |
| `D` | `C5 3A D4 11 2D 89 E1 97` | K7 |
| `E` | `CC 18 FE 2A 95 64 52 52` | K12 |
| `F` | `8C B0 A4 8A 7E 24 46 38` | K10 |

---

## 10. Session 5 (fallback) – SDR

Only if session 1 finds nothing (preamble too short, other data rate or modulation).

| Run | Settings | Goal |
|---|---|---|
| R5.1 | wide-band spectrum / waterfall 2400 … 2484 MHz (e.g. `hackrf_sweep` or the SDR's spectrum view), handset on, operate controls | occupied channels, burst length and interval |
| R5.2 | record I/Q on the strongest channel, ≥ 4 MS/s, 10 s, with control actions | modulation (FSK deviation), data rate, preamble length |
| R5.3 | demodulate in URH, read preamble and sync word | input for session 2 (nRF52840 if the data rate is 1 / 2 Mbps), else continue in URH |

Raw I/Q files are large – send only the cut bursts.

---

## 11. Session 6 (optional) – Logic analyzer on the CJV1010 board

The receiver board has a separate SOP-14 (probably the MCU) and the RF SOP-16 next to the 12 MHz
crystal ([CJV1010 §1.2](CJV1010.md#12-board)). If the MCU configures the RF chip over SPI (as with
the LT8900), the register writes at power-on contain data rate, channel and sync word in clear.

| Run | Probe | Capture | Goal |
|---|---|---|---|
| R6.0 | identify 3 … 4 lines between SOP-14 and RF SOP-16 (continuity check, board unpowered) | – | SPI candidates (CLK, MOSI, MISO, CS) |
| R6.1 | these lines + GND, receiver switched on | ≥ 24 MS/s, trigger on CS, 5 s from power-on | register initialisation |
| R6.2 | same during pairing and normal operation with the handset | 10 s | channel changes (hopping), received payloads read from the FIFO |

Decode with PulseView (SPI decoder). Register numbers and values identify the chip family (C9)
directly if they match a datasheet. Be careful with the probes – the board runs from the 7.4 V
Li-ion pack.

---

## 12. Recording the results

| Result | Goes to |
|---|---|
| frequencies, data rate, sync word, frame layout, CRC | [CJV8011.md §2](CJV8011.md#2-radio-protocol) (new subsections) |
| pairing procedure and bind frames | CJV8011.md §2 and [CJV1010.md §2](CJV1010.md#2-radio-protocol) |
| telegram mapping | CJV8011.md §2, table per channel and state |
| receiver register initialisation (session 6) | CJV1010.md §2 |
| status of C1 … C9 and of each session | this plan, sections 1 and 4 |

---

## 13. Open questions

- Is the nRF52840 preamble trick sensitive enough, or does the CaDA transmitter use a short preamble (1 … 3 bytes)?
- Does the handset transmit continuously or only on control changes / while a receiver answers?
- Is the radio chip in the handset the unmarked SOP-16 on the main board (crystal and antenna sit on the switch board, connected by the 7-wire ribbon cable)?
- Are the EU and the Chinese variants different only in the sync word / frequency, or in the whole protocol?
