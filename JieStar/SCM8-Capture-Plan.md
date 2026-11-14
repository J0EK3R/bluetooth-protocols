# JIESTAR SCM8 – Capture plan for the original handset

> Purpose: step-by-step measurement guide for the original 2.4 GHz handset of the [JIESTAR SCM8](SCM8.md) with the [XN297L sniffer](../Tools/xn297l-sniffer/README.md) and the [nRF Sniffer for Bluetooth LE](../Tools/nrf-sniffer-ble/README.md) (both on the nRF52840 MDK USB dongle).
> Status: **in progress** – S1, S2 and S4 answered (bind phase: 2411 MHz only), S3, S5 and S6 partly (handset side of the telegram decoded, identity fixed); open: comparison with the 2nd handset H2 and binding (S5, new runs R2.4, R3.7, R3.8), port mapping (S6), device slot (S7), hopping order (S8), receiver response. Results in [SCM8-Remote.md](SCM8-Remote.md). Status per question: section 1, per session: section 3.
> Last updated: 2026-11-14 (results R2.1 … R2.4c – session 2 done; R4.2, R4.5 … R4.7; plan extended for H2)

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

When this plan was written, nothing was known about the SCM8 handset. The app protocol
([SCM8.md](SCM8.md)) is an XN297L frame hidden in BLE advertising on 2402 MHz with address
`C1 … C5`. The first captures (2026-11-13) showed that the handset, like the
[MK4.0 handset](../MouldKing/MK4.0-Remote.md), uses a completely different radio configuration with
the same XN297L frame layer.

| # | Question | Status |
|---|---|---|
| S1 | Does the handset transmit BLE (advertising) or a proprietary 2.4 GHz frame? | **answered:** proprietary – native XN297L frames found directly on 2411 MHz (R1.a); session 0 skipped |
| S2 | Frequency / frequencies, data rate | **answered:** bind 2411 MHz, operation 2416 / 2433 / 2450 / 2469 MHz, 1 Mbps (R1.a, R3.1) |
| S3 | Address (length, on-air bytes), payload length | **partly:** bind `TX_ADDR` `E4834A5834`, operating `TX_ADDR` `E48C545690`, payload 3 / 8 bytes with a 5-byte address (R1.a, R3.1); the address length cannot be decided passively |
| S4 | Is there a bind phase (fixed bind channel / address) and an operation phase (hopping)? | **answered:** yes – bind telegrams every 20.08 ms on 2411 MHz until the receiver is switched on, then hopping over four channels (R1.b, R3.1). On 2411 MHz the handset uses **every** 20.083 ms slot (R2.1); no bind frames on any other channel at 1 Mbps (R2.2). |
| S5 | Handset identity: fixed or generated at power-on; how does the receiver bind? | **partly:** identity is **fixed** – same bind address and payload after 9 power-ons (R2.3); `E4` + `22 5B` appear in both phases. H2 differs in exactly these bytes: `80` + `00 63`, the bind address bytes `83 4A 58 34` are common (R2.4a). Open: operating address of H2 (R3.7) and how the receiver binds (R3.8) |
| S6 | Telegram layout: which byte / nibble is which control, mapping to ports A … H | **mostly answered:** sticks A … D → CH1 … CH4 → ports A … D, buttons E … H → B6 bits → ports E … H, shoulder buttons → B7 bits 0 … 3 (R4.1, R4.2). B7 bits = direction reversal of ports A … D (R4.5). Ring button = drive mode with mixed sticks (R4.6). Open: mixing of A + B together |
| S7 | Does the handset select a device slot (Device 1 … 3 like the app)? | **open:** no Device 1 … 3 marking on the handset; the round button with the ring symbol sets no flag in the telegram; it toggles a drive mode with mixed sticks (R4.6) – **answered:** no device slot |
| S8 | Hopping order and spacing of the four operating channels within the 16.07 ms period | **open** (new question after R4.1; R4.3) |

