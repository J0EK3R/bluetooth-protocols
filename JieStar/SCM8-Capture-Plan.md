# JIESTAR SCM8 – Capture plan for the original handset

> Purpose: step-by-step measurement guide for the original 2.4 GHz handset of the [JIESTAR SCM8](SCM8.md) with the [XN297L sniffer](../Tools/xn297l-sniffer/README.md) and the [nRF Sniffer for Bluetooth LE](../Tools/nrf-sniffer-ble/README.md) (both on the nRF52840 MDK USB dongle).
> Status: **in progress** – bind phase (R1.a, R1.b) and operating channels (R3.1) found; results in [SCM8-Remote.md](SCM8-Remote.md). Sessions 2 and 4 are still open.
> Last updated: 2026-11-13 (result of R4.1)

## Contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Equipment and preparation](#2-equipment-and-preparation)
3. [Session order](#3-session-order)
4. [Session 0 – Is the handset a BLE device?](#4-session-0--is-the-handset-a-ble-device)
5. [Session 1 – Find the handset (XN297L discovery)](#5-session-1--find-the-handset-xn297l-discovery)
6. [Session 2 – Lock onto the handset](#6-session-2--lock-onto-the-handset)
7. [Session 3 – Handset + receiver](#7-session-3--handset--receiver)
8. [Session 4 – Channel mapping](#8-session-4--channel-mapping)
9. [Recording the results](#9-recording-the-results)
10. [Open questions](#10-open-questions)

---

## 1. Purpose and scope

Unlike the [MK4.0 handset](../MouldKing/MK4.0-Remote.md), **nothing is known** about the SCM8 handset yet.
The app protocol ([SCM8.md](SCM8.md)) is an XN297L frame hidden in BLE advertising on 2402 MHz with
address `C1 … C5`; the handset may use a completely different radio configuration (as the MK4.0
handset does) or even a different chip.

| # | Question |
|---|---|
| S1 | Does the handset transmit BLE (advertising) or a proprietary 2.4 GHz frame? |
| S2 | Frequency / frequencies, data rate |
| S3 | Address (length, on-air bytes), payload length |
| S4 | Is there a bind phase (fixed bind channel / address) and an operation phase (hopping)? |
| S5 | Handset identity: fixed or generated at power-on; how does the receiver bind? |
| S6 | Telegram layout: which byte / nibble is which control, mapping to ports A … H |
| S7 | Does the handset select a device slot (Device 1 … 3 like the app)? |

Writing convention as in the [MK4.0 capture plan](../MouldKing/MK4.0-Capture-Plan.md): only measured
values go into the result document (`SCM8-Remote.md`, created after session 2), interpretations are
marked as such.

---

## 2. Equipment and preparation

| Item | Needed for |
|---|---|
| nRF52840 MDK USB dongle | all sessions |
| firmware **nRF Sniffer for BLE** ([Tools/nrf-sniffer-ble](../Tools/nrf-sniffer-ble/README.md)) | session 0 |
| firmware **XN297L sniffer 1.1** ([Tools/xn297l-sniffer](../Tools/xn297l-sniffer/README.md)) | sessions 1 … 4 |
| SCM8 handset (if there are several: note a label for each, H1, H2, …) | all sessions |
| SCM8 receiver with battery | sessions 3, 4 |
| motors or LEDs on as many ports A … H as possible | session 4 |
| phone with BrickController2 (SCM8 device configured) | sanity check R1.0 |
| PC with Wireshark (extcap) or Python 3 + `pyserial` for `--print` | all sessions |

Flashing: double-click the dongle button (LED green, UF2 drive appears), copy the `.uf2` of the
firmware the session needs.

Console command (run from the repository root, replace `<PORT>`, e.g. `COM5`):

```bash
SNIFF="python -u Tools/xn297l-sniffer/extcap/xn297l_sniffer.py --print --show-bad --port <PORT>"
# each run: $SNIFF <options> | tee R<run>.log
```

In Wireshark use the same values in the extcap dialog (Sync mode, Address, Address length, Payload
length, RF channels, Dwell time, Data rate, Extra bytes). For every run note what you did and when
(the log has device time only). Raw logs / `.pcapng` / JSON exports are **not** committed; send them
to me for the analysis.

Hints: dongle 0.5 … 1 m from the handset; switch 2.4 GHz Wi-Fi off for the session if possible (or
at least keep it in the same state); keep each run below 70 minutes (device time wraps after 71.6 min).

---

## 3. Session order

| Session | Device state | Runs | Questions | Time |
|---|---|---|---|---|
| 0 BLE check | handset on, receiver off | R0.1, R0.2 | S1 | 10 min |
| 1 Discovery | handset on, receiver off; then off | R1.0 … R1.4 | S1, S2, S3 | 30 min |
| 2 Lock on | handset on, receiver off | R2.x (depends on session 1) | S3, S4, S5 | 30 min |
| 3 Handset + receiver | receiver on, binding | R3.x | S4, S5 | 30 min |
| 4 Mapping | receiver bound | R4.1 | S6, S7 | 20 min |

**Sessions 0 and 1 are fully specified below. Sessions 2 … 4 get their exact settings once session 1
has found the frequency and data rate** (address, channels and payload length are filled in then).

---

## 4. Session 0 – Is the handset a BLE device?

Cheap first check: some newer handsets are BLE advertisers. Firmware: **nRF Sniffer for BLE**.

| Run | State | Wireshark | Duration |
|---|---|---|---|
| R0.1 | everything off (reference: which BLE devices are around) | interface *nRF Sniffer for Bluetooth LE*, all advertising devices | 30 s |
| R0.2 | handset **on**, receiver off; move all sticks and press all buttons once | same | 60 s |

Filter for new advertisers: `btle.advertising_header && btle.rssi > -60` (dongle close to the
handset). Compare the device list of R0.1 and R0.2.

| Observation | Meaning |
|---|---|
| a new device appears in R0.2 with strong RSSI and changing data when sticks move | **S1 = BLE**: export R0.2 as JSON, sessions 1 … 4 are replaced by a BLE plan |
| nothing new | handset is not BLE → session 1 (XN297L) |

---

## 5. Session 1 – Find the handset (XN297L discovery)

Firmware: **XN297L sniffer**. Receiver off, so the handset stays in a possible bind phase (as with the MK4.0).

### R1.0 – Sanity check with the app (known transmitter)

Proves that the sniffer works with the known SCM8 app frame before searching the unknown handset.
In BrickController2 connect an SCM8 device and move one control.

| Run | Options | Duration |
|---|---|---|
| R1.0 | `--mode address --address C1C2C3C4C5 --channels 2 --dwell 0 --payload-length 0 --rate ble1m` | 30 s |

Expected: frames with `CRC ok` on 2402 MHz (Connect `A4 … 00 00 00 00 5B`, then Command `41 …`
(Device 1)). Wireshark: Sync mode *Known address*, Address `C1C2C3C4C5`, RF channels `2`,
Dwell `0`, Data rate *1 Mbps (BLE)*. Close the app afterwards (phone Bluetooth off).

### R1.1 … R1.4 – Channel scan

Promiscuous mode searches the XN297L preamble `71 0F 55` on every channel. A full sweep of 84
channels at 50 ms takes 4.2 s; 120 s give about 28 sweeps.

| Run | State | Options | Duration |
|---|---|---|---|
| R1.1 reference | everything off | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 50 --rate nrf1m` | 120 s |
| R1.2 | handset **on** (just switched on), receiver off | same as R1.1 | 120 s |
| R1.3 | handset on | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 50 --rate nrf2m` | 120 s |
| R1.4 | handset on | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 50 --rate ble1m` | 120 s |

During R1.2 … R1.4: switch the handset off and on twice (every ~40 s), so that a possible bind phase
is captured several times. Note if the handset LED blinks or is constant.

Wireshark filters:

```
xn297l.crc_ok == 1
xn297l.hdr.rssi > -85
```

**Expected result / interpretation**

| Observation | Meaning | Next step |
|---|---|---|
| frames with `CRC ok` and RSSI > −85 dBm in R1.2 (or R1.3 / R1.4), not in R1.1 | handset found: frequency, rate, address, payload length | session 2 with these values |
| strong repeating hits (> −70 dBm) on one channel, always CRC bad | transmitter present, framing does not match: try `--address-length 3` and `4`, the other rates, `--no-scramble` on that single channel | repeat on that channel only |
| hits only on 2–3 neighbouring channels, CRC bad | weak copies of a strong transmitter (seen with the MK4.0) – take the strongest channel | as above |
| nothing in all three rates | 250 kbps, non-XN297L chip, or a different preamble | see section 10: open the handset and identify the radio chip |

### 5.1 Result of the first capture R1.a (2026-11-13)

Instead of the full scan, the first capture was taken directly on the MK4.0 bind channel – and hit.

**Setup:** promiscuous, address length 5, payload length 5, channel `11` (2411 MHz) only, `nrf1m`,
about 150 extra bytes. Handset switched on, SCM8 receiver **off**, sticks untouched. 200 frames in 10.7 s.

**Measured:**

| Item | Value |
|---|---|
| Frequency | **2411 MHz** (the only channel observed) |
| Data rate | 1 Mbps (`nrf1m`) |
| Framing | XN297L: preamble `71 0F 55`, scrambler on, CRC-16, normal mode (no PCF) |
| Valid CRC | 197 of 200 frames; the 3 bad ones: 1 bit error at −69 dBm, 2 noise hits at −98 / −99 dBm |
| Address + payload | **8 bytes** in total before the CRC (address/payload split see below) |
| Address on air (descrambled, MSB first) | `34 58 4A 83 E4` |
| `TX_ADDR` (5 B, for `--address`) | `E4834A5834` |
| Payload with 5-byte address | `22 5B 00` (3 bytes), **identical in all 197 frames** |
| Payload with 4-byte address | `27 22 5B 00` (4 bytes) |
| Payload with 3-byte address | `C1 27 22 5B 00` (5 bytes) |
| Timing | frames on a fixed **20.08 ms** grid (std. dev. 85 µs); gaps are exact multiples of 20 ms (20 ms: 99×, 40 ms: 38×, 60 ms: 27×, …) |
| Received share | 197 frames in 8.58 s ≈ 46 % of the 20 ms slots |
| RSSI | −47 … −84 dBm (changed during the capture, handset was probably moved) |

**Interpretation (not verified):**

- This is most likely the **bind phase** (receiver off), as with the MK4.0: same channel 2411 MHz,
  same data rate, same XN297L framing, constant short payload. The address differs from the MK4.0
  bind address (`48 44 4B 03` + identity).
- As with the MK4.0, the address length cannot be decided passively: 3, 4 and 5 bytes all give a
  valid CRC. With a 3-byte address the payload is 5 bytes like the MK4.0 bind telegram.
- The ~54 % missing slots are either reception losses of the promiscuous mode, or the handset
  sends on other channels in between (e.g. alternating every 10 ms) – R2.2 checks this.
- `22 5B` (or `27 22 5B`, `C1 27 22 5B`) is a candidate for the handset identity; R2.3 / R2.4 check it.

### 5.2 Result of capture R1.b (2026-11-13)

**Setup:** same sniffer settings as R1.a (promiscuous, channel `11` only, `nrf1m`). Sequence:
handset on → SCM8 on → all sticks and buttons moved → SCM8 off → handset off.

**Measured:**

| Item | Value |
|---|---|
| Frames | 157 in 6.89 s (device time), 155 with valid CRC, 2 bad (1 noise hit at −98 dBm, 1 bit error) |
| Content | **only** the bind frame of R1.a: address `E4834A5834`, payload `22 5B 00`, 20 ms grid |
| End | the bind frames stop at t = 6.89 s; **no frame at all** on 2411 MHz afterwards |
| Payload changes | none (no stick values on 2411 MHz) |
| Other addresses | none |

**Interpretation (not verified):** the bind frames end when the SCM8 is switched on; the handset
then leaves 2411 MHz and transmits its control telegrams on other channels (like the MK4.0 handset).
No frame of the receiver was seen on 2411 MHz. If the capture was still running when the SCM8 was
switched off again, the handset did **not** return to the bind phase – to be confirmed (duration of
the capture).

---

## 6. Session 2 – Lock onto the handset

Values from R1.a (section 5.1). Handset on, SCM8 receiver **off**, sticks untouched.

| Run | Purpose | Options | Wireshark | Duration |
|---|---|---|---|---|
| R2.1 | robust capture in address mode: share of received slots compared with R1.a (46 %) | `--mode address --address E4834A5834 --channels 11 --dwell 0 --payload-length 0 --rate nrf1m` | Known address, Address `E4834A5834`, RF channels `11`, Dwell `0`, Payload `0` | 60 s |
| R2.2 | does the handset also send on other channels in the bind phase? | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-10,12-83 --dwell 50 --rate nrf1m` | Promiscuous, Address length 5, Payload `0`, RF channels `0-10,12-83`, Dwell `50` | 120 s |
| R2.3 | identity fixed? handset off 5 s / on 5 s, 10× | as R2.1 | as R2.1 | ~2 min |
| R2.4 | 2nd handset (only if available) | `--mode address --address 834A5834 --channels 11 --dwell 0 --payload-length 0 --rate nrf1m` (4-byte address: both handsets in one log, if they share it) | Known address, Address `834A5834`, rest as R2.1 | 60 s |
| R2.5 | sticks / buttons in the bind phase: does the payload change? | as R2.1, move every control once | as R2.1 | 60 s |

Expected / interpretation:

- R2.1: ~100 % of the 20 ms slots with valid CRC → the gaps in R1.a were losses of the promiscuous
  mode; again ~50 % → the handset is on 2411 MHz only every other slot (look at R2.2).
- R2.2: frames with address `E4:83:4A:58:34` (or another address) on other channels → bind phase
  uses several channels; nothing → 2411 MHz only.
- R2.3: same address and payload after every power-on → fixed identity (H6a of the MK4.0 plan);
  otherwise generated at power-on.
- R2.4: which bytes differ between two handsets decides which bytes are the identity.
- R2.5: payload stays `22 5B 00` → the bind telegram carries no control values (as MK4.0).

Questions answered: S3, S4 (bind part), S5.

---

## 7. Session 3 – Handset + receiver

**First step (after R1.b): find the operating channels.** Bind the SCM8 first (handset on, then
SCM8 on, wait until the LEDs are constant), **then** start the capture; move one stick back and forth
during the whole run so that the frames change.

| Run | Purpose | Options | Wireshark | Duration |
|---|---|---|---|---|
| R3.1 | operating channels at 1 Mbps | `--mode promiscuous --address-length 5 --payload-length 0 --channels 0-83 --dwell 50 --rate nrf1m` | Promiscuous, Address length 5, Payload `0`, RF channels `0-83`, Dwell `50`, 1 Mbps (nRF) | 120 s |
| R3.2 | only if R3.1 finds nothing: 2 Mbps | as R3.1 with `--rate nrf2m` | Data rate 2 Mbps | 120 s |
| R3.3 | only if R3.1 and R3.2 find nothing | as R3.1 with `--rate ble1m` | Data rate 1 Mbps (BLE) | 120 s |

Expected: frames with valid CRC on a few channels (strongest RSSI), a new or the same address, a
longer payload whose bytes follow the stick. These channels then go into a single-channel run in
address mode for the mapping (section 8).

**Result R3.1 (2026-11-13):** found with `nrf1m`, R3.2 / R3.3 not needed. Operating channels
**2416 / 2433 / 2450 / 2469 MHz**, operating address `E48C545690`, 8-byte control telegram
`22 5B CH1 CH2 CH3 CH4 B6 B7`. 44 of 49 frames with valid CRC (the 5 others: noise at −99 … −101 dBm).
Details in [SCM8-Remote.md](SCM8-Remote.md).

Further content of this session:

- receiver off → handset on → receiver on: does the handset change frequency, address or payload (bind → operation, as with the MK4.0)?
- note LED behaviour of handset and receiver in the table of section 9 (the [MK4.0 table](../MouldKing/MK4.0-Remote.md#11-led-behaviour) is the template);
- receiver off while handset stays on: does the handset notice it (back channel)?
- several receivers / several handsets: who binds to whom?

---

## 8. Session 4 – Channel mapping

Settings (from R3.1): SCM8 bound to the handset, a motor or LED on as many ports A … H as possible.

| Run | Options | Wireshark | Duration |
|---|---|---|---|
| R4.1 | `--mode address --address E48C545690 --channels 16 --dwell 0 --payload-length 8 --rate nrf1m` | Known address, Address `E48C545690`, RF channels `16`, Dwell `0`, Payload `8`, 1 Mbps (nRF) | ~5 min |

One channel is enough if all four channels carry the same payload (to be confirmed once with
`--channels 16,33,50,69 --dwell 1` while moving one stick).

**Result R4.1 (2026-11-13):** handset side done – 4 proportional axes CH1 … CH4, 8 momentary
buttons (B6 bits), 4 latching states (B7 bits), see [SCM8-Remote.md §5](SCM8-Remote.md#5-control-telegram-8-bytes).
Still missing: names of the physical controls and the port reaction (A … H).

Procedure as in the
[MK4.0 plan Q4](../MouldKing/MK4.0-Capture-Plan.md#q4--channel-mapping-ch1--ch6---controls---ports-a--d):
each control is moved and held for 3 s, 3 s neutral in between, in a fixed order written down with
its number; per action note which payload byte changes (CH1 … CH4, B6, B7) and which port
(A … H) reacts. Watch especially for the button that changes **B7** (`0F` ↔ `04` in R3.1) and
whether it switches the sticks to other ports (E … H).
Additionally: is there a switch or button on the handset that selects Device 1 … 3 (S7), and does
it change the address or a byte in the payload?

---

## 9. Recording the results

**Session 0 – BLE check**

| Run | New BLE device? | Address / name | RSSI | Data changes with sticks? |
|---|---|---|---|---|
| R0.2 | | | | |

**Session 1 – frames found**

| Run | Channel (MHz) | Rate | Address | Length | Payload (example) | RSSI | CRC ok / bad | Remark |
|---|---|---|---|---|---|---|---|---|
| R1.0 | 2402 | ble1m | `C1C2C3C4C5` | | | | | app sanity check |
| R1.a | 2411 | nrf1m | `E4834A5834` (5 B) | 3 | `22 5B 00` | −47 … −84 | 197 / 3 | channel 11 only, receiver off, 20.08 ms grid, 46 % of slots received |
| R1.b | 2411 | nrf1m | `E4834A5834` (5 B) | 3 | `22 5B 00` | −51 … −62 | 155 / 2 | channel 11 only, SCM8 switched on during the run; bind frames stop after 6.89 s, nothing afterwards |
| R3.1 | 2416 / 2433 / 2450 / 2469 | nrf1m | `E48C545690` (5 B) | 8 | `22 5B 80 80 80 80 00 04` | −53 … −69 | 44 / 5 | SCM8 bound, scan `0-83` dwell 50; 5 bad = noise |
| R4.1 | 2416 | nrf1m | `E48C545690` (5 B) | 8 | `22 5B 80 80 80 80 00 04` | −50 … −82 | 9444 / 7 | address mode, 152 s, 16.07 ms per frame; all sticks, 8 buttons (B6), 4 toggle bits (B7) |
| R1.2 | | nrf1m | | | | | | |
| R1.3 | | nrf2m | | | | | | |
| R1.4 | | ble1m | | | | | | |

**LED behaviour** (session 3)

| Situation | Handset LED | Receiver LED |
|---|---|---|
| handset on, no receiver | | – |
| receiver switched on | | |
| handset switched off | – | |
| handset switched on again | | |
| receiver switched off | | – |

---

## 10. Open questions

- Which radio chip is in the handset and in the receiver? If session 1 finds nothing, photos of
  both boards (chip markings) decide the next tool (nRF24L01+ module or SDR for 250 kbps / other framing).
- Does the SCM8 receiver accept handset and app at the same time, or does it lock into the first
  source after power-on like the MK4.0?
- Is the SCM8 handset the same as the SCM4 handset (same frames, other channel count)?
