# CaDA CJV8011 / CJV1010 – Capture plan for the 2.4 GHz radio link

> Purpose: step-by-step measurement guide for the radio link between the [CJV8011](CJV8011.md) handset and the [CJV1010](CJV1010.md) receiver, mainly with the nRF52840 MDK USB dongle ([XN297L sniffer](../Tools/xn297l-sniffer/README.md) in raw mode, [nRF Sniffer for Bluetooth LE](../Tools/nrf-sniffer-ble/README.md)); SDR and logic analyzer as fallbacks.
> Status: **in progress** – session 0: R0.3, R0.4 done (no XN297L frames, C2 answered); R0.1, R0.2 (BLE) deferred. Session 1: R1.0 … R1.6 done – **handset found** on 2446 / 2466 MHz, 1 Mbps, repeating 32-byte block after an `AA` preamble (section 6.1); next: session 2 with sync `AA 93 88 B0 CA`. Results go to [CJV8011.md §2](CJV8011.md#2-radio-protocol).
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
| C3 | Frequency / frequencies, data rate, modulation | **partly:** 1 Mbps GFSK (received with `nrf1m` and `ble1m`, not with `nrf2m`); handset alone (receiver off) on **2446 and 2466 MHz** (R1.1 … R1.4) |
| C4 | Preamble, sync word (length, value), frame structure: length field, payload length, trailer, CRC, bit order | **partly:** preamble `AA …` (≥ 4 bytes incl. the nRF preamble), followed by a 32-byte block that repeats without gap (section 6.1); frame boundaries, sync word and CRC open (session 2) |
| C5 | Pairing: how is the pairing mode entered, is there a bind channel / bind address, does the handset have a fixed ID, is the receiver bound to one handset afterwards? | open (session 3) |
| C6 | Telegram layout: encoding of the 4 channels × 3 states, effect of the direction switches (handset-side or flag in the telegram) | open (session 4) |
| C7 | Frequency hopping (channels, order, period) | **partly:** only 2446 / 2466 MHz seen with the receiver off; full channel set and order open (R2.1) |
| C8 | Does the receiver transmit (acknowledge, telemetry)? | open (sessions 2, 3) |
| C9 | Chip family (LT8900 / LT8910 class or other)? | open (sessions 2, 6) |

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
| 2 Lock on | handset + receiver | R2.1 … R2.6 | C4, C7, C8, C9 | 45 min | open |
| 3 Pairing | pairing sequences | R3.1 … R3.5 | C5, C8 | 30 min | open |
| 4 Mapping | paired, motors on all ports | R4.1 … R4.4 | C6 | 30 min | open |
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