Writing convention as in the [MK4.0 capture plan](../MouldKing/MK4.0-Capture-Plan.md): only measured
values go into the result document (`SCM8-Remote.md`, created after session 2), interpretations are
marked as such.

---

## 2. Equipment and preparation

| Item | Needed for |
|---|---|
| nRF52840 MDK USB dongle | all sessions |
| firmware **nRF Sniffer for BLE** ([Tools/nrf-sniffer-ble](../Tools/nrf-sniffer-ble/README.md)) | session 0 (skipped, not needed) |
| firmware **XN297L sniffer 1.1** ([Tools/xn297l-sniffer](../Tools/xn297l-sniffer/README.md)) | sessions 1 … 4 |
| SCM8 handset **H1** = the handset measured so far (ID `22 5B`); mark it (sticker) | all sessions |
| 2nd SCM8 handset **H2** (available since 2026-11-14) | R2.4, R3.7, R3.8 |
| SCM8 receiver with battery | sessions 3, 4 |
| motors or LEDs on as many ports A … H as possible | session 4 |
| phone with BrickController2 (SCM8 device configured) | sanity check R1.0 (not run), R3.6 |
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

| Session | Device state | Runs | Questions | Time | Status |
|---|---|---|---|---|---|
| 0 BLE check | handset on, receiver off | R0.1, R0.2 | S1 | 10 min | **skipped** – R1.a found XN297L frames, S1 answered |
| 1 Discovery | handset on, receiver off; then off | R1.0 … R1.4, R1.a, R1.b | S1, S2, S3 | 30 min | **done** – R1.a / R1.b directly on 2411 MHz; the full scan R1.1 … R1.4 and R1.0 were not needed |
| 2 Lock on | handset on, receiver off | R2.1 … R2.5 | S3, S4, S5 | 30 min | **done** – R2.1 … R2.3, R2.4a, R2.4c done, R2.4b not needed, R2.5 answered by R1.b |
| 3 Handset + receiver | receiver on, binding | R3.1 … R3.8 | S4, S5 | 45 min | **partly** – R3.1 done; R3.4 … R3.8 and the LED table open |
| 4 Mapping | receiver bound | R4.1 … R4.4 | S6, S7, S8 | 30 min | **partly** – R4.1, R4.2, R4.5 … R4.7 done; R4.3, R4.4 open |

All runs now have their exact settings. Sessions 0 and 1 are kept for reference and for other
handsets.

---

## 4. Session 0 – Is the handset a BLE device?

Cheap first check: some newer handsets are BLE advertisers. Firmware: **nRF Sniffer for BLE**.

**Status: skipped.** R1.a (section 5.1) received native XN297L frames from the handset, so S1 is
answered without this session.

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

**Status:** R1.0 … R1.4 were not run: the first capture R1.a went straight to the MK4.0 bind
channel 2411 MHz and found the handset (section 5.1).

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
  sends on other channels in between (e.g. alternating every 10 ms) – R2.1 / R2.2 check this.
  **Answered by R2.1:** address mode received 100 % of the slots – the gaps were reception losses
  of the promiscuous mode.
- `22 5B` (or `27 22 5B`, `C1 27 22 5B`) is a candidate for the handset identity; R2.3 / R2.4 check it.
  **Confirmed in R3.1:** the identity byte `E4` and `22 5B` also appear in the operating frames.

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

**Interpretation:** the bind frames end when the SCM8 is switched on; the handset
then leaves 2411 MHz and transmits its control telegrams on other channels (like the MK4.0 handset)
– **confirmed by R3.1** (operating channels 2416 / 2433 / 2450 / 2469 MHz, switch within 230 ms).
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
| R2.4a | **H2 only** on (H1 off): bind address and ID of H2 | `--mode promiscuous --address-length 5 --payload-length 0 --channels 11 --dwell 0 --rate nrf1m` | Promiscuous, Address length 5, Payload `0`, RF channels `11`, Dwell `0` | 60 s |
| R2.4b | only if R2.4a finds nothing: H2 bind channel – **not needed** (R2.4a found H2 on 2411 MHz) | as R2.2, but with RF channels `0-83` | as R2.2, RF channels `0-83` | 120 s |
| R2.4c | **H1 and H2** on at the same time: both bind telegrams side by side (time offset, collisions) | `--mode address --address 834A5834 --channels 11 --dwell 0 --payload-length 0 --rate nrf1m` (4-byte common address: both handsets without the losses of the promiscuous mode; the identity byte then is the first payload byte, H1 `27`, H2 `01`) | Known address, Address `834A5834`, RF channels `11`, Dwell `0`, Payload `0` | 60 s |
| R2.5 | sticks / buttons in the bind phase: does the payload change? | **answered by R1.b** – not needed | – | – |

