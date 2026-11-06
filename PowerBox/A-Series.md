# PowerBox A Series – Bluetooth Protocol

> Source: [J0EK3R/brickcontroller2](https://github.com/J0EK3R/brickcontroller2) – `DeviceManagement/PowerBox/PowerBoxASeries.cs`, `PowerBoxBaseNibble.cs`, `PowerBox.cs`, `PowerBoxDeviceManager.cs`, `Protocols/PowerBoxProtocol.cs`, `Protocols/CryptTools.cs`, the platform `PowerBoxPlatformService.cs` files, `UI/Controls/Devices/PowerBoxASeriesChannelSelectorView.xaml` and `PowerBoxASeriesDatagramTests.cs`.
> Last updated: 2026-11-06

<img src="img/powerboxaseries_image.png" alt="PowerBox A Series module" height="160">

*Image: BrickController2 (`UI/Images/powerboxaseries_image.png`, MIT License).*

## Overview

| Property | Value |
|---|---|
| Device | PowerBox A Series – 4-channel receiver |
| Transport | **BLE advertising** (broadcast), no GATT connection |
| Direction | app → receiver only (no back channel, no battery voltage) |
| Manufacturer ID | **`0xFF00`** |
| Devices | 1 (no device slots) |
| Channels | 4 (port A … D), one **nibble** each, bidirectional analog |
| Raw telegrams | Connect (8 bytes), Command (8 bytes) |
| Encoding | XN297L-compatible frame + BLE whitening compensation, same algorithm as [Mould King MK4.0](../MouldKing/MK4.0.md#5-encoding-into-ble-advertising-data) (see [XN297L](../Chips/XN297L.md)) |

The A Series uses the same radio layer as the Mould King and JIESTAR modules: the phone builds the advertising data so that, after BLE whitening on channel 37, an XN297L frame (preamble `71 0F 55`, address `C1 … C5`, CRC16, scrambler) appears on air. `PowerBoxProtocol` uses the same constants as `MKProtocol`, only the manufacturer ID differs.

### Relation to JIESTAR SCM4

The PowerBox telegrams use the **same identifiers** as the [JIESTAR SCM4](../JieStar/SCM4.md) (Connect `A4 … 5B`, Command `40 … BF`) and the same nibble encoding. Differences:

| Topic | JIESTAR SCM4 | PowerBox A Series |
|---|---|---|
| Manufacturer ID | `0xFFF0` | `0xFF00` |
| Connect bytes 3 … 6 | `80 80 80 80` | `80 80 80 00` |
| Command bytes 5, 6 | `80 80` | `00 00` |
| Device slots | 3 (BLE channel 37/38/39) | 1 (channel 37) |
| Manufacturer data length | Android 24 / iOS 26 | Android **18** / iOS **20** (no padding on Android) |

The manufacturer ID is part of the BLE header, which the XN297L receiver does not see. On air the two products therefore only differ in the constant bytes.

---

## 1. Sequence

```
App starts advertising
        │
        ▼
 Send Connect telegram        → receiver (freshly powered on) selects Bluetooth mode
        │
        ▼
 Send Command telegram(s)     → channel values for ports A … D
        │
        ▼
 Stop: end advertising
```

- When advertising starts, the **Connect telegram** is sent first. There is **no pairing** (see section 4).
- Afterwards the **Command telegram** carries the four channel values (section 3).
- The sender has to transmit continuously; BLE advertising repeats the current data at every advertising interval.

Mode selection and a failsafe timeout are documented for the [MK4.0](../MouldKing/MK4.0.md#1-sequence); whether the A Series behaves the same is **not verified** (see section 9).

### 1.1 Implementation notes (BrickController2, not part of the protocol)

- Vendor `PowerBox`, device type `A Series` (device address string `Device`, no real BLE address).
- The device gets its own `BluetoothAdvertisingDeviceHandler`.
- If all channels stay at 0 for longer than `ReconnectTimeSpan` = **3 s**, BC2 sends the Connect telegram again.
- The app identifier is managed by `PowerBoxDeviceManager` (2 bytes).
- Channel letters A … D (`DeviceChannelLabel._powerBoxChannelLetters`); in the channel selector ports B/D are on the left, A/C on the right of the module image – matching the labels on the housing (B top left, A top right, D bottom left, C bottom right).

---

## 2. Connect telegram (8 bytes, raw)

| Offset | Value | Meaning |
|---|---|---|
| 0 | `0xA4` | telegram identifier (start) |
| 1 | `AppId[0]` | app identifier byte 0 |
| 2 | `AppId[1]` | app identifier byte 1 |
| 3 | `0x80` | constant (meaning unknown) |
| 4 | `0x80` | constant (meaning unknown) |
| 5 | `0x80` | constant (meaning unknown) |
| 6 | `0x00` | constant (meaning unknown) |
| 7 | `0x5B` | telegram identifier (end) |

Identical for A Series and [M Battery](M-Battery.md). Start and end identifier are bitwise complements: `0xA4 + 0x5B = 0xFF`.

---

## 3. Command telegram (8 bytes, raw)

| Offset | Content | Meaning |
|---|---|---|
| 0 | `0x40` | telegram identifier (start) |
| 1 | `AppId[0]` | app identifier byte 0 |
| 2 | `AppId[1]` | app identifier byte 1 |
| 3 | `A │ B` | channel 0 / port A (high nibble), channel 1 / port B (low nibble) |
| 4 | `C │ D` | channel 2 / port C (high nibble), channel 3 / port D (low nibble) |
| 5 | `0x00` | constant |
| 6 | `0x00` | constant |
| 7 | `0xBF` | telegram identifier (end) |

### 3.1 Channel value (nibble)

| Nibble | Meaning |
|---|---|
| `0x0` | **stop / neutral** (default) |
| `0x1` … `0x7` | reverse, `0x1` = slowest, `0x7` = full |
| `0x8` | not used by BC2 |
| `0x9` … `0xF` | forward, `0x9` = slowest, `0xF` = full |

Conversion from the app value `v` ∈ [-1.0 … +1.0] (7 steps per direction, `PowerBoxBaseNibble.SetOutput_AnalogChannel`):

```
v ≥ +1/7  →  nibble = min(0xF, (int)(v * 7) + 8)     // 0x9 … 0xF
v ≤ -1/7  →  nibble = min(0x7, (int)(-v * 7))        // 0x1 … 0x7
else      →  nibble = 0x0                            // stop
```

### 3.2 Examples (AppId = `7B A7`)

| Channels (A, B, C, D) | Raw telegram |
|---|---|
| 0, 0, 0, 0 | `40 7B A7 00 00 00 00 BF` |
| +1, 0, 0, 0 | `40 7B A7 F0 00 00 00 BF` |
| 0, +1, 0, 0 | `40 7B A7 0F 00 00 00 BF` |
| −1, 0, 0, 0 | `40 7B A7 70 00 00 00 BF` |
| 0, 0, 0, −1 | `40 7B A7 00 07 00 00 BF` |
| +1, +1, +1, +1 | `40 7B A7 FF FF 00 00 BF` |

---

## 4. App identifier

- Bytes 1 and 2 of both telegrams contain a **2-byte app identifier** (random, generated on first launch, stored in the app settings, managed by `PowerBoxDeviceManager`).
- Whether the A Series evaluates these bytes is **not known**.

---

## 5. Encoding into BLE advertising data

Same algorithm as for Mould King – see [MK4.0 §5](../MouldKing/MK4.0.md#5-encoding-into-ble-advertising-data) and [XN297L §6](../Chips/XN297L.md#6-emulation-with-other-radios).

| Item | Value |
|---|---|
| Manufacturer ID | `0xFF00` |
| Preamble | `71 0F 55` |
| RF address (`TX_ADDR`) | `C1 C2 C3 C4 C5` (on air `C5 … C1`) |
| CRC | CRC-16/CCITT, init `0xFFFF`, over address + telegram (bit-reversed), little endian in the buffer |
| Scrambling 1 | `CTX = 0x3F` (XN297L scrambler) over address + telegram + CRC |
| Scrambling 2 | `CTX = 0x25` (BLE whitening, channel 37) over the whole buffer |
| `headerOffset` / length | Android 15 / **18 bytes** (no padding), iOS 13 / **20 bytes** (padding `0x12, 0x13`), Windows 15 / 26 bytes (payload at offset 3) |

Result length before padding: Connect 18 bytes, Command 18 bytes. On Android the manufacturer data is exactly the XN297L frame; the AD length is `0x15` and the PDU length `0x1F`.

### 5.1 Byte-by-byte comparison: BLE packet vs. XN297L frame (Android)

AppId = `7B A7`, `headerOffset` = 15. Same layout as [MK4.0 §5.5](../MouldKing/MK4.0.md#55-byte-by-byte-comparison-ble-packet-vs-xn297l-frame-android), but with company ID `0xFF00` and the shorter manufacturer data (PDU header `42 1F`, AD length `15`).

**How to read the tables:** each column is one byte in transmission order, each row is one view of the same packet. The coloured image shows the table with field colours (legend below each image; light and dark mode); the Markdown table under it contains the same bytes as text, with bold marking the bytes that match.

| Row | Meaning |
|---|---|
| ① | What an XN297L (the original handset chip) would transmit for this telegram with `TX_ADDR = C1 … C5`: preamble, address, telegram, CRC – scrambled, MSB first. `··` = the XN297L sends nothing there. |
| ② | The BLE advertising packet as the phone's BLE stack assembles it, before whitening (LSB first). From PDU byte 15 on this is the manufacturer data from `GetRfPayload()` – it looks completely different from ①, because it is scrambled twice (XN297 scrambler + pre-compensated BLE whitening). |
| ③ | The same packet after BLE whitening (channel 37) – the bytes the radio actually sends, LSB first. Preamble and access address are not whitened. The XN297 preamble shows up as `8E F0 AA` = `71 0F 55` with reversed bit order. |
| ④ | Row ③ with every byte bit-reversed, i.e. read MSB first like an XN297L receiver does. **Bold** bytes are identical to row ①. |
| ④ = ① | ✓ = byte matches the XN297L frame. |

Field abbreviations: `Pre` BLE preamble, `AA` access address, `Hdr` PDU header, `AdvA` advertiser address, `Flg` Flags AD, `AD` AD length/type, `CID` company ID `0xFF00`; **Pre** XN297 preamble, **Adr** XN297 address, **T0 …** raw telegram bytes, **CRC** XN297 CRC.

The BLE part (PDU bytes 0 … 14) does not match – there is nothing to match: for the XN297L receiver it is just noise in front of its preamble `71 0F 55`. Only the *length* of this part (`headerOffset` = 15) matters for the encoding, not its content; the header values are examples (see [XN297L §6.1](../Chips/XN297L.md#61-example-ble-advertising-packet-vs-xn297l-frame)). Padding and the 3-byte BLE CRC after the XN297 CRC are omitted; the receiver stops reading after its CRC.

#### Connect telegram `A4 7B A7 80 80 80 00 5B`

![PowerBox Connect telegram: BLE packet vs. XN297L frame](img/powerbox_connect.svg)

| PDU byte | – | – | – | – | – | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 | 32 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Field | Pre | AA | AA | AA | AA | Hdr | Hdr | AdvA | AdvA | AdvA | AdvA | AdvA | AdvA | Flg | Flg | Flg | AD | AD | CID | CID | **Pre** | **Pre** | **Pre** | **Adr** | **Adr** | **Adr** | **Adr** | **Adr** | **T0** | **T1** | **T2** | **T3** | **T4** | **T5** | **T6** | **T7** | **CRC** | **CRC** |
| ① XN297L on air (MSB first) | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | `71` | `0F` | `55` | `26` | `75` | `88` | `28` | `44` | `99` | `3B` | `83` | `0C` | `AF` | `8D` | `88` | `C8` | `94` | `14` |
| ② BLE before whitening (LSB first) | `AA` | `D6` | `BE` | `89` | `8E` | `42` | `1F` | `55` | `44` | `33` | `22` | `11` | `C0` | `02` | `01` | `06` | `15` | `FF` | `00` | `FF` | `6D` | `B6` | `43` | `CF` | `7E` | `8F` | `47` | `11` | `41` | `66` | `59` | `38` | `D1` | `7A` | `2A` | `EF` | `58` | `8B` |
| ③ BLE on air (LSB first) | `AA` | `D6` | `BE` | `89` | `8E` | `CF` | `CD` | `02` | `E5` | `0E` | `85` | `77` | `70` | `77` | `30` | `17` | `5D` | `69` | `77` | `07` | `8E` | `F0` | `AA` | `64` | `AE` | `11` | `14` | `22` | `99` | `DC` | `C1` | `30` | `F5` | `B1` | `11` | `13` | `29` | `28` |
| ④ BLE on air, bits reversed (MSB first) | `55` | `6B` | `7D` | `91` | `71` | `F3` | `B3` | `40` | `A7` | `70` | `A1` | `EE` | `0E` | `EE` | `0C` | `E8` | `BA` | `96` | `EE` | `E0` | **`71`** | **`0F`** | **`55`** | **`26`** | **`75`** | **`88`** | **`28`** | **`44`** | **`99`** | **`3B`** | **`83`** | **`0C`** | **`AF`** | **`8D`** | **`88`** | **`C8`** | **`94`** | **`14`** |
| ④ = ① |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

#### Command telegram, neutral `40 7B A7 00 00 00 00 BF`

![PowerBox Command telegram (neutral): BLE packet vs. XN297L frame](img/powerbox_command_neutral.svg)

| PDU byte | – | – | – | – | – | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 | 32 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Field | Pre | AA | AA | AA | AA | Hdr | Hdr | AdvA | AdvA | AdvA | AdvA | AdvA | AdvA | Flg | Flg | Flg | AD | AD | CID | CID | **Pre** | **Pre** | **Pre** | **Adr** | **Adr** | **Adr** | **Adr** | **Adr** | **T0** | **T1** | **T2** | **T3** | **T4** | **T5** | **T6** | **T7** | **CRC** | **CRC** |
| ① XN297L on air (MSB first) | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | ·· | `71` | `0F` | `55` | `26` | `75` | `88` | `28` | `44` | `BE` | `3B` | `83` | `0D` | `AE` | `8C` | `88` | `EF` | `97` | `34` |
| ② BLE before whitening (LSB first) | `AA` | `D6` | `BE` | `89` | `8E` | `42` | `1F` | `55` | `44` | `33` | `22` | `11` | `C0` | `02` | `01` | `06` | `15` | `FF` | `00` | `FF` | `6D` | `B6` | `43` | `CF` | `7E` | `8F` | `47` | `11` | `A5` | `66` | `59` | `B8` | `51` | `FA` | `2A` | `0B` | `98` | `8F` |
| ③ BLE on air (LSB first) | `AA` | `D6` | `BE` | `89` | `8E` | `CF` | `CD` | `02` | `E5` | `0E` | `85` | `77` | `70` | `77` | `30` | `17` | `5D` | `69` | `77` | `07` | `8E` | `F0` | `AA` | `64` | `AE` | `11` | `14` | `22` | `7D` | `DC` | `C1` | `B0` | `75` | `31` | `11` | `F7` | `E9` | `2C` |
| ④ BLE on air, bits reversed (MSB first) | `55` | `6B` | `7D` | `91` | `71` | `F3` | `B3` | `40` | `A7` | `70` | `A1` | `EE` | `0E` | `EE` | `0C` | `E8` | `BA` | `96` | `EE` | `E0` | **`71`** | **`0F`** | **`55`** | **`26`** | **`75`** | **`88`** | **`28`** | **`44`** | **`BE`** | **`3B`** | **`83`** | **`0D`** | **`AE`** | **`8C`** | **`88`** | **`EF`** | **`97`** | **`34`** |
| ④ = ① |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## 6. Reference implementation (Python)

Encoder identical to the Mould King reference, extended by the parameters `total_len` and `ctx2` (verified against the MK4.0 test vectors from `CryptToolsTests.cs`). The telegram builder is verified against all cases of `PowerBoxASeriesDatagramTests.cs`.

```python
# PowerBox A Series - reference encoder for BLE advertising payloads.
# Re-implementation of BrickController2 CryptTools.GetRfPayload()
# plus the A Series telegram builder.

MANUFACTURER_ID = 0xFF00                    # company ID used for advertising

# --- Protocol constants (JieStarProtocol.cs / PowerBoxProtocol.cs) ------------
SEED   = [0xC1, 0xC2, 0xC3, 0xC4, 0xC5]     # 5-byte RF address
HEADER = [0x71, 0x0F, 0x55]                 # XN297L preamble
CTX1   = 0x3F                               # scrambler seed (address+data+CRC)
CTX2   = 0x25                               # BLE whitening seed (channel 37)


def rev8(b: int) -> int:
    """Reverse the bit order of one byte (0b00000001 -> 0b10000000)."""
    return int(f"{b:08b}"[::-1], 2)


def rev16(w: int) -> int:
    """Reverse the bit order of a 16-bit word."""
    return int(f"{w:016b}"[::-1], 2)


def crc16(seed: list[int], data: list[int]) -> int:
    """CRC16-CCITT as used by the protocol.

    - seed is processed in reverse order, bytes as-is
    - data is processed in forward order, each byte bit-reversed
    - result is bit-reversed and inverted
    """
    crc = 0xFFFF
    for b in list(reversed(seed)) + [rev8(x) for x in data]:
        crc ^= b << 8
        for _ in range(8):
            # shift left, apply polynomial 0x1021 when the MSB falls out
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return rev16(crc) ^ 0xFFFF


def whitening_init(value: int) -> list[int]:
    """7-bit LFSR state: fixed 1 followed by bits 5..0 of value."""
    return [1] + [(value >> s) & 1 for s in (5, 4, 3, 2, 1, 0)]


def whitening_next(ctx: list[int]) -> int:
    """Advance the LFSR by one step and return the output bit."""
    v3, v6 = ctx[3], ctx[6]
    ctx[3], ctx[2], ctx[1], ctx[0] = ctx[2], ctx[1], ctx[0], ctx[6]
    ctx[6], ctx[5] = ctx[5], ctx[4]
    ctx[4] = v3 ^ v6
    return ctx[0]


def whitening(buf: list[int], start: int, length: int, value: int) -> None:
    """XOR buf[start:start+length] in place with the LFSR bit stream (LSB first)."""
    ctx = whitening_init(value)
    for i in range(start, start + length):
        out = 0
        for bit in range(8):
            out |= (whitening_next(ctx) ^ ((buf[i] >> bit) & 1)) << bit
        buf[i] = out


def get_rf_payload(data: list[int], platform: str = "android", total_len: int | None = None,
                   ctx2: int = CTX2) -> list[int]:
    """Convert a raw telegram into advertising manufacturer data.

    platform "android": header_offset 15, padding index + 1
    platform "ios":     header_offset 13, padding 0x12, 0x13, ...
    total_len:          payload length of the platform (see section 5)
    ctx2:               BLE whitening seed = BLE advertising channel index (0x25 = 37)
    """
    header_offset = 13 if platform == "ios" else 15

    # leading dummy bytes keep the whitening stream aligned with the real BLE PDU
    buf = [0] * header_offset
    # preamble + address (reversed order), every byte bit-reversed
    buf += [rev8(b) for b in HEADER + SEED[::-1]]
    # raw telegram unchanged
    buf += list(data)
    # CRC16, little endian
    crc = crc16(SEED, data)
    buf += [crc & 0xFF, crc >> 8]

    # scrambling 1: address + data + CRC (skips the 3 preamble bytes)
    whitening(buf, header_offset + len(HEADER), len(SEED) + len(data) + 2, CTX1)
    # scrambling 2: pre-compensates the BLE whitening over the whole PDU
    whitening(buf, 0, len(buf), ctx2)

    out = buf[header_offset:]
    if total_len is None:
        return out
    # fill up to the platform specific length
    if platform == "ios":
        return out + [0x12 + i for i in range(total_len - len(out))]
    return out + [i + 1 for i in range(len(out), total_len)]

# --- PowerBox A Series telegram builder -----------------------------------------------
APP_LEN_ANDROID, APP_LEN_IOS = 18, 20      # manufacturer data length (PowerBoxPlatformService)


def nibble(value: float) -> int:
    """Map -1.0..+1.0 to the PowerBox nibble (0x1..0x7 reverse, 0x0 stop, 0x9..0xF forward).

    Mirrors PowerBoxBaseNibble.SetOutput_AnalogChannel().
    """
    value = max(-1.0, min(1.0, value))          # CutOutputValue()
    if value <= -1 / 7:
        return int(min(0x7, -value * 7))
    if value >= 1 / 7:
        return int(min(0xF, value * 7 + 8))
    return 0x0


def connect_telegram(app_id: tuple[int, int]) -> list[int]:
    """Connect telegram (A Series and M Battery)."""
    return [0xA4, app_id[0], app_id[1], 0x80, 0x80, 0x80, 0x00, 0x5B]


def aseries_command_telegram(app_id: tuple[int, int], channels: list[float]) -> list[int]:
    """A Series Command telegram, channels: 4 values (-1.0..+1.0) for ports A..D."""
    return [0x40, app_id[0], app_id[1],
            (nibble(channels[0]) << 4) | nibble(channels[1]),   # offset 3: port A | port B
            (nibble(channels[2]) << 4) | nibble(channels[3]),   # offset 4: port C | port D
            0x00, 0x00, 0xBF]


if __name__ == "__main__":
    hexs = lambda a: " ".join(f"{x:02X}" for x in a)
    app = (0x7B, 0xA7)
    print(hexs(get_rf_payload(connect_telegram(app), "android", APP_LEN_ANDROID)))
    # -> 6D B6 43 CF 7E 8F 47 11 41 66 59 38 D1 7A 2A EF 58 8B
    print(hexs(get_rf_payload(aseries_command_telegram(app, [0, 0, 0, 0]), "android", APP_LEN_ANDROID)))
    # -> 6D B6 43 CF 7E 8F 47 11 A5 66 59 B8 51 FA 2A 0B 98 8F
```

---

## 7. Test vectors

AppId = `7B A7`. Generated with the reference implementation above; BC2 has no encoded PowerBox vectors in `CryptToolsTests.cs`.

| Raw telegram | CRC16 | `CTXValue2` | Platform | Encoded data |
|---|---|---|---|---|
| `A4 7B A7 80 80 80 00 5B` (Connect) | `0x5FBF` | `0x25` | Android | `6D B6 43 CF 7E 8F 47 11 41 66 59 38 D1 7A 2A EF 58 8B` (no padding) |
| | | | iOS | `F9 08 49 22 47 BA C4 BC CA EF 19 8A 6D B9 35 D8 12 D4` + padding `12 13` |
| `40 7B A7 00 00 00 00 BF` (Command neutral) | `0x5B7F` | `0x25` | Android | `6D B6 43 CF 7E 8F 47 11 A5 66 59 B8 51 FA 2A 0B 98 8F` (no padding) |
| | | | iOS | `F9 08 49 22 47 BA C4 BC 2E EF 19 0A ED 39 35 3C D2 D0` + padding `12 13` |

---

## 8. Hardware

No board analysis yet. The BC2 image shows a flat module with four output connectors (labelled A … D), an orange push button and a Micro-USB socket in the middle.

<img src="img/powerboxaseries_image.png" alt="PowerBox A Series module" height="200">

---

## 9. Open questions

- Meaning of the constant bytes `80 80 80 00` (Connect) and `00 00` (Command, offsets 5 and 6).
- Interference with a [JIESTAR SCM4](../JieStar/SCM4.md) receiver (Device 1 slot, channel 37): identical identifiers, only the constant bytes differ.
- Whether mode selection and a failsafe timeout exist as on the MK4.0.
- Whether the receiver evaluates the app identifier bytes.
- Whether more than one A Series can be addressed (device slots).
- Hardware details (section 8).
