# Mould King MK4.0 – Original 2.4 GHz Remote Control

> Source: own captures with the [XN297L sniffer](../Tools/xn297l-sniffer/README.md) (nRF52840 dongle), three MK4.0 handsets and one MK4.0 receiver, 2026-11-11.
> All values in this document are **measured**; interpretations are marked as such.
> Last updated: 2026-11-11 (link to capture plan)

## Overview

| Property | Value |
|---|---|
| Device | original 2.4 GHz handset of the Mould King MK4.0 receiver ([MK4.0](MK4.0.md)) |
| Radio | XN297L-compatible frame: preamble `71 0F 55`, scrambler on, CRC-16, normal mode (no PCF) |
| Data rate | 1 Mbps (received with the nRF52840 in `Nrf_1Mbit` mode) |
| Bind channel | **2411 MHz**, fixed |
| Operating channels | **2423, 2441, 2458, 2466 MHz** (frequency hopping), identical for all handsets |
| Handset identity | 3 bytes per handset (identity byte + 2-byte ID), see section 3 |
| Bind telegram | 5 bytes: ID + `00 00 00` |
| Control telegram | 8 bytes: ID + 6 channels, **one byte per channel** |
| Devices per handset | 1 (the handset controls exactly one receiver) |

The handset uses a completely different radio configuration than the app (BLE advertising, see
[MK4.0 §5](MK4.0.md#5-encoding-into-ble-advertising-data)): different frequencies, a different
address and a different telegram format. Only the XN297L frame layer (preamble, scrambler, CRC) is the same.

---

## 1. Sequence

```
Handset switched on (no bound receiver)
        │
        ▼
 Bind phase: Bind telegram on 2411 MHz, bind address    ← repeated every ~14 ms
        │
        │   receiver switched on → receiver accepts this handset
        ▼
 Operation: Control telegrams, operating address,
            hopping over 2423 / 2441 / 2458 / 2466 MHz
```

- Without a receiver, the handset stays in the bind phase (observed for more than 30 s).
- As soon as the MK4.0 receiver is switched on, the handset changes to operation. Because the
  handset changes its behaviour, the receiver **must send something back** (acknowledgement or
  bind response). This response has not been captured yet; see section 2.2 for what has been
  ruled out.
- **Binding:** the receiver binds to the **first handset** it accepts after power-on. Other
  handsets are ignored until the receiver is power-cycled. Since all handsets use the same
  frequencies and differ only in their 3-byte identity (section 3), the receiver obviously stores
  this identity (interpretation).
- After power-on, the receiver locks into the mode of the first source it receives: handset
  (this document) or app (Connect telegram, see [MK4.0 §1](MK4.0.md#1-sequence)).

### 1.1 LED behaviour

Observed on the handset status LED and the receiver LED:

| Situation | Handset LED | Receiver LED |
|---|---|---|
| Handset switched on, no receiver | blinking (bind phase) | – |
| Receiver switched on | **constant** (bound) | constant |
| Handset switched off | – | blinks again after a few seconds (failsafe timeout, searching) |
| Handset switched on again | constant **immediately** | constant |
| Receiver switched off | stays **constant** | – |

Conclusions (interpretation):

- The receiver transmits only **during binding**: the handset changes from blinking to constant
  when the receiver answers, but does not notice when the receiver is switched off. In operation
  the link is one-way (handset → receiver), there is no acknowledgement or telemetry.
- A receiver that has lost its handset (failsafe) stays bound to it and answers its bind telegrams
  again; the binding is only lost by power-cycling the receiver.
- Re-binding can therefore be triggered repeatedly by switching the handset off and on while the
  receiver stays on – useful for capturing the receiver's answer.

---

## 2. Radio parameters

| Phase | Frequency | Address on air (descrambled, MSB first) | Payload |
|---|---|---|---|
| Bind | 2411 MHz | `48 44 4B 03` + identity byte | 5 bytes |
| Operation | 2423, 2441, 2458, 2466 MHz | `0E 6E DB 6C` + identity byte | 8 bytes |

- The first four address bytes are **identical for all handsets** in each phase. The bind prefix
  `48 44 4B` reads `HDK` in ASCII.
- Frame format, scrambler and CRC exactly as described in [XN297L §5](../Chips/XN297L.md).
- Weak copies (−84 … −89 dBm) of the operating frames were also seen on 2442, 2450, 2474 and
  2482 MHz while the four operating channels were received at −50 … −65 dBm. They are most likely
  adjacent-channel / image reception and not additional hopping channels.

### 2.1 Timing

| Phase | Observation |
|---|---|
| Bind | bursts of frames every ~14 ms on 2411 MHz |
| Operation | listening on 2423 MHz only: ~47 frames/s, intervals alternating ~17 ms and ~28 ms |

The hopping sequence (order of the four channels, time per channel) has not been determined yet.

Reception quality with the nRF52840 sniffer (`nrf1m`): about 6 … 10 % of the bind telegrams of
handset 3 fail the CRC, independent of whether a receiver is switched on. The errors are
systematic (identical corrupted byte patterns recur), which points to a demodulation mismatch
(frequency deviation / offset) rather than interference.

### 2.2 Search for the receiver's response (2026-11-11)

All captures on the bind channel 2411 MHz, data rate 1 Mbps, handset 3 (`92 60 03`):

| Capture | Receiver | Result |
|---|---|---|
| promiscuous, handset switched off/on 5 times | off | reference: only bind telegrams, 6.3 % with CRC errors |
| promiscuous, handset switched off/on 4 times | on | only bind telegrams, 5.6 % with CRC errors, **no frame with another address** |
| known address, 150 extra bytes (~1.2 ms) captured after every bind telegram | on | **no XN297L preamble or bind address** at any bit position after the telegrams (no acknowledgement) |

Ruled out so far: a receiver frame with XN297L preamble on 2411 MHz at 1 Mbps, and an
acknowledgement within 1.2 ms after the handset's bind telegram on the bind address.

Remaining hypotheses:

1. The receiver transmits a beacon on **another channel** while it is searching (LED blinking),
   and the handset listens for it in the ~15 ms gaps between its bind telegrams.
2. The receiver answers with **another data rate** (2 Mbps, or 250 kbps – the latter cannot be
   received with the nRF52840).
3. The receiver answers on one of the **operating channels**.

Planned captures (promiscuous, payload length auto). The complete step-by-step plan for all open questions is in [MK4.0-Capture-Plan.md](MK4.0-Capture-Plan.md); captures A, B, C below correspond to its runs R2.1, R2.3 and R3.2 (the plan uses 20 ms dwell and 120 s per run):

| # | Situation | Channels | Dwell | Data rate |
|---|---|---|---|---|
| A | receiver only (searching, LED blinking), all handsets off, ~30 s | `0-83` | 50 ms | 1 Mbps |
| B | as A | `0-83` | 50 ms | 2 Mbps |
| C | receiver on, handset switched off/on several times | `11` | 0 | 2 Mbps |

If none of them shows the response, a receiver supporting 250 kbps is needed (e.g. nRF24L01+ or
an SDR).

---

## 3. Address and identity

The three handsets differ only in **one address byte** (the last byte on air) and the
**first two payload bytes**. These 3 bytes are the same in the bind and in the operating phase:

| Handset | Identity byte | ID | Bind address (`TX_ADDR`) | Operating address (`TX_ADDR`) |
|---|---|---|---|---|
| 1 | `8C` | `43 EB` | `8C 03 4B 44 48` | `8C 6C DB 6E 0E` |
| 2 | `1C` | `4F 20` | `1C 03 4B 44 48` | `1C 6C DB 6E 0E` |
| 3 | `92` | `60 03` | `92 03 4B 44 48` | `92 6C DB 6E 0E` |

`TX_ADDR` is given in SPI write order (LSByte first), i.e. reversed compared with the on-air order
in section 2.

**Address length is not certain.** The CRC covers address and payload together, so a capture
cannot tell where the address ends. Two interpretations give identical frames on air:

| Interpretation | Address | Payload (operation) | Handset identity |
|---|---|---|---|
| A (used in this document) | 5 bytes: common 4 bytes + identity byte | `ID0 ID1 CH1 … CH6` (8 bytes) | identity byte in the address + 2-byte ID |
| B | 4 bytes, common to all handsets | `31 43 EB CH1 … CH6` (9 bytes, handset 1) | 3 bytes at the start of the payload |

In interpretation B the identity byte is part of the payload; because payload bytes are sent LSB
first, `8C` / `1C` / `92` then read `31` / `38` / `49`.

---

## 4. Bind telegram (5 bytes)

| Offset | Value | Meaning |
|---|---|---|
| 0 | `ID0` | handset ID, byte 0 |
| 1 | `ID1` | handset ID, byte 1 |
| 2 | `0x00` | constant |
| 3 | `0x00` | constant |
| 4 | `0x00` | constant |

The bind telegram contains no channel values; moving the sticks does not change it.

## 5. Control telegram (8 bytes)

| Offset | Content | Observed values | Interpretation |
|---|---|---|---|
| 0 | `ID0` | constant per handset | handset ID, byte 0 |
| 1 | `ID1` | constant per handset | handset ID, byte 1 |
| 2 | CH1 | `01` … `80` … `FF` | analog stick axis |
| 3 | CH2 | `01` … `80` … `FF` | analog stick axis |
| 4 | CH3 | `01` … `80` … `FF` | analog stick axis |
| 5 | CH4 | `01` … `80` … `FF` | analog stick axis |
| 6 | CH5 | `02` / `80` / `FE` | button pair or 3-position switch |
| 7 | CH6 | `02` / `80` / `FE` | button pair or 3-position switch |

- **Neutral** = `0x80`. Neutral control telegram of handset 1: `43 EB 80 80 80 80 80 80`.
- Analog channels use the full byte (observed minimum `0x01`, maximum `0xFF`), unlike the app
  telegram with one nibble per channel.
- Which stick axis and which button belong to CH1 … CH6, and how they map to the ports A … D
  of the receiver, is not determined yet (section 9).

---

## 6. Example frames (handset 1)

Complete frames on air (MSB first, scrambled), as transmitted by the handset and received by the
sniffer. They were reproduced bit-exactly with the reference model in
[XN297L §7](../Chips/XN297L.md) (5-byte address, interpretation A).

| Frame | Preamble | Address | Payload | CRC |
|---|---|---|---|---|
| Bind `43 EB 00 00 00` | `71 0F 55` | `AB F5 00 E9 09` | `7E 32 66 0D AE` | `C0 02` |
| Control, neutral `43 EB 80 80 80 80 80 80` | `71 0F 55` | `ED DF 90 86 09` | `7E 32 67 0C AF 8D 89 13` | `2C 1F` |

## 7. Comparison with app control (BLE)

Layer-by-layer comparison with side-by-side example frames: [MK4.0 Remote vs. BLE](MK4.0-Remote-vs-BLE.md).

| | Handset | App ([MK4.0](MK4.0.md)) |
|---|---|---|
| Transport | native XN297L-compatible frames | BLE advertising emulating an XN297L frame |
| Frequency | bind 2411 MHz, operation 2423 / 2441 / 2458 / 2466 MHz (hopping) | 2402 MHz (BLE channel 37) |
| Address (`TX_ADDR`) | `<identity> 03 4B 44 48` (bind), `<identity> 6C DB 6E 0E` (operation) | `C1 C2 C3 C4 C5` |
| Telegrams | Bind (5 bytes), Control (8 bytes) | Connect (8 bytes), Command (10 bytes) |
| Channel values | 6 × 1 byte (4 analog, 2 three-state) | 3 devices × 4 nibbles |
| Pairing | yes, receiver binds to the first handset | no, app identifier is ignored |
| Devices | 1 receiver per handset | 3 device slots in a shared telegram |

## 8. Capturing with the XN297L sniffer

| Purpose | Sync mode | Address | RF channels | Dwell | Payload length |
|---|---|---|---|---|---|
| Find any handset | promiscuous | – | `0-83` | 30 … 50 ms | 0 (auto) |
| Bind phase of handset 1 | known address | `8C034B4448` | `11` | 0 | 5 |
| Operation of handset 1 | known address | `8C6CDB6E0E` | `23,41,58,66` or a single channel | 0 or short | 8 |

Data rate `1 Mbps (nRF)` in all cases.

---

## 9. Open questions

The captures and experiments planned to answer these questions are described in [MK4.0-Capture-Plan.md](MK4.0-Capture-Plan.md).

- **Receiver response:** what does the MK4.0 receiver send to end the bind phase (channel,
  address, data rate, content)? Not captured yet, see section 2.2 for what has been ruled out
  and the planned captures.
- **Address length:** 5-byte address + 2-byte ID (interpretation A) or 4-byte address + 3-byte
  identity in the payload (interpretation B)?
- **Channel mapping:** which stick axis / button is CH1 … CH6, and which ports A … D of the
  receiver react to which channel? Do CH5 / CH6 have any effect on the MK4.0?
- **Hopping:** order of the four operating channels and time per channel; meaning of the weak
  frames on 2442 / 2450 / 2474 / 2482 MHz.
- **Identity:** is the 3-byte identity fixed per handset (factory programmed) or generated at
  power-on? Does the receiver keep the binding over a power cycle (observed: no, it binds again
  to the first handset)?
- Meaning of the constant bytes `00 00 00` in the bind telegram.
- Failsafe timeout of the receiver in handset mode ("a few seconds"; in app mode approx. 2 s).
- Does the receiver transmit anything while it is searching (LED blinking) without a handset?