Expected / interpretation:

- R2.1: ~100 % of the 20 ms slots with valid CRC → the gaps in R1.a were losses of the promiscuous
  mode; again ~50 % → the handset is on 2411 MHz only every other slot (look at R2.2).
- R2.2: frames with address `E4:83:4A:58:34` (or another address) on other channels → bind phase
  uses several channels; nothing → 2411 MHz only.
- R2.3: same address and payload after every power-on → fixed identity (H6a of the MK4.0 plan);
  otherwise generated at power-on.
- R2.4a: compare bind address and payload of H2 with H1 (`E4834A5834` / `22 5B 00`): the bytes that
  differ are the identity; if only the payload differs, the bind address is a common constant.
  R2.4c: two independent 20 ms grids → the handsets do not coordinate (expected).
- R2.5: **answered by R1.b** – the payload stayed `22 5B 00` while all sticks and buttons were
  moved: the bind telegram carries no control values (as MK4.0).

Questions answered: S3, S4 (bind part), S5.

### 6.1 Result R2.1 (2026-11-14)

**Setup:** as in the table (Wireshark, Known address `E4834A5834`, RF channels `11`, Dwell `0`,
Payload `0`, 1 Mbps (nRF)). Handset on, SCM8 receiver off, sticks untouched. Exported as JSON.

**Measured:**

| Item | Value |
|---|---|
| Frames | 2673 in 53.66 s (device time), **2670 with valid CRC** |
| Content | only the bind frame: address `E4834A5834`, payload `22 5B 00` (3 bytes) in all 2670 frames |
| Bad frames | 3 – each a single bit error in the scrambled payload (byte 3 on air `A6` → `86` / `26` / `86`), RSSI −58 / −59 dBm; each sits in the slot where the valid frame is missing |
| Period | **20.083 ms** (linear fit over all slots; std. dev. of the single gaps 61 µs) |
| Received slots | 2673 of 2673 (100 %), 2670 of 2673 with valid CRC (99.9 %); no gap longer than one slot |
| RSSI | −54 … −72 dBm, mean −58 dBm |

**Interpretation:** the handset transmits the bind telegram in **every** 20.083 ms slot on 2411 MHz.
The 46 % in R1.a were losses of the promiscuous mode. So there is no room for an alternating
second bind channel at the same rate – R2.2 can still show transmissions on other channels
*between* the 2411 MHz frames.

### 6.2 Result R2.2 (2026-11-14)

**Setup:** as in the table (Promiscuous, address length 5, Payload `0`, RF channels `0-10,12-83`,
Dwell `50`, 1 Mbps (nRF)). Handset H1 on, SCM8 receiver off. Run time 210 s instead of 120 s.

**Measured:**

| Item | Value |
|---|---|
| Frames | **8** in 210 s, none with valid CRC |
| Channels | 17, 27, 29, 38, 44, 45, 54, 71 – each only once |
| RSSI | −96 … −100 dBm (noise floor) |
| Addresses | all different, random |

**Interpretation:** the 8 hits are noise. With 83 channels × 50 ms one sweep takes 4.15 s, so each
channel was watched for about 2.5 s in total (≈ 125 slots of 20 ms). A bind transmitter on another
channel would have given dozens of frames even with the losses of the promiscuous mode (R1.a: 46 %).
**The bind phase uses 2411 MHz only** (at 1 Mbps).

