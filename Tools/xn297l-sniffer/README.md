# XN297L sniffer (nRF52840 dongle + Wireshark)

> Receives XN297L frames (2.4 GHz GFSK, see [XN297L](../../Chips/XN297L.md)) with an
> nRF52840 USB dongle and shows them decoded in Wireshark.
> Status: **verified on hardware** with a native XN297L transmitter (promiscuous mode, `nrf1m`)
> and with XN297L frames emulated via BLE advertising (address mode, `ble1m`), see [Status](#status).

A normal Bluetooth dongle cannot receive XN297L transmissions: its controller only
reports packets with the BLE access address `0x8E89BED6` and a valid CRC-24.
The nRF52840, however, has a freely programmable `RADIO` peripheral. This tool
programs it as a raw 1 Mbps GFSK receiver that synchronises on an XN297L sync word;
descrambling and the CRC check are done on the host.

```
 XN297L transmitter
 +----------+---------+---------+-----+
 | preamble | address | payload | CRC |
 | 71 0F 55 | 3..5 B  |         |     |
 +----------+---------+---------+-----+
       |
       |  RF, 2.4 GHz GFSK
       v
 nRF52840 dongle  (firmware/)
 +--------------------------------------+
 | RADIO: nrf1m / ble1m / nrf2m         |
 | sync word = preamble 71 0F 55        |
 |             (promiscuous mode)       |
 |          or scrambled address        |
 |             (address mode)           |
 | hardware CRC and whitening off       |
 +--------------------------------------+
       |
       |  USB CDC, text lines
       v
 PC
 +--------------------------------------+
 | extcap/xn297l_sniffer.py             |
 |   -> Wireshark (DLT_USER0)           |
 |   -> wireshark/xn297l.lua            |
 |      descramble, CRC check, decode   |
 +--------------------------------------+
```

---

## Contents

| Path | Content |
|---|---|
| `firmware/` | Zephyr application for the **nRF52840 MDK USB Dongle** (makerdiary) |
| `firmware/prebuilt/` | ready-to-flash `.uf2` built from this source |
| `extcap/xn297l_sniffer.py` | Wireshark extcap interface **and** console tool (`--print`) |
| `extcap/xn297l_sniffer.bat` | Windows wrapper for the extcap |
| `wireshark/xn297l.lua` | Wireshark dissector |
| `tests/test_decoder.py` | unit tests for the decoder (Python and Lua) |

---

## 1. Sync modes

The nRF52840 needs a sync word (its "address", 3 … 5 bytes) to detect a packet.
Three modes are available:

| Mode | Sync word | Captured | Use |
|---|---|---|---|
| **address** (default) | the XN297L address as it appears on air (byte order reversed, scrambled) | payload + CRC | known address – robust |
| **promiscuous** | the XN297L preamble `71 0F 55` | address + payload + CRC | unknown address – **experimental** |
| **raw** | any 3 … 5 bytes (`--sync`, default `AA AA AA`) | `--raw-length` bytes (default 64), shown undecoded | unknown, **non-XN297L** transmitters – find frequency and sync word |

In address mode the last preamble byte `0x55` serves as the nRF preamble (an
alternating bit pattern, as the nRF radio expects). In promiscuous mode there is no alternating preamble in
front of the sync word, so detection may be poor; use it to find an address, then
switch to address mode.

Example: `TX_ADDR` = `C1 C2 C3 C4 C5` → on air `C5 C4 C3 C2 C1` → scrambled
`26 75 88 28 44` (= sync word in address mode). This is the address used by the
[MK4.0](../../MouldKing/MK4.0.md) receivers.

If the payload length is not given, the decoder tries every length and takes the first
one with a valid CRC.

**Raw mode** does no XN297L processing at all: no descrambling, no address, no CRC search. It
prints / records the sync word and the captured bytes as received (MSB first). Typical use is a
transmitter whose sync word is unknown: with the alternating preamble `AA AA AA` or `55 55 55`
as sync word, every GFSK frame at the selected data rate with a long enough preamble is
captured, and the captured bytes begin with the transmitter's own sync word. Once that is known,
use it as `--sync` to receive the frames reliably. Example: the
[CaDA CJV8011 capture plan](../../CaDA/CJV8011-Capture-Plan.md).

---

## 2. Firmware

### 2.1 Flashing (UF2 bootloader)

The dongle ships with a UF2 bootloader; no programmer is needed.

1. With the dongle plugged in, press the button **twice quickly**. The RGB LED turns green
   and a drive **UF2BOOT** appears. (Tested with UF2 bootloader 0.2.13; according to the
   makerdiary documentation, newer bootloaders enter this mode by holding the button while
   plugging the dongle in.)
2. Copy `firmware/prebuilt/xn297l_sniffer_nrf52840_mdk_usb_dongle.uf2` (or your own
   `build/zephyr/zephyr.uf2`) onto the drive.
3. The dongle restarts and appears as a serial port (**XN297L Sniffer**, Windows: `COMx`,
   Linux: `/dev/ttyACM0`, macOS: `/dev/cu.usbmodem…`).

> Flashing replaces the current firmware (e.g. nRF Sniffer for Bluetooth LE).
> A backup of the nRF Sniffer firmware is in [../nrf-sniffer-ble](../nrf-sniffer-ble/README.md);
> copy it onto the UF2BOOT drive the same way to switch back.

The application is linked to `0x1000` (after the Nordic MBR), which is where the UF2
bootloader of the dongle expects it.

### 2.2 LEDs

| LED | Meaning |
|---|---|
| red | receiver stopped |
| blue | receiver running |
| green flash | frame received |
| red blinking | start-up error (HF crystal or USB) |

### 2.3 Building

Tested to build with **Zephyr v3.7.0** and **Zephyr SDK 0.16.8** (nRF Connect SDK
v2.7 or later contains a compatible Zephyr).

```bash
# inside a west workspace (nRF Connect SDK or plain Zephyr)
west build -b nrf52840_mdk_usb_dongle -p always path/to/Tools/xn297l-sniffer/firmware
# result: build/zephyr/zephyr.uf2
```

With the nRF Connect extension for VS Code: *Add build configuration*, board
`nrf52840_mdk_usb_dongle`, application folder `firmware`.

The build prints two CMake warnings about the USB VID/PID defaults and the legacy USB
device stack. Both are expected for a hobby tool.

### 2.4 Serial protocol

Text lines over the virtual COM port, terminated by `\n`. Data is only sent while the
port is open (DTR set). Any terminal program can be used.

| Command | Meaning | Default |
|---|---|---|
| `sync <hex>` | sync word, 3 … 5 bytes, on-air order, MSB first | `710F55` |
| `len <n>` | bytes captured after the sync word (1 … 250) | `39` |
| `ch <list>` | RF channels, channel = MHz − 2400; single channels and ranges, e.g. `23`, `2,26,80`, `0-83` (up to 84 entries, ranges need firmware 1.1) | `2,26,80` |
| `dwell <ms>` | time per channel, `0` = stay on the first one | `300` |
| `rate <r>` | `nrf1m`, `ble1m` (1 Mbps, BLE deviation), `nrf2m` | `nrf1m` |
| `start` / `stop` | start / stop the receiver | stopped |
| `info` / `help` | show configuration / commands | |

Answers: `OK`, `E <error>`, `I <info>` and for every frame

```
P <device time µs> <channel> <RSSI dBm> <sync word + captured bytes as hex>
P 1256623 2 -55 2675882844 09AD4A0CAF8D7A58...
```

The XN297L 250 kbps mode is not supported (the nRF52840 has no 250 kbps proprietary mode).

---

## 3. Wireshark

### 3.1 Installation

Requirements: Wireshark 3.6 or later, Python 3.8 or later, `pyserial`:

```bash
pip install pyserial          # Windows: py -m pip install pyserial
```

Copy the files to the personal Wireshark folders (shown under
*Help → About Wireshark → Folders*):

| File | Windows | Linux / macOS |
|---|---|---|
| `extcap/xn297l_sniffer.py` | `%APPDATA%\Wireshark\extcap\` | `~/.local/lib/wireshark/extcap/` (make it executable) |
| `extcap/xn297l_sniffer.bat` | `%APPDATA%\Wireshark\extcap\` (same folder) | – |
| `wireshark/xn297l.lua` | `%APPDATA%\Wireshark\plugins\` | `~/.local/lib/wireshark/plugins/` |

Restart Wireshark. A new interface **XN297L sniffer (nRF52840 dongle)** appears.

> **Empty serial port list / capture does not start:** the extcap runs with `py -3` on
> Windows, which can be a different Python than `python`. Install pyserial for exactly
> that interpreter: `py -3 -m pip install pyserial`. The port field is editable, so the
> port (e.g. `COM8`) can also be typed in directly.

### 3.2 Capturing

Click the gear icon next to the interface and set:

| Option | Meaning |
|---|---|
| Serial port | port of the dongle |
| Sync mode | *Known address*, *Promiscuous* or *Raw* (section 1) |
| Address | `TX_ADDR` in SPI write order, e.g. `C1C2C3C4C5` (address mode) |
| Address length | 3 … 5 (promiscuous mode) |
| Payload length | `0` = find the length via CRC |
| RF channels | channel = MHz − 2400, e.g. `2` for 2402 MHz, `2,26,80` for the three BLE advertising frequencies, `0-83` for all channels |
| Dwell time | ms per channel when hopping; `0` = stay on the first channel of the list |
| Data rate | 1 Mbps (nRF), 1 Mbps (BLE deviation), 2 Mbps |
| Scrambler off | for transmitters with the scrambler disabled |
| Extra bytes after the frame | additional captured bytes (8 µs each at 1 Mbps), e.g. to look for an acknowledgement sent right after a frame; shown as *Bytes after the frame* |
| Sync word (raw mode) | 3 … 5 bytes, on-air order, MSB first, e.g. `AAAAAA`, `555555` |
| Capture length (raw mode) | bytes captured after the sync word, 1 … 250 |

Display filter examples:

```
xn297l.crc_ok == 1
xn297l.address == "C1:C2:C3:C4:C5"
xn297l.payload_len == 10
xn297l.hdr.freq == 2402
xn297l.hdr.flags.raw == 1
```

Raw captures are shown with the protocol *RAW 2.4G* and the fields *Sync word (raw capture)* and
*Bytes after the sync word (raw capture)*.

### 3.3 Console mode (without Wireshark)

```bash
python extcap/xn297l_sniffer.py --list-ports
python extcap/xn297l_sniffer.py --print --port COM5 --mode address --address C1C2C3C4C5 --channels 2 --dwell 0
python extcap/xn297l_sniffer.py --print --port COM5 --mode promiscuous --show-bad
python extcap/xn297l_sniffer.py --print --port COM5 --mode raw --sync AAAAAA --raw-length 64 --channels 0-83 --dwell 50
```

```
    1.258836s 2402 MHz  -55 dBm  addr C1:C2:C3:C4:C5  CRC ok   len  8  payload AD 12 34 80 80 80 4F 52
```

Raw mode (sync word `|` captured bytes):

```
    0.001000s 2440 MHz  -55 dBm  raw AA AA AA | 03 80 A5 C3 …
```

### 3.4 Record format (DLT_USER0)

Every record starts with a 12-byte pseudo header (little endian), followed by the
on-air bytes beginning with the first address byte (MSB-first notation, still scrambled);
in raw mode beginning with the sync word:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | version (`1`) |
| 1 | 1 | flags: bit 0 = scrambler on, bit 1 = promiscuous capture, bit 2 = raw capture |
| 2 | 1 | RF channel (MHz − 2400) |
| 3 | 1 | RSSI in dBm (signed) |
| 4 | 1 | address length (raw mode: sync word length) |
| 5 | 1 | payload length (`0` = unknown) |
| 6 | 1 | data rate: 0 = nrf1m, 1 = nrf2m, 2 = ble1m |
| 7 | 1 | reserved |
| 8 | 4 | device timestamp in µs |
| 12 | n | on-air bytes |

The dissector registers for DLT_USER0. If DLT_USER0 is already used for something else
in *Preferences → Protocols → DLT_USER*, remove that entry.

### 3.5 Device-specific dissectors

The decoded payload (FIFO values) is passed to the dissector table `xn297l.address`,
keyed by the address in `TX_ADDR` order as upper-case hex. A protocol on top of
XN297L can therefore live in its own Lua file:

```lua
-- example: my_device.lua (placed next to xn297l.lua)
local p = Proto("mydev", "My XN297L device")
local f_cmd = ProtoField.uint8("mydev.cmd", "Command", base.HEX)
p.fields = { f_cmd }

function p.dissector(tvb, pinfo, tree)
    local t = tree:add(p, tvb())
    t:add(f_cmd, tvb(0, 1))
end

DissectorTable.get("xn297l.address"):add("C1C2C3C4C5", p)
```

---

## 4. Finding the parameters

1. **Frequency:** scan all channels in promiscuous mode (`ch 0-83`, dwell 30 … 50 ms) and
   filter on strong signals in Wireshark (`xn297l.hdr.rssi > -85`); noise hits stay at about
   −95 … −100 dBm. An XN297L signal is only 1 … 2 MHz wide, so a coarse grid (e.g. every
   5 MHz) can miss a transmitter on a fixed channel.
2. **Address:** if unknown, use promiscuous mode with `--show-bad`, look for recurring
   address bytes, then switch to address mode.
3. **Data rate:** if nothing is received, try `ble1m` (wider deviation) or `nrf2m`
   (old XN297 at 2 Mbps).
4. **Frequency-hopping transmitters** (e.g. the original handsets, which hop over four
   channels): set **one** of their channels with dwell `0`. The sniffer then receives the
   transmitter every time its hopping sequence passes that channel – a complete, regular capture.
   A list of all channels needs a dwell > 0; because sniffer and transmitter hop independently,
   frames are then caught only at random. Examples:
   [MK4.0 handset](../../MouldKing/MK4.0-Remote.md#8-capturing-with-the-xn297l-sniffer),
   [SCM8 handset](../../JieStar/SCM8-Remote.md#8-capturing-with-the-xn297l-sniffer).

---

## 5. Tests

```bash
pip install lupa              # optional: also runs the Lua tests
python tests/test_decoder.py
```

The reference frames are generated with an independent encoder in the BLE/LSB-first
formulation (same as in the [MK4.0](../../MouldKing/MK4.0.md) encoder) and must be decoded
correctly by both the Python and the Lua decoder (Lua 5.1 … 5.4).

---

## Status

| Part | Verified |
|---|---|
| Firmware build (Zephyr 3.7.0, SDK 0.16.8), UF2 at `0x1000` | ✅ |
| Python decoder, Lua decoder (Lua 5.1 … 5.4) against reference frames | ✅ |
| extcap discovered by Wireshark 4.2, live capture from a simulated dongle, dissector output | ✅ |
| Mapping of the sync word to `BASE0`/`PREFIX0` (derived from the BLE access address layout) | ✅ on hardware |
| Address mode, `ble1m`, 2402 MHz: XN297L frames emulated by a phone via BLE advertising (address `C1C2C3C4C5`) | ✅ 292 of 292 frames with valid CRC, payload length found automatically, RSSI −59 … −84 dBm |
| Native XN297L transmitter (original remote control), promiscuous mode, `nrf1m`, channel scan with dwell 50 ms | ✅ found on 2423 MHz, 44 frames with valid CRC at −51 … −83 dBm |
| Native XN297L transmitter, address mode, `nrf1m`, single channel | ✅ continuous reception (~47 frames/s on one hopping channel); 6 … 10 % of the frames fail the CRC with systematic, recurring bit errors |
| Extra bytes after the frame (up to 150) | ✅ works; used to search for acknowledgements |
| Raw mode (console tool 1.1.0, any sync word, no decoding) | unit tests and a simulated dongle ✅; **not yet tested on hardware** (first use: [CaDA CJV8011 capture plan](../../CaDA/CJV8011-Capture-Plan.md)) |
| Promiscuous mode, noise | random 24-bit matches on `71 0F 55` at noise level (≈ −95 … −100 dBm) without valid CRC; weak copies of a strong transmitter also appear on adjacent channels (e.g. 2425 MHz for 2423 MHz) with bit errors |

Test 2026-11-11 (address mode): the captured frames show the Connect telegram
`AD 7B A7 80 80 80 4F 52` (8 bytes) and Command telegrams `7D 7B A7 … 82` (10 bytes) with
changing channel nibbles, i.e. exactly the telegrams described in [MK4.0](../../MouldKing/MK4.0.md).

Open questions:

- Address length: the CRC covers address and payload together, so it cannot tell where the
  address ends. In promiscuous mode a 3-, 4- or 5-byte split gives the same valid CRC; the
  address length has to be known (5 bytes is the most common setting).
- How reliable is the promiscuous mode compared with the address mode (missed frames)?
- Do the systematic bit errors with native XN297L transmitters disappear with `ble1m` (wider
  deviation), or are they caused by a frequency offset?
