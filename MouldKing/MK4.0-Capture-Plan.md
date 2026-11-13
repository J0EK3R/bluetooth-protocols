# Mould King MK4.0 – Capture plan for the original handset / receiver

> Purpose: step-by-step measurement guide that answers the open questions of [MK4.0-Remote.md](MK4.0-Remote.md) (sections 2.2 and 9) with the [XN297L sniffer](../Tools/xn297l-sniffer/README.md) (nRF52840 dongle).
> Status: **plan – no run of this plan has been measured yet.** Answered in the meantime without a run: the receiver's failsafe / LED behaviour (R2.4). New evidence from the [SCM8 handset](../JieStar/SCM8-Remote.md) (same structure, captured 2026-11-13) on the CRC errors (section 3.2), the hopping timing (Q3), the receiver response (Q1) and the control names (Q4). Status per question: section 1.
> Last updated: 2026-11-13 (status update with the SCM8 results)

## Contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Equipment and preparation](#2-equipment-and-preparation)
3. [Tool settings used and hardware limits](#3-tool-settings-used-and-hardware-limits)
4. [Cheat sheet](#4-cheat-sheet)
5. [Session order](#5-session-order)
6. [Questions Q1 … Q6](#6-questions)
7. [What the nRF52840 cannot answer](#7-what-the-nrf52840-cannot-answer)
8. [Tool follow-up proposals](#8-tool-follow-up-proposals)
9. [Recording the results](#9-recording-the-results)
10. [Appendix: settings audit](#10-appendix-settings-audit)
11. [Open questions](#11-open-questions)

---

## 1. Purpose and scope

Six questions are open after the first captures ([MK4.0-Remote.md](MK4.0-Remote.md) section 9 and the comparison with the app protocol in section 7):

| # | Question | Status |
|---|---|---|
| Q1 | What does the receiver send during binding (channel, address, data rate, content)? | open; the SCM8 receiver's answer was not seen on 2411 MHz at 1 Mbps either |
| Q2 | Address length: 5-byte address + 2-byte ID, or 4-byte address + 3-byte identity in the payload? | open, not decidable passively (same for the SCM8) |
| Q3 | Hopping order and dwell time of the four operating channels (2423 / 2441 / 2458 / 2466 MHz) | open; the SCM8 comparison makes a sniffer artefact unlikely (Q3) |
| Q4 | Mapping CH1 … CH6 -> sticks / buttons -> ports A … D | open |
| Q5 | Does the searching receiver listen on 2402 MHz (app) **and** 2411 MHz (bind)? | open |
| Q6 | Is the handset identity fixed or generated at power-on? | open (LED observation suggests fixed) |

For every question this document gives hypotheses, the setup (which device is on or off, in which
order), the exact sniffer settings, the expected result and how to interpret it. The runs are
ordered by device state (section 5) so that one power-up sequence serves as many questions as
possible. Questions that the nRF52840 cannot answer are listed with the hardware that would be
needed (section 7); small tool extensions are only **proposed** (section 8), they are not part of
this plan.

Writing convention: "Expected" and "Hypothesis" are predictions. Only what is measured goes into
[MK4.0-Remote.md](MK4.0-Remote.md), marked as measured, with interpretations marked as such (section 9).

---

## 2. Equipment and preparation

### 2.1 Equipment (assumptions)

| Item | Needed for |
|---|---|
| **One** nRF52840 MDK USB dongle with the XN297L sniffer firmware 1.1.0 | all sessions |
| The three handsets (identities `8C` / `43 EB`, `1C` / `4F 20`, `92` / `60 03`) | all sessions |
| One MK4.0 receiver with battery | sessions 2 … 4 |
| Motors **or** LEDs on the ports A … D (either works, all four ports should have a load) | Q4 |
| Android phone with BrickController2 (the phone that already produced the verified 2402 MHz captures) | Q5 |
| PC with Python 3 and `pip install pyserial` (Wireshark is optional) | all sessions |
| *Optional:* a **second** dongle | improves Q3 and Q5 (marked "optional 2nd dongle") |
| *Optional:* nRF24L01+ module, SDR (HackRF / PlutoSDR), logic analyzer | session 6 only (section 7) |

The plan is written for **one** dongle. Because one dongle sees only one channel at a time,
runs that would need two observers are split into several runs.

### 2.2 Preparation

1. Flash the sniffer firmware if the dongle runs something else ([README](../Tools/xn297l-sniffer/README.md) section 2.1).
2. Find the serial port: `python Tools/xn297l-sniffer/extcap/xn297l_sniffer.py --list-ports`
3. Define the console command once per shell. The log keeps device time in microseconds; `-u`
   makes Python write unbuffered so that `| tee` shows lines immediately. `--show-bad` is always
   on so that frames with CRC errors (useful for timing) stay in the log:

```bash
# run from the repository root; replace <PORT> (e.g. COM5 or /dev/ttyACM0)
SNIFF="python -u Tools/xn297l-sniffer/extcap/xn297l_sniffer.py --print --show-bad --port <PORT>"
```

4. Run each capture as `$SNIFF <options> | tee R<run>-<handset>-<rate>.log` and stop it with
   Ctrl+C. Example: `$SNIFF --mode address --address 8C034B4448 --channels 11 --dwell 0 --payload-length 5 --rate nrf1m | tee R0.1-h3-nrf1m.log`.
5. Write down for every run the actions with a wall-clock time or an action counter (the log has
   no host clock, see F1).

### 2.3 Binding the receiver

Needed whenever a run says "bound" (sessions 3 and 4, and every change of handset). The first
handset that is switched on after the receiver's power-up wins, and the binding is only lost by a
power cycle of the receiver ([MK4.0-Remote.md](MK4.0-Remote.md) section 1):

1. Switch **all** handsets off and power-cycle the receiver (battery off, then on); the receiver searches (LED blinking).
2. Switch on **only** the chosen handset (N).
3. Wait until the LEDs of receiver and handset are constant; check with a short stick movement that a load reacts.
4. To change to another handset: switch it on only after step 1 again (handset N off, receiver power-cycled).

Exception: Q6 step c deliberately switches all three handsets on together, with the receiver off.

### 2.4 Hints

- Place the dongle 0.5 … 1 m from the device under test; do not touch handset and dongle antenna.
- Only one program may hold the serial port (close Wireshark when using `--print`).
- 2.4 GHz Wi-Fi overlaps 2411 / 2441 / 2466 MHz: note the state of the router (or switch it off
  for the session) and keep the same state for comparable runs.
- The device time is a 32-bit microsecond counter and wraps after about 71.6 minutes: keep every
  run well below that and restart the capture if one runs longer.
- **Logs are not committed to the repository.** Keep the raw `--print` logs locally; only the
  results (tables, interpretations) are written to [MK4.0-Remote.md](MK4.0-Remote.md).

---

## 3. Tool settings used and hardware limits

### 3.1 Settings that exist in the tools

"Wireshark option" is the display name in the extcap dialog (gear icon), "console option" the
`--print` command-line option, "firmware command" what the script sends to the dongle.

| Setting | Wireshark option | Console option | Firmware command | Values used here |
|---|---|---|---|---|
| Sync mode | Sync mode (*Known address* / *Promiscuous (preamble)*) | `--mode address` / `--mode promiscuous` | `sync <hex>` (derived) | both |
| Address (address mode) | Address (TX_ADDR order, hex) | `--address HEX` | `sync` (derived) | 3, 4 or 5 bytes; here 4 or 5 |
| Address length (promiscuous) | Address length (promiscuous) | `--address-length 3\|4\|5` | `len` (derived) | 5 |
| Payload length | Payload length (0 = auto) | `--payload-length N` | `len` (derived) | 0, 5, 8 |
| RF channels | RF channels (MHz - 2400) | `--channels LIST` | `ch <list>` | `0-83`, single channels, lists |
| Dwell | Dwell time per channel (ms) | `--dwell MS` | `dwell <ms>` | 0, 1, 20 |
| Data rate | Data rate | `--rate nrf1m\|ble1m\|nrf2m` | `rate <r>` | all three |
| Extra bytes | Extra bytes after the frame | `--extra-bytes N` | `len` (derived) | 200 |
| Show CRC errors | (always shown) | `--show-bad` | – | always |

Ranges enforced by the tools: sync word 3 … 5 bytes; channels 0 … 100, ranges `a-b`, at most 84
list entries; dwell 0 … 60000 ms (`0` = stay on the first channel); capture length 1 … 250 bytes
after the sync word (payload or automatic search margin of 32 bytes + 2 CRC + extra bytes, plus
the address length in promiscuous mode); extra bytes 0 … 200; payload length 0 … 64 in the
Wireshark dialog. `--no-scramble` exists but is not needed here.

Wireshark display filters (from the [README](../Tools/xn297l-sniffer/README.md) section 3.2 and the Lua dissector): `xn297l.crc_ok == 1`,
`xn297l.hdr.rssi > -85`, `xn297l.hdr.freq == 2411`, `xn297l.address == "8C:6C:DB:6E:0E"`,
`xn297l.payload_len == 8`, `xn297l.hdr.timestamp` (device time column).

### 3.2 Hardware limits of the nRF52840 sniffer

- Data rates only `nrf1m`, `ble1m`, `nrf2m`. **No 250 kbps** (the nRF52840 has no 250 kbps proprietary
  mode; the XN297L supports it).
- One channel and one sync word at a time. Receive only: **no transmit**, so no injection and no
  acknowledgement tests.
- Promiscuous mode is experimental (no alternating preamble in front of the sync word), frames may
  be missed. Address mode is the robust mode.
- The MK4.0 handsets show 6 … 10 % CRC errors (systematic) with `nrf1m`. The SCM8 handset, captured
  with the same dongle and settings, shows only 7 bad frames out of 9451 (0.07 %, R4.1 of the
  [SCM8 plan](../JieStar/SCM8-Capture-Plan.md)). The errors are therefore specific to the MK4.0
  handsets (frequency offset / deviation, interpretation), not a general limit of the sniffer;
  `ble1m` may still be better for the MK4.0 (session 0 checks it).
- Hopping: dwell has 1 ms granularity (checked against the millisecond uptime), every hop restarts
  the radio (ramp-up) and drops a frame in progress.
- Capture window after a frame is at most 250 bytes (extra bytes ≤ 200 = 1.6 ms at 1 Mbps).
- Device time: 32 bit microseconds from the kernel clock (resolution about 30 µs, **assumption**: the tick rate of `k_uptime_ticks` is not stated in the repository; verify with the spacing of timestamps), wraps after 71.6 min.
- `--print` has device time only: no host clock, no event markers, no energy-detect / RSSI scan.

---

## 4. Cheat sheet

### 4.1 Addresses and channels

From [MK4.0-Remote.md](MK4.0-Remote.md) section 3. Addresses are given in `TX_ADDR` order (LSByte first), as expected by `--address`.

| Handset | Identity byte | ID | Bind `TX_ADDR` (5 B) | Operation `TX_ADDR` (5 B) |
|---|---|---|---|---|
| 1 | `8C` | `43 EB` | `8C034B4448` | `8C6CDB6E0E` |
| 2 | `1C` | `4F 20` | `1C034B4448` | `1C6CDB6E0E` |
| 3 | `92` | `60 03` | `92034B4448` | `926CDB6E0E` |
| common 4-byte part | – | – | `034B4448` | `6CDB6E0E` |

- Channels (`ch` = MHz - 2400): bind `11`; operation `23,41,58,66`; app `2`.
- A 4-byte address is accepted in address mode (sync word 3 … 5 bytes).
- With the 4-byte address the identity byte appears as the first payload byte, bit-reversed
  (`8C -> 31`, `1C -> 38`, `92 -> 49`): bind payload `31 43 EB 00 00 00` (6 B), operation payload
  `31 43 EB CH1 … CH6` (9 B). With the 5-byte address: bind payload `43 EB 00 00 00` (5 B),
  operation payload `43 EB CH1 … CH6` (8 B).
- Neutral stick value: `80`.

### 4.2 Reading a console line

```
   12.345678s 2423 MHz  -55 dBm  addr 8C:6C:DB:6E:0E  CRC ok   len  8  payload 43 EB 80 80 80 80 80 80
```

Device time in seconds (microsecond digits), frequency, RSSI, address in `TX_ADDR` order, CRC
status, payload length, payload. Frames without a valid CRC print `no valid CRC  raw ...`.

### 4.3 Gap histogram without a tool

Gap in ms between consecutive valid frames of one log (one channel per log):

```bash
awk '/CRC ok/ {t=$1+0; if (p) printf "%.0f\n", (t-p)*1000; p=t}' R3.5a.log | sort -n | uniq -c
```

---

## 5. Session order

Principle: group runs by **device state** so that each power-up sequence is used for as many
questions as possible. A handset only leaves the bind phase when a receiver answers, so
operation-phase runs need the receiver switched on and bound.

| Session | Device state | Runs | Questions | Time |
|---|---|---|---|---|
| 0 Preparation | handset 3 on, receiver off | R0.1, R0.2 | calibration: choose `RATE*` | 20 min |
| 1 Handset only | handsets switched on/off, receiver off | R1.1, R1.2 | Q6, Q2 (passive part), bind timing | 30 min |
| 2 Receiver only | receiver on and searching (LED blinking), all handsets off | R2.0 … R2.3 | Q1 (beacon hypothesis) | 25 min |
| 3 Handset + receiver | receiver bound to handset 1; plus off/on cycles | R2.4, R3.1 … R3.9 (R3.10 = analysis) | Q1, Q3, Q4, Q6 cross-check | 90 min |
| 4 App + handset + receiver | race experiments | R4.0 … R4.4 | Q5 | 45 min |
| 5 Optional: 2nd dongle | see Q3 / Q5 notes | – | Q3, Q5 | open |
| 6 Optional: extra hardware | see section 7 | – | Q1, Q2, Q3 | open |

Rules:

- Do **session 0 first**. Its result `RATE*` (the better of `nrf1m` / `ble1m`, i.e. fewer CRC
  errors at the same number of bind bursts) is used in every later run that says `RATE*`.
- Session 2 before 3: a receiver that was never bound is the clean "searching" case.
- Session 4 last: it needs the receiver power-cycled many times.
- Extra hardware (nRF24L01+, SDR, logic analyzer, opening a handset or the receiver for SPI
  tapping) is **optional** and only used if sessions 0 … 4 leave Q1 / Q2 / Q3 open. Opening a device may void
  the warranty; this is the product owner's decision.

### Session 0 – calibration

Handset 3 on, receiver off (the handset stays in its bind phase). Both runs 120 s, handset
untouched:

| Run | Mode / address | Channels | Dwell | Payload length | Rate | Options |
|---|---|---|---|---|---|---|
| R0.1 | address `92034B4448` | `11` | 0 | 5 | nrf1m | `--mode address --address 92034B4448 --channels 11 --dwell 0 --payload-length 5 --rate nrf1m` |
| R0.2 | address `92034B4448` | `11` | 0 | 5 | ble1m | `--mode address --address 92034B4448 --channels 11 --dwell 0 --payload-length 5 --rate ble1m` |

Evaluation: count lines with `CRC ok` and with `no valid CRC` / `CRC BAD`. `RATE*` is the rate with
the lower share of bad frames (known: 6 … 10 % with `nrf1m`). If both are equal use `nrf1m`.

---

## 6. Questions

### Q1 – Receiver response during binding

**Hypotheses** (from [MK4.0-Remote.md](MK4.0-Remote.md) section 2.2):

- H1a: the searching receiver sends a beacon on **another channel**, which the handset hears in the ~14 ms gaps between its bind telegrams.
- H1b: the reply uses **another data rate** (2 Mbps, or 250 kbps).
- H1c: the reply is on one of the **operating channels**.
- H1d: the reply uses the handset's own bind address but a different length or payload (earlier captures fixed the payload length to 5, which would hide it in the CRC-bad list).

Already ruled out: a 1 Mbps XN297L frame with preamble on 2411 MHz in promiscuous mode, and an acknowledgement within 1.2 ms after a bind telegram.
The SCM8 handset uses the same bind channel; its receiver's answer was not seen on 2411 MHz at 1 Mbps
either (R1.b of the [SCM8 plan](../JieStar/SCM8-Capture-Plan.md)), so the answer is likely of the same
kind for both receivers (interpretation) and a result here probably applies to the SCM8 as well.

**Setup.** Part A (session 2): receiver on and searching (LED blinking), all handsets off. Part B
(session 3): receiver on and bound, handset 1 switched off for 5 s and on for 5 s, ten times; the
receiver LED must stay constant after each cycle (note any cycle where the handset LED stays
blinking).

**Runs** (`--payload-length 0` = automatic length search):

| Run | State | Options | Duration |
|---|---|---|---|
| R2.0 reference | everything off | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 20 --rate nrf1m` | 120 s |
| R2.1 | receiver just powered on, searching, handsets off | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 20 --rate nrf1m` | 120 s |
| R2.2 | as R2.1 | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 20 --rate ble1m` | 120 s |
| R2.3 | as R2.1 | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 20 --rate nrf2m` | 120 s |
| R2.4 | receiver bound to handset 1, handset switched off (known from [MK4.0-Remote.md §1.1](MK4.0-Remote.md#11-led-behaviour): the receiver LED blinks again after a few seconds, the receiver stays bound) | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 20 --rate nrf1m` | 120 s |
| R3.1 | bound, handset 1 off/on 10x (5 s each) | `--mode address --address 8C034B4448 --channels 11 --dwell 0 --payload-length 0 --rate nrf1m` | ~2 min |
| R3.1x | as R3.1 | `--mode address --address 8C034B4448 --channels 11 --dwell 0 --payload-length 5 --extra-bytes 200 --rate nrf1m` | ~2 min |
| R3.2 | as R3.1 | `--mode promiscuous --address-length 5 --payload-length 0 --channels 11 --dwell 0 --rate nrf2m` | ~2 min |
| R3.3 | as R3.1 | `--mode promiscuous --address-length 5 --payload-length 0 --channels 11 --dwell 0 --rate ble1m` | ~2 min |
| R3.4a – d | as R3.1 (10 cycles each) | `--mode promiscuous --address-length 5 --payload-length 0 --channels 23 --dwell 0 --rate nrf1m`, and the same with `--channels 41`, `--channels 58`, `--channels 66` | 4 x 2 min |

In R2.4, R3.1, R3.1x and R3.4 replace `nrf1m` by `RATE*` when session 0 chose `ble1m` (R2.2 / R2.3
and R3.2 / R3.3 keep their listed rates). Wireshark equivalents: the same values in the dialog
fields of section 3.1.

Console examples: R2.1: `$SNIFF --mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 20 --rate nrf1m | tee R2.1.log`;
R3.1: `$SNIFF --mode address --address 8C034B4448 --channels 11 --dwell 0 --payload-length 0 --rate nrf1m | tee R3.1.log`.

Mapping to the captures planned in [MK4.0-Remote.md](MK4.0-Remote.md) section 2.2: A = R2.1, B = R2.3, C = R3.2.
A sweep of 84 channels at 20 ms takes 1.7 s, so 120 s give about 70 sweeps; a beacon that is sent
less often than about once per 1.7 s on one channel can be missed (use longer runs then).
R2.0 is the noise reference: random 24-bit hits at -95 … -100 dBm without a valid CRC
([README](../Tools/xn297l-sniffer/README.md) Status). Useful filters: `xn297l.crc_ok == 1`, `xn297l.hdr.rssi > -85`, `xn297l.hdr.freq == 2411`.

**Expected result / interpretation:**

| Observation | Meaning |
|---|---|
| R2.1 … R2.3 contain frames with a valid CRC (or RSSI > -85 dBm) that R2.0 does not | H1a: beacon found; record channel, rate, address, payload and period (device time) |
| Strong, repeating hits on one channel, always CRC bad | a transmitter is present but format or rate does not match: repeat that single channel with the other rates; if none works, see section 7 |
| R3.1 shows frames with address `8C034B4448` but another length or payload | H1d: reply with the handset's address; decode the payload |
| R3.1x: the bytes after the frame contain a new preamble | immediate reply within 1.6 ms (200 extra bytes = 1.6 ms; the earlier test covered 1.2 ms) |
| A reply appears only in R3.2 / R3.3 / R3.4x | H1b / H1c; the run names the rate and the channel |
| Nothing anywhere | the reply is 250 kbps or not XN297L-framed: hardware of section 7 (F4 energy detect first) |

Bonus from R3.1 without any extra setting: number of bind frames and the time from the last bind
frame to the first operation frame after each handset power-on (length of the receiver's reply
window); spacing of frames inside a bind burst (the handset's possible RX window).

**Limits:** 250 kbps cannot be received; one channel and one data rate at a time; promiscuous mode
is experimental, so a reply may be missed – the address-mode run R3.1 is the robust one.

### Q2 – Address length

**Hypotheses:** H2a: 5-byte address with a 2-byte ID in the payload. H2b: 4-byte common address with a 3-byte identity at the start of the payload.

**Key statement (interpretation):** both give **bit-identical frames on air**. The CRC covers
address and payload together, so a **passive sniffer cannot decide** (also stated in the [sniffer README](../Tools/xn297l-sniffer/README.md), open questions).
Supporting argument for H2b or a hybrid: an unbound receiver accepts the first handset of any
identity, but an XN297L matches a full address; in the bind phase it can therefore only use the
4 common bytes (`48 44 4B 03` on air); after binding it may switch to a 5-byte address, which is
not observable on air. For an emulator the difference is irrelevant (the same bits are sent); it
matters for which identity bytes can be chosen freely and for the sniffer's address length.

**Setup.** Session 1: receiver **off**, handsets in their bind phase. Passive runs only (same
captures as Q6):

| Run | Mode / address | Channels | Dwell | Payload length | Rate | Options |
|---|---|---|---|---|---|---|
| R1.1 | address `034B4448` (4 B) | `11` | 0 | 0 | RATE* | `--mode address --address 034B4448 --channels 11 --dwell 0 --payload-length 0 --rate nrf1m` |
| R1.2 | address `8C034B4448` (5 B) | `11` | 0 | 5 | RATE* | `--mode address --address 8C034B4448 --channels 11 --dwell 0 --payload-length 5 --rate nrf1m` |

(Replace `nrf1m` by `ble1m` if `RATE*` is `ble1m`.)

**Expected result:** R1.1 prints `addr 03:4B:44:48 ... len  6 payload 31 43 EB 00 00 00` for handset 1 and `38 4F 20 ...` /
`49 60 03 ...` for handsets 2 and 3 (all handsets in one run). R1.2 prints only handset 1 with the same frame count.

**Interpretation:** this confirms only the equivalence of A and B. The decisive tests need transmit
capability (F5) or an SPI tap (section 7). Q2 is documented as "not decidable passively;
plausible: 4 bytes in the bind phase".

**Limits:** bit-identical frames; no passive solution exists.

### Q3 – Hopping order and dwell time

**Hypotheses:**

- H3a: one frame per hop, fixed order, equal dwell D (then 4 D between frames of one channel; this contradicts the measured alternating ~17 / 28 ms gaps unless the slots are uneven).
- H3b: unequal slots or each channel visited twice per cycle (8 slots; 17 + 28 = 45 ms cycle).
- H3c: bursts of repeated frames per channel visit.
- H3d: pseudo-random order.

All four channels are expected to carry the same payload.

Comparison: the SCM8 handset, captured in address mode on one of its operating channels, shows a
**constant** period of 16.07 ms (99.8 % of the slots, [SCM8-Remote.md §2.1](../JieStar/SCM8-Remote.md#21-timing)).
The sniffer therefore does not create irregular gaps by itself; the alternating ~17 / 28 ms gaps of
the MK4.0 are most likely real (interpretation), which favours H3b or H3c over H3a.

**Setup.** Session 3: receiver and handset 1 bound, sticks untouched (neutral) so that payloads are constant.

**Runs** (single dongle; device timestamps come from one clock):

| Run | Mode / address | Channels | Dwell | Payload length | Rate | Duration | Options |
|---|---|---|---|---|---|---|---|
| R3.5a – d (per channel) | address `8C6CDB6E0E` | `23`, `41`, `58`, `66` | 0 | 8 | RATE* | 60 s each | `--mode address --address 8C6CDB6E0E --channels 23 --dwell 0 --payload-length 8 --rate nrf1m` (then `--channels 41`, `58`, `66`) |
| R3.6a – f (pairs) | same | `23,41` `23,58` `23,66` `41,58` `41,66` `58,66` | 1 | 8 | RATE* | 60 s each | `--mode address --address 8C6CDB6E0E --channels 23,41 --dwell 1 --payload-length 8 --rate nrf1m` (and the other five pairs) |
| R3.7 (all four) | same | `23,41,58,66` | 1 | 8 | RATE* | 60 s | `--mode address --address 8C6CDB6E0E --channels 23,41,58,66 --dwell 1 --payload-length 8 --rate nrf1m` |
| R3.8a – d (weak copies) | same | `42`, `50`, `74`, `82` | 0 | 8 | RATE* | 60 s each | `--mode address --address 8C6CDB6E0E --channels 42 --dwell 0 --payload-length 8 --rate nrf1m` (then `--channels 50`, `74`, `82`) |

**Analysis** (manual with the awk snippet of section 4.3, or with F2):

1. R3.5: frames per second and gap histogram per channel (expect ~47 fps and alternating ~17 / 28 ms on 2423 MHz); the same rate and gap pattern on all channels supports one frame per slot on every channel.
2. Cycle length T = sum of one repeating gap group on a channel.
3. R3.6: for each frame on channel a, take the next frame on channel b; the delay histogram shows a sharp peak at the phase offset of b relative to a (the dongle spends about 50 % of the time on each channel at dwell 1, so only some cycles yield a pair). Sort the offsets of all channels -> hopping order; differences of neighbours -> dwell per slot. A flat histogram -> H3d.
4. R3.7 (sanity): frames per channel are roughly 25 % of the R3.5 rates. Move a stick once during R3.7: all channels must show the new value, confirming that all channels carry the same payload.
5. R3.8: if the weak frames on 2442 / 2450 / 2474 / 2482 MHz have the same gap pattern and phase as the neighbouring main channel and vanish when the distance is increased by about 1 m while the main channels drop only slightly, they are adjacent / image reception and not extra hop channels. Otherwise there are extra channels.

**Expected result:** a repeating gap pattern per channel, a stable phase offset per channel pair, equal payload on all channels.

**Limits:** dwell has 1 ms granularity; each hop costs a radio ramp-up (~100 µs or more, **assumption**, not derived from the tool sources) and drops a
frame in progress; timestamp resolution ~30 µs (**assumption**, see section 3.2). The accuracy suffices for ms-scale slots, not for
the exact dwell in µs. *Optional 2nd dongle:* two dongles on two channels with a common host clock
(F6) give the order directly; microsecond-level dwell needs F3 or an SPI tap.

### Q4 – Channel mapping CH1 … CH6 -> controls -> ports A … D

**Hypotheses:** H4a: CH1 … CH4 are the four stick axes, CH5 / CH6 are button pairs or 3-position
switches (values `02` / `80` / `FE`). H4b: CH1 … CH4 map to ports A … D in order (or in a pairing like the
app: channel 0 = port A … 3 = port D, see [MK4.0.md](MK4.0.md) section 3). H4c: CH5 / CH6 have no effect on the MK4.0 receiver.

**Setup.** Session 3: receiver bound to handset 1 (procedure in section 2.3), a motor or LED on each of the ports A, B, C, D
(or move one load across the ports). Run R3.9 for about 5 minutes:

| Run | Mode / address | Channels | Dwell | Payload length | Rate | Options |
|---|---|---|---|---|---|---|
| R3.9 | address `8C6CDB6E0E` | `23` | 0 | 8 | RATE* | `--mode address --address 8C6CDB6E0E --channels 23 --dwell 0 --payload-length 8 --rate nrf1m` |

**Procedure.** First note the markings printed on the handset: the SCM8 handset labels its controls
with the port letters A … H ([SCM8-Remote.md, Handset](../JieStar/SCM8-Remote.md#handset)), which
may answer the port part of Q4 directly. Each action is held 3 s with 3 s neutral in between, in this fixed order, and is
written down with its number (the log has no markers; use the action list together with the
changing payload):

| # | Action on the handset | Log column that must change | Receiver observation |
|---|---|---|---|
| 0 | all neutral, 10 s | baseline `80 80 80 80 80 80` | no motor / LED |
| 1 – 4 | left stick up / down / left / right | CHn above / below `80` | port and direction |
| 5 – 8 | right stick up / down / left / right | CHn | port and direction |
| 9 – 12 | each button / switch position of CH5 and CH6 | `02` / `FE` | any effect? |
| 13 | slow sweep of one stick from neutral to the end over ~10 s | monotone `80 -> FF` (or `00`) | speed steps visible? |

**Expected result:** per action exactly one of CH1 … CH6 differs from `80`. Result table: action ->
CHn -> port, direction, value range (section 9). **Interpretation:** record the measured values
only (minimum / maximum actually seen); note separately if one action moves two ports (mixing).
Step 13 shows whether the receiver reacts in 255 steps or in coarse steps (compare the app: 7 steps per direction).
Repeat with handset 2 or 3 (re-bind as in section 2.3; the identity must not change the mapping). R3.5 shows that all four
channels carry the same payload, so one hop channel is sufficient.

**Limits:** none for the nRF52840.

### Q5 – Does the searching receiver listen on 2402 MHz (app) and 2411 MHz (bind)?

**Hypotheses:** H5a: the receiver alternates between both frequencies (time slicing). H5b: it
listens on one of them first (priority). H5c: the first source wins by arrival time, independent of
frequency. "The first source after power-on wins" is already documented; this tests a
**simultaneous** start.

**Setup.** Session 4: receiver power-cycled for every trial; handset 1; phone with BrickController2
and an MK4.0 device configured. With one dongle only one side can be observed at a time:

| Run | Observer | Options |
|---|---|---|
| R4.0 sanity (before the series, and after it) | app side (verified settings, [README](../Tools/xn297l-sniffer/README.md) Status) | `--mode address --address C1C2C3C4C5 --channels 2 --dwell 0 --payload-length 0 --rate ble1m` |
| R4.1 trial observer | handset side | `--mode address --address 8C034B4448 --channels 11 --dwell 0 --payload-length 5 --rate nrf1m` |

R4.0 is expected to show Connect `AD .. 80 80 80 4F 52` and then Command `7D ..` telegrams, which
proves that the phone transmits. R4.1 shows bind frames while the handset is in its bind phase;
they stop when it hops to operation ("handset won" is visible from the log). In R4.1 use `RATE*`
instead of `nrf1m` if `ble1m` was chosen. *Optional 2nd dongle:* run the R4.0 settings
concurrently on a second `--port` to prove that the app telegrams are on air during the whole trial.

**Trials** (10 repetitions each; record the winner, receiver LED, handset LED, motor reaction to the handset sticks and to an app command):

| Trial | Sequence | Question |
|---|---|---|
| R4.2 (control) | only the handset on, then power the receiver, 5x; the same with only the app (Connect already sent), 5x | baseline lock latency (coarse, by eye) |
| R4.3 (race) | handset on (bind phase), app started and sending, then receiver switched on | who wins? |
| R4.4 (order) | receiver on first (searching), then handset on, 3 s later app start; then reversed order | does the first source win? |
| R4.4x | after the winner is locked, drive with the other source | locked mode stays (expect no reaction) |

BrickController2 hint: it sends Connect at the start and again after 3 s of all-zero channels
([MK4.0.md](MK4.0.md) section 1.1), so keep the channels at zero for more than 3 s after the receiver
power-up to get a fresh Connect.

**Interpretation:** R4.3 about 50 / 50 -> H5a (alternating scan; the win ratio and the lock latencies of
R4.2 indicate the scan duty). Always handset (or always app) -> H5b with that priority, but check the
duty-cycle bias (handset bursts every ~14 ms vs. the app's advertising interval). R4.4 always the
first source -> H5c, consistent with the documentation. Outcome "none" -> interference, repeat.

**Caveat:** this is behavioural evidence only; the receiver's radio cannot be observed. **Limit:** one dongle shows one channel at a time.

### Q6 – Is the handset identity fixed or generated at power-on?

**Hypotheses:** H6a: fixed (factory programmed). H6b: random at each power-on. H6c: partly fixed
(e.g. identity byte fixed, 2-byte ID random). The LED observation (the handset is constant
immediately when switched on again with a bound receiver) already suggests H6a.

**Setup.** Session 1, receiver **off** (no binding needed, section 2.3 only for the cross-check): R1.1 (settings of Q2: 4-byte address `034B4448`, channel `11`, dwell 0, payload length 0, `RATE*`, `--show-bad`), one capture per handset:

| Step | Action | Count |
|---|---|---|
| a | switch off 5 s, on, wait 5 s | 10x per handset |
| b | remove the battery for 1 min (capacitors discharge), insert | 3x per handset |
| c | all three handsets on at the same time (different identities visible in one log) | 1x |

Cross-check (R3.10, analysis only, no extra run): in the R3.1 log (session 3, receiver bound) the
motor must still react after each cycle, and the identity in the bind frames equals the identity in
the operation frames of R3.5.

**Expected result (H6a):** identical first payload byte and ID in all cycles (`31 43 EB` for handset 1).
**Interpretation:** any change between cycles -> H6b / H6c; then the receiver cannot rely on a fixed
identity, and "first handset wins" plus the "constant immediately" observation must be re-examined
(a changed identity with a still-working receiver would mean the receiver re-binds). Also record
whether the three identities differ in more than the three known bytes.

**Limits:** none for the nRF52840.

---

## 7. What the nRF52840 cannot answer

| Question | nRF52840 enough? | Limit | Hardware needed otherwise |
|---|---|---|---|
| Q1 | partly | reply at 250 kbps or with unknown framing is invisible | nRF24L01+ / BK2425-class module with an SPI MCU (250 kbps, address-sniffing trick); SDR with 2.4 GHz range (HackRF, PlutoSDR, LimeSDR – an RTL-SDR does not reach 2.4 GHz); logic analyzer on the SPI bus of the handset's radio (shows RX address, channel and data rate set by the handset after binding); F4 |
| Q2 | no (passive part only) | bit-identical frames | TX capability (F5, nRF24L01+ / XN297L module) or SPI tap (address-width register, `TX_ADDR` writes) |
| Q3 | yes (statistical) | ms dwell granularity, one channel at a time | 2nd / 3rd dongle + F6, F3, or SPI tap (RF-channel register writes with timing) |
| Q4 | yes | none | – |
| Q5 | yes (behavioural) | receiver radio not observable | 2nd dongle for parallel 2402 / 2411 view |
| Q6 | yes | none | – |

**Session 6 (optional, extra hardware):** SPI tap with a logic analyzer (3.3 V logic, ≥ 8 MHz
sampling) on the handset board, and on the receiver board if a separate SPI radio exists (the
receiver's `2148dMC` part is unidentified, [MK4.0.md](MK4.0.md) section 8.2). It requires opening
the device and may void the warranty; the product owner decides. The nRF24L01+ / SDR runs reuse
the channel and rate lists of Q1.

---

## 8. Tool follow-up proposals

Separate tasks; **not implemented** by this plan.

| ID | Proposal | Problem solved | Size | Helps |
|---|---|---|---|---|
| F1 | `--print`: host wall-clock column and a manual marker (keypress `m` writes a `# mark` line); rollover handling of the 32-bit device time | power-on and action moments are only noted by hand; the clock wraps after 71.6 min | small (Python only) | Q1, Q4, Q5 |
| F2 | `tools/hop_analyzer.py`: reads `--print` logs, prints per-channel rate, gap histogram, pair-phase histogram | R3.5 / R3.6 evaluation is manual | small | Q3 |
| F3 | microsecond dwell (hardware timer instead of the 1 ms uptime) and an optional "follow" mode that hops using the learned period | exact dwell and complete hop sequence with one dongle | medium (firmware) | Q3 |
| F4 | energy-detect / RSSI burst scan: report time, channel and RSSI of bursts without a sync word | detect replies of any data rate (even 250 kbps) and their timing | medium (firmware) | Q1 |
| F5 | TX firmware command (send a raw on-air frame, e.g. bind or control frame; the app frame natively on 2402 MHz) | active experiments: accepted identities, address length, handset emulation | large | Q2, Q5 |
| F6 | multi-dongle capture helper: one host clock for two serial ports | order across channels and parallel 2402 / 2411 observation | small-medium | Q3, Q5 |
| F7 | Lua dissector for MK4.0 handset frames (registers `8C6CDB6E0E` etc. via `xn297l.address`; shows CH1 … CH6) | readable Wireshark view | small | Q4 |

---

## 9. Recording the results

Copy the filled tables into [MK4.0-Remote.md](MK4.0-Remote.md). Keep **measured** (what the log shows) strictly separate from **interpretation**. Raw logs stay local.

**Q1 / Q6 – frames found**

| Run | Channel | Rate | Address | Length | Payload | Period / count | Remark |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

**Q3 – hop timing** (device time, per channel)

| Channel (MHz) | Frames / s | Gap pattern (ms) | Phase offset to 2423 MHz (ms) | Remark |
|---|---|---|---|---|
| 2423 | | | 0 | |
| 2441 | | | | |
| 2458 | | | | |
| 2466 | | | | |

**Q4 – channel mapping** (handset ___)

| # | Action | Column that changed | Min / max value seen | Port | Direction / effect |
|---|---|---|---|---|---|
| | | | | | |

**Q6 – identity** (per handset)

| Handset | Cycles checked | First payload byte | ID | Changed? |
|---|---|---|---|---|
| 1 / 2 / 3 | | | | |

**Q5 – trial tally**

| Trial | Repetitions | Handset won | App won | Neither | Remark |
|---|---|---|---|---|---|
| R4.2 | | | | | |
| R4.3 | | | | | |
| R4.4 (receiver first) | | | | | |
| R4.4 (handset first) | | | | | |
| R4.4x | | | | | |

**Q2** is recorded as "not decidable passively" unless session 6 delivers more.

---

## 10. Appendix: settings audit

Every distinct sniffer setting used in this document and where it exists in the tools
(`Tools/xn297l-sniffer/`): `extcap/xn297l_sniffer.py` (`build_parser`, `extcap_config`, `configure`,
`run_print`), `firmware/src/main.c` (`handle_command`), `firmware/src/radio.h` (limits).

| Setting value used | Where it exists |
|---|---|
| `--print`, `--show-bad`, `--port` | `build_parser` (console mode) |
| `--mode address`, `--mode promiscuous` | `build_parser` choices; `extcap_config` arg 1 |
| `--address` with 3 … 5 bytes (used: `8C034B4448`, `92034B4448`, `034B4448`, `8C6CDB6E0E`, `C1C2C3C4C5`) | `configure` (`len(tx_addr) in (3, 4, 5)`); firmware `sync` 3 … 5 bytes |
| `--address-length 5` | `build_parser` choices 3, 4, 5; `extcap_config` arg 3 |
| `--payload-length 0, 5, 8` | `build_parser`; `extcap_config` arg 4 (range 0 … 64); `len` 1 … 250 |
| `--channels 0-83`, `2`, `11`, `23`, `41`, `42`, `50`, `58`, `66`, `74`, `82`, `23,41` …, `23,41,58,66` | firmware `ch` (0 … 100, ranges `n-m`, ≤ 84 entries, ranges need firmware 1.1) |
| `--dwell 0, 1, 20` | firmware `dwell` 0 … 60000; hop test in `radio.c` uses `k_uptime_get()` (1 ms) |
| `--rate nrf1m`, `ble1m`, `nrf2m` | `build_parser` choices `RATES`; firmware `rate` |
| `--extra-bytes 200` | `build_parser` (0 … 200); `extcap_config` arg 9; total ≤ 250 B (payload 5 + CRC 2 + 200 = 207) |
| device time in `--print` | `run_print` (`t_us / 1e6`), 32-bit from `k_uptime_ticks` in `radio.c` |
| Wireshark display names of section 3.1 | `extcap_config` `display=` strings |
| filters `xn297l.crc_ok`, `xn297l.hdr.rssi`, `xn297l.hdr.freq`, `xn297l.address`, `xn297l.payload_len`, `xn297l.hdr.timestamp` | `wireshark/xn297l.lua` ProtoFields |

Not available and therefore **not used** anywhere above: any transmit command, dwell below 1 ms,
250 kbps, 2 Mbps BLE, several sync words at once, energy detect, a host-clock column, event markers.

---

## 11. Open questions

- **Failsafe behaviour (R2.4):** answered – with the bound handset switched off, the receiver LED
  blinks again after a few seconds; the receiver stays bound and answers the handset's bind
  telegrams again ([MK4.0-Remote.md §1.1](MK4.0-Remote.md#11-led-behaviour)). Only the exact timeout is still open.
- **`RATE*`:** whether `ble1m` reduces the 6 … 10 % CRC errors is decided by session 0. The SCM8
  handset shows almost no CRC errors with `nrf1m`, so the errors are specific to the MK4.0 handsets.
- **Timing assumptions:** the ~30 µs timestamp resolution and the ~100 µs radio ramp-up are assumptions (section 3.2, Q3).
- **Follow-ups:** which of F1 … F7 are worth implementing (F1, F2 and F6 are small and help most).
- **Optional hardware (session 6):** whether extra hardware or opening a device is acceptable if Q1 / Q2 stay open.