### 6.3 Result R2.3 (2026-11-14)

**Setup:** as R2.1. Handset switched off for ~5 s and on for ~5 s, repeatedly; SCM8 receiver off.

**Measured:**

| Item | Value |
|---|---|
| Frames | 2019 in 79.9 s (device time), **all with valid CRC** |
| Content | in every on phase only the bind frame: address `E4834A5834`, payload `22 5B 00` |
| On phases | 9 captured (the first one already running at the start), 3.9 … 6.0 s long, each without a missing 20 ms slot |
| Off phases | 8, 4.0 … 7.4 s without any frame |
| Period | 20.083 ms (std. dev. 58 µs), the same as R2.1 |
| RSSI | −52 … −59 dBm |

**Interpretation:** the handset identity (bind address `E4834A5834` and ID `22 5B`) is **fixed** and
not generated at power-on (H6a of the MK4.0 plan). After power-on the handset starts the bind phase
immediately on 2411 MHz with the same values. Which of these bytes differ between handsets needs a
second handset (R2.4).


### 6.4 Result R2.4a (2026-11-14) – 2nd handset H2

**Setup:** Promiscuous, address length 5, Payload `0`, RF channels `11`, Dwell `0`, 1 Mbps (nRF).
**Only H2** on (H1 off), SCM8 receiver off, sticks untouched.

**Measured:**

| Item | H1 (R1.a, R2.1) | H2 (R2.4a) |
|---|---|---|
| Frequency | 2411 MHz | 2411 MHz |
| Address on air (descrambled, MSB first) | `34 58 4A 83 E4` | `34 58 4A 83 80` |
| `TX_ADDR` (5 B) | `E4834A5834` | `80834A5834` |
| Payload (5-byte address) | `22 5B 00` | `00 63 00` |
| Period | 20.083 ms | 20.084 ms (linear fit) |
| Frames | – | 728 in 25.5 s, 727 with valid CRC; 1 noise hit (other address) |
| Received slots (promiscuous) | 46 % (R1.a) | 57 % |
| RSSI | – | −47 … −66 dBm |

**Interpretation:**

- The two handsets differ in exactly the bytes already suspected as identity: the **identity
  byte** (last address byte on air: `E4` / `80`) and the **2-byte ID** (first payload bytes:
  `22 5B` / `00 63`). The bytes `34 58 4A 83` (on air) and the trailing payload byte `00` are
  common – a fixed bind address prefix, as with the MK4.0.
- A relation between identity byte and ID is not visible with two samples
  (`22 ^ 5B` = `79`, `00 ^ 63` = `63`).
- Because the first four address bytes on air are common, the 4-byte address `834A5834` in known
  address mode receives the bind telegrams of **every** handset without the losses of the
  promiscuous mode (used for R2.4c and R3.8).

### 6.5 Result R2.4c (2026-11-14) – H1 and H2 at the same time

**Setup:** run in **promiscuous** mode (address length 5, Payload `0`, RF channels `11`, Dwell `0`,
1 Mbps (nRF)) instead of the planned known address `834A5834` – the losses of the promiscuous mode
do not matter for this question. SCM8 receiver off. H2 was already on at the start, H1 was switched
on at t ≈ 2.5 s.

**Measured:**

| Item | H1 | H2 |
|---|---|---|
| `TX_ADDR` / payload | `E4834A5834` / `22 5B 00` | `80834A5834` / `00 63 00` |
| Frames with valid CRC | 250 (t = 2.5 … 12.5 s) | 293 (t = 0 … 12.5 s) |
| Received slots (promiscuous) | 50 % | 47 % |
| Period | 20.0834 ms | 20.0835 ms |
| RSSI | −54 … −65 dBm | −48 … −55 dBm |

- Other frames: 4 noise hits (−96 … −100 dBm, random addresses, no CRC).
- **Phase offset:** H2 sends 13.92 … 14.05 ms after H1 (i.e. ≈ 6.1 ms before the next H1 frame),
  constant over the 10 s of the run; the closest H1 / H2 frames were 5.98 ms apart.

**Interpretation:** both handsets send on the same channel with the same bind address prefix on
two **independent** 20.083 ms grids; there is no coordination and no reaction of one handset to
the other. The phase offset is set by the power-on time and drifts only with the clock difference
of the two handsets (here < 0.1 µs per period, i.e. too small to measure in 10 s). If the grids met,
the frames would collide; with ~6 ms distance there were no collisions in this run.
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

Status of the further content of this session:

| Item | Status |
|---|---|
| receiver off → handset on → receiver on: does the handset change frequency, address or payload? | **answered** (R1.b, R3.1): bind phase on 2411 MHz with bind address and 3-byte payload → operation on four channels with operating address and 8-byte payload, switch within 230 ms |
| LED behaviour of handset and receiver | **open** – fill in the table of section 9 (the [MK4.0 table](../MouldKing/MK4.0-Remote.md#11-led-behaviour) is the template) |
| receiver off while the handset stays on: does the handset notice it (back channel)? | **open** – R3.4 |
| what does the receiver send to end the bind phase? | **open** – R3.5 |
| does the SCM8 lock into handset or app mode after power-on (like the MK4.0)? | **open** – R3.6 |
| several handsets: who binds to whom? | **open** – R3.8 with H1 and H2 |
| operating address and channels of a 2nd handset | **open** – R3.7 with H2 |

Further runs (receiver bound to the handset unless stated otherwise):

| Run | Purpose | Options | Wireshark | Duration |
|---|---|---|---|---|
| R3.4a | handset bound and running; switch the SCM8 **off** after ~20 s, leave the handset on: does the handset return to the bind phase? | `--mode address --address E4834A5834 --channels 11 --dwell 0 --payload-length 0 --rate nrf1m` | Known address, Address `E4834A5834`, RF channels `11`, Dwell `0`, Payload `0` | 60 s |
| R3.4b | same sequence, observing the operation instead: do the control frames continue? | `--mode address --address E48C545690 --channels 16 --dwell 0 --payload-length 8 --rate nrf1m` | Known address, Address `E48C545690`, RF channels `16`, Dwell `0`, Payload `8` | 60 s |
| R3.5 | receiver response: SCM8 on and bound, switch the **handset** off for 5 s and on again, 10× | `--mode promiscuous --address-length 5 --payload-length 0 --channels 11 --dwell 0 --rate nrf1m` (then the same with `--rate nrf2m` and `--rate ble1m`) | Promiscuous, Address length 5, Payload `0`, RF channels `11`, Dwell `0` | 3 × 2 min |
| R3.6 | handset vs. app: power the SCM8 with the handset already on and BrickController2 already sending; 5 trials; note which source controls the ports | as R3.4b (shows whether the handset leaves its bind phase) | as R3.4b | 5 × 1 min |
| R3.7 | **H2** bound to the SCM8 (H1 off): operating channels and operating address of H2; move one stick during the whole run | as R3.1 | as R3.1 | 120 s |
| R3.8a | H1 and H2 on, SCM8 off → switch the SCM8 on: which handset is bound? 5 trials, alternately H1 / H2 switched on first; note which handset controls the ports | as R2.4c (the bind frames of the bound handset stop, the other one keeps sending) | as R2.4c | 5 × 30 s |
| R3.8b | SCM8 bound to H1, H2 in the bind phase: switch **H1** off – does the SCM8 take H2 (H2 bind frames stop)? | as R2.4c | as R2.4c | 60 s |
| R3.8c | SCM8 was last bound to H1; everything off. Switch on **only H2**, then the SCM8: does it bind to H2 (pairing memory)? Then the same with H1 only | as R2.4c | as R2.4c | 2 × 30 s |

Interpretation:

- R3.4a: bind frames reappear → the handset notices the missing receiver (back channel in
  operation); nothing → one-way link in operation, as with the MK4.0 (interpretation of its LED
  behaviour). R3.4b: control frames continue after the SCM8 is off → the handset does not notice.
- R3.5: any frame with an address other than `E4834A5834` → candidate for the receiver's answer
  (note time relative to the last bind frame). Nothing → the answer uses another channel, another
  data rate (250 kbps cannot be received) or no XN297L framing – same situation as the MK4.0
  ([MK4.0 plan Q1](../MouldKing/MK4.0-Capture-Plan.md#q1--receiver-response-during-binding)).
- R3.6: the source that wins in all trials (or the first one, if the order is varied) shows whether
  the SCM8 locks into one mode like the MK4.0.
- R3.7: compare with H1 (channels 2416 / 2433 / 2450 / 2469 MHz, `E48C545690`): same channels and
  address → only the payload ID separates the handsets; different values → channels and / or
  address derived from the identity (compare with the bind address of H2 from R2.4a). Prediction by analogy with H1: operating
  address `808C545690`, payload starting with `00 63`.
- R3.8a: always the handset switched on first → "first come"; always the same → preference /
  memory. R3.8b: H2 bind frames stop → the SCM8 rebinds during operation. R3.8c: H2 stays in the
  bind phase → the SCM8 stores the bound handset.

---

## 8. Session 4 – Channel mapping

Settings (from R3.1): SCM8 bound to the handset, a motor or LED on as many ports A … H as possible.

| Run | Options | Wireshark | Duration |
|---|---|---|---|
| R4.1 | `--mode address --address E48C545690 --channels 16 --dwell 0 --payload-length 8 --rate nrf1m` | Known address, Address `E48C545690`, RF channels `16`, Dwell `0`, Payload `8`, 1 Mbps (nRF) | ~5 min |

Channel `16` = 2416 MHz (sniffer channel = MHz − 2400); the four operating channels are
`16`, `33`, `50`, `69` = 2416, 2433, 2450, 2469 MHz. With `--dwell 0` the sniffer stays on one
channel and receives every pass of the handset's hopping sequence, see
[SCM8-Remote.md §8](SCM8-Remote.md#8-capturing-with-the-xn297l-sniffer).
One channel is enough if all four channels carry the same payload (confirmed in R4.3).

**Result R4.1 (2026-11-13):** handset side done – 4 proportional axes CH1 … CH4, 8 momentary
buttons (B6 bits), 4 latching states (B7 bits), see [SCM8-Remote.md §5](SCM8-Remote.md#5-control-telegram-8-bytes).
Still missing: which physical control sets which byte / bit, and the port reaction (A … H).
The handset photos ([SCM8-Remote.md, Handset](SCM8-Remote.md#handset)) show the printed control
names: sticks **A** / **B** (left) and **C** / **D** (right), button groups **E**, **F**, **G**,
**H** (two buttons each), four shoulder buttons, a round button with a ring symbol.

Further runs:

| Run | Purpose | Options | Duration |
|---|---|---|---|
| R4.2 | mapping controls → bytes / bits → ports A … H, and device slot (S7) | as R4.1 | ~5 min |
| R4.3a – f | hopping order (S8): channel pairs `16,33` `16,50` `16,69` `33,50` `33,69` `50,69`, sticks neutral | `--mode address --address E48C545690 --channels 16,33 --dwell 1 --payload-length 8 --rate nrf1m` (and the other five pairs) | 60 s each |
| R4.3g | all four channels carry the same payload: move one stick slowly | `--mode address --address E48C545690 --channels 16,33,50,69 --dwell 1 --payload-length 8 --rate nrf1m` | 60 s |
| R4.4 | B7 over a power cycle: note B7, switch the handset off and on (receiver stays on), 5× | as R4.1 | ~2 min |

**R4.2 procedure** as in the
[MK4.0 plan Q4](../MouldKing/MK4.0-Capture-Plan.md#q4--channel-mapping-ch1--ch6---controls---ports-a--d):
each control is moved and held for 3 s, 3 s neutral in between, in a fixed order written down with
its number (stick A up / down, B left / right, C, D; buttons E, F, G, H, each of the two; the four
shoulder buttons; the round button). Per action note which payload byte changes (CH1 … CH4, B6, B7)
and which port (A … H) reacts. Expected (interpretation from the photos): sticks A … D → CH1 … CH4
→ ports A … D; buttons E … H → B6 bits → ports E … H (two directions each); shoulder buttons → B7 bits.
Watch whether a B7 bit switches the sticks to other ports and whether the round button changes the
address or a payload byte (Device 1 … 3, S7).

**R4.3 analysis** as in the
[MK4.0 plan Q3](../MouldKing/MK4.0-Capture-Plan.md#q3--hopping-order-and-dwell-time): for each frame
on channel a take the next frame on channel b; the delay histogram peaks at the phase offset of b
relative to a within the 16.07 ms period. Sorting the offsets gives the order: one frame every
~4 ms rotating over the channels, or a burst over all four channels per period.

| R4.5 | function of the B7 bits / stick mixing: start with B7 = `00` if possible (toggle the set bits off); then set **one** shoulder button at a time, move stick A up and B left in each state, note which ports react; finally press the ring button and repeat | as R4.1 | ~5 min |
| R4.6 | ring button / stick mixing: sticks neutral, press the ring button; move each stick axis (A up / down, B left / right, C, D) for 3 s each and note the ports; press the ring button again and repeat | as R4.1 | ~3 min |
| R4.7 | drive mode on: sticks A … D up / down, buttons E … H, repeated in several B7 states | as R4.1 | ~2.5 min |

**R4.4:** B7 unchanged after power-on → the latching states are stored in the handset; always the
same start value → reset at power-on. Start values seen so far: `0F` (R3.1), `04` (R4.1), `01` (R4.2).

**Result R4.2 (2026-11-14):** 6380 frames with valid CRC in 102.6 s on 2416 MHz (99.9 % of the
slots). Every control drives the port with its own letter; full table, stick mixing with B7 =
`0B` / `0F` and the missing frame at each B7 toggle in
[SCM8-Remote.md §5.3](SCM8-Remote.md#53-mapping-controls--bytes--ports-r42). Ring button: no
change in the telegram.

**Result R4.5 (2026-11-14):** 6460 frames with valid CRC in 103.9 s. Start B7 = `00`; each shoulder
button set / cleared one bit (`01`, `02`, `04`, `08`), the stick values stayed unchanged; reported:
the shoulder buttons reverse the direction of ports A … D. After the ring button (B7 = `00`) the
handset sent mixed stick values → the ring button, not B7, switches the mixing. Again one missing
frame at every B7 change (8 of 8).

**Result R4.6 (2026-11-14):** 2107 frames, all with valid CRC, 33.8 s, no missing frame. Stick A
only: before the ring button CH1 alone; after it CH1 = CH2 = A and CH3 = CH4 = `FF` − A; reported:
all ports A … D run. See [SCM8-Remote.md §5.3](SCM8-Remote.md#53-mapping-controls--bytes--ports-r42).

**Result R4.7 (2026-11-14):** 8825 frames with valid CRC in 142 s. In drive mode stick C gives the
same values as A and D the same as B; B7 (`00`, `01`, `03`, `07`, `0B`) does not change the values;
buttons E … H unchanged. One more unintended B7 bit 2 toggle while stick C was up (3rd time).

---

## 9. Recording the results

**Session 0 – BLE check**

| Run | New BLE device? | Address / name | RSSI | Data changes with sticks? |
|---|---|---|---|---|
| R0.2 | not run (session 0 skipped) | | | |

**Session 1 – frames found**

| Run | Channel (MHz) | Rate | Address | Length | Payload (example) | RSSI | CRC ok / bad | Remark |
|---|---|---|---|---|---|---|---|---|
| R1.0 | 2402 | ble1m | `C1C2C3C4C5` | | | | | app sanity check – not run (not needed) |
| R1.a | 2411 | nrf1m | `E4834A5834` (5 B) | 3 | `22 5B 00` | −47 … −84 | 197 / 3 | channel 11 only, receiver off, 20.08 ms grid, 46 % of slots received |
| R1.b | 2411 | nrf1m | `E4834A5834` (5 B) | 3 | `22 5B 00` | −51 … −62 | 155 / 2 | channel 11 only, SCM8 switched on during the run; bind frames stop after 6.89 s, nothing afterwards |
| R3.1 | 2416 / 2433 / 2450 / 2469 | nrf1m | `E48C545690` (5 B) | 8 | `22 5B 80 80 80 80 00 04` | −53 … −69 | 44 / 5 | SCM8 bound, scan `0-83` dwell 50; 5 bad = noise |
| R4.1 | 2416 | nrf1m | `E48C545690` (5 B) | 8 | `22 5B 80 80 80 80 00 04` | −50 … −82 | 9444 / 7 | address mode, 152 s, 16.07 ms per frame; all sticks, 8 buttons (B6), 4 toggle bits (B7) |
| R1.2 | | nrf1m | | | | | | not run (handset found by R1.a) |
| R1.3 | | nrf2m | | | | | | not run (handset found by R1.a) |
| R1.4 | | ble1m | | | | | | not run (handset found by R1.a) |

**Sessions 2 … 4 – open runs**

| Run | Result |
|---|---|
| R2.1 | 2673 frames / 53.7 s, 2670 CRC ok (3 × 1-bit errors), 100 % of the 20.083 ms slots on 2411 MHz, payload always `22 5B 00` → gaps in R1.a were promiscuous losses (section 6.1) |
| R2.2 | 210 s over channels 0 … 10, 12 … 83: only 8 noise hits (−96 … −100 dBm, no CRC) → bind phase on 2411 MHz only (section 6.2) |
| R2.3 | 9 power-ons captured (8 off phases of 4.0 … 7.4 s), 2019 frames, all CRC ok, always `E4834A5834` / `22 5B 00` → identity fixed (section 6.3) |
| R2.4a (H2) | 727 frames CRC ok on 2411 MHz: `TX_ADDR` `80834A5834`, payload `00 63 00` → H2 differs from H1 only in identity byte and ID (section 6.4) |
| R2.4b | not needed |
| R2.4c | H1 and H2 on two independent 20.083 ms grids on 2411 MHz, phase offset constant ≈ 14 ms, no collisions (section 6.5) |
| R3.4a / b | |
| R3.5 | |
| R3.6 | |
| R3.7 (H2) | |
| R3.8a … c | |
| R4.2 | sticks A … D → CH1 … CH4 → ports A … D, E … H → B6 bits → ports E … H, shoulder → B7 bits 0 … 3; with B7 = `0B` / `0F` the handset mixes the sticks; ring button no change |
| R4.5 | B7 bits 0 … 3 = direction reversal of ports A … D (done in the receiver); stick mixing appears after the ring button with B7 = `00`; 1 missing frame per B7 change |
| R4.7 | drive mode: C = A, D = B; B7 does not change the values; E … H unchanged; bit 2 toggled again with stick C up |
| R4.6 | ring button toggles a drive mode: stick A → CH1 = CH2 = A, CH3 = CH4 = `FF` − A, ports A … D run; no flag in the telegram |
| R4.3 | |
| R4.4 | |

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

- Which radio chip is in the handset and in the receiver? No longer needed for capturing (the
  handset sends XN297L-compatible frames at 1 Mbps); only relevant if the receiver's answer (R3.5)
  turns out to be invisible to the nRF52840 (250 kbps or other framing).
- Does the SCM8 receiver accept handset and app at the same time, or does it lock into the first
  source after power-on like the MK4.0? (R3.6)
- Is the SCM8 handset the same as the SCM4 handset (same frames, other channel count)?
- Does the handset return to the bind phase when the SCM8 is switched off? (R3.4)
- Are the B7 latching states kept over a power cycle of the handset? (R4.4)
