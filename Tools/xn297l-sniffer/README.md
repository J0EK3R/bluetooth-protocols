# XN297L sniffer (nRF52840 dongle + Wireshark)

> Receives XN297L frames (2.4 GHz GFSK, see [XN297L](../../Chips/XN297L.md)) with an
> nRF52840 USB dongle and shows them decoded in Wireshark.
> Status: **verified on hardware** with a native XN297L transmitter (promiscuous mode, `nrf1m`)
> and with XN297L frames emulated via BLE advertising (address mode, `ble1m`), see [Status](#status).
>
> Since firmware 2.0.0 the same dongle also works as a **Bluetooth LE sniffer** (advertising scan
> with device list in Wireshark, see [section 6](#6-bluetooth-le-sniffer)); firmware 2.1.0 adds
> **following a selected device and its connection** (CSA #1/#2, connection / channel map updates).
> Extended advertising and decryption (feature parity with the nRF Sniffer for Bluetooth LE) are
> planned in further steps. Status of the BLE part: advertising scan tested on hardware (works),
> connection following implemented and unit tested, **not yet tested on hardware**.

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
| `extcap/xn297l_sniffer.py` | Wireshark extcap (interfaces `xn297l` and `xn297l_ble`) **and** console tool (`--print`) |
| `extcap/ble_*.py` | helper modules of the BLE interface (pcap/PHDR output, PDU parser, session and device list, toolbar control channel) |
| `extcap/xn297l_sniffer.bat` | Windows wrapper for the extcap |
| `wireshark/xn297l.lua` | Wireshark dissector |
| `tests/` | unit tests: XN297L decoder (Python and Lua), BLE host side |

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

1. With the dongle plugged in, press the button **once**. The RGB LED turns green and a drive
   **UF2BOOT** appears (tested with UF2 bootloader 0.2.13).
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
| `mode <m>` | receiver backend, stops the receiver: `xn297l` or `ble` (firmware 2.0). After boot and whenever a host opens the port the mode is `xn297l` | `xn297l` |
| `bch <list>` | BLE: advertising channels to scan, subset of `37,38,39` in hop order (no repeats) | `37,38,39` |
| `bdwell <ms>` | BLE: time per advertising channel, `0` = stay on the first | `300` |
| `brssi <dBm>` | BLE: hide advertising packets weaker than this (-127 … 0, -127 = off) | `-127` |
| `badv on|off` | BLE: "only advertising", never follow connections | `off` |
| `bfollow off\|<addr>[,<type>]` | BLE (firmware 2.1): follow a device. `<addr>` = 6 hex bytes in display order (`AABBCCDDEEFF` or `AA:BB:CC:DD:EE:FF`), `<type>` `0` public / `1` random (default: either). Only its advertising packets (and scan requests / responses) are reported, its CONNECT_IND is caught and the connection is followed. `off` = report all devices. A change restarts the receiver | `off` |
| `bconn on\|off` | BLE: follow the connections of the followed device | `on` |
| `brsp on\|off` | BLE: report scan requests / responses of the followed device | `on` |
| `info` / `help` | show configuration / commands | |

Answers: `OK`, `E <error>`, `I <info>` and for every frame

```
P <device time µs> <channel> <RSSI dBm> <sync word + captured bytes as hex>
P 1256623 2 -55 2675882844 09AD4A0CAF8D7A58...
```

In BLE mode every packet is reported as

```
B <t_us> <ch> <rssi> <phy> <flags> <evt> <hex>
B 4126532 37 -58 1 01 0 D6BE898E4009665544332211020106...ABCDEF
```

| Field | Meaning |
|---|---|
| `t_us` | device time (µs, wraps after 71 min; the host unwraps) of the packet start (first preamble bit) |
| `ch` | BLE channel index 0 … 39 (37/38/39 = advertising), not the frequency |
| `rssi` | dBm |
| `phy` | 1 = LE 1M (2 = 2M, 3/4 = coded, reserved for later releases) |
| `flags` | hex bit field: `01` CRC ok, `02` slave → master (otherwise master → slave), `04` data channel packet of a followed connection, `20` first packet of a connection event (anchor), `40` gap anomaly (the spacing to the previous packet of the event is not 150 µs ± 20 µs: a packet was probably missed). `08` (aux) and `10` (truncated) are reserved |
| `evt` | connection event counter (0 for advertising) |
| `hex` | access address + PDU header (2 B) + payload + CRC (3 B), de-whitened, on-air byte order. The access address is `D6BE898E` for advertising packets and the one of the connection for data packets. Packets with a bad CRC are reported too (flag bit 0 = 0) |

Status lines about a followed connection (only with `bfollow`; `int` in 1.25 ms, `to` in 10 ms units,
`t` = device time in µs):

```
I conn new aa=50655A21 crcinit=123456 int=24 lat=0 to=200 map=FFFFFFFF1F hop=7 chsel=2 sca=5 t=4126532
I conn upd evt=6 int=40 lat=0 to=300 map=FFFFFFFF1F t=4376532
I conn lost reason=timeout|terminate|establish evt=123 t=9126532
```

`new` follows the report of the CONNECT_IND, `upd` is sent when a connection update or channel map update
takes effect (at its instant), `lost` when the supervision timeout expired (`timeout`), an LL_TERMINATE_IND was
seen (`terminate`) or no packet was heard after the CONNECT_IND (`establish`); the scan for the device then
resumes.

Output is queued in a ring buffer and never blocks the receiver; if the host reads too slowly,
reports are dropped and announced with `I drop n=<count>` (hosts ignore unknown `I` lines).
`info` additionally shows `mode=xn297l|ble caps=ble` (and the BLE settings in BLE mode).

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
cd tests && python3 -m unittest      # all tests, standard library only
python tests/test_decoder.py         # decoder tests only
```

The reference frames are generated with an independent encoder in the BLE/LSB-first
formulation (same as in the [MK4.0](../../MouldKing/MK4.0.md) encoder) and must be decoded
correctly by both the Python and the Lua decoder (Lua 5.1 … 5.4).

---

## 6. Bluetooth LE sniffer

With firmware 2.0.0 the dongle can sniff Bluetooth LE without swapping the firmware. A second extcap
interface **BLE sniffer (nRF52840 dongle)** (`xn297l_ble`) delivers LE packets with link type
`LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR` (256), so Wireshark's built-in Bluetooth LE dissector decodes
them (no Lua plugin needed). The XN297L interface is unchanged.

Compared with the [nRF Sniffer for Bluetooth LE](../nrf-sniffer-ble/README.md) (feature list of 4.1.x):

| Feature | Status |
|---|---|
| Advertising on 37/38/39 (LE 1M), RSSI, CRC flag, bad-CRC packets kept | implemented (not yet tested on hardware) |
| Advertising hop sequence (toolbar *Adv Hop*), RSSI filter, *Defaults*, status bar | implemented |
| Device list in the toolbar (name, address, RSSI; most recent 50, stale entries removed after 30 s) | implemented |
| Option *Only advertising packets* | implemented |
| Selecting a device to follow in the toolbar, CONNECT_IND, channel map / hop, CSA #1 and #2, window widening, both directions, More Data, connection update and channel map update at their instants, LL_TERMINATE_IND, supervision timeout, scan request / response following | implemented in firmware 2.1.0 (unit tested incl. the C logic, **not yet tested on hardware**) |
| Extended advertising (AUX chains), 2M and Coded PHY, *Only legacy advertising* | planned |
| Decryption (Legacy passkey / OOB, LTK) | planned |

### 6.1 Installation

Same as in [section 3.1](#31-installation), but copy **all** `extcap/*.py` files (the `ble_*.py` modules
must be in the same folder as `xn297l_sniffer.py`; on Windows also `xn297l_sniffer.bat`) and flash
the firmware **2.1.0** (`firmware/prebuilt/`). With an older firmware the capture stops with
the message "does not support the BLE sniffer" (2.0.0 has no connection following: "cannot follow a device").

### 6.2 Capturing in Wireshark

1. Plug in the dongle, flash the 2.1.0 UF2 once (section 2.1), close every terminal program on the port.
2. Start Wireshark (restart it after copying the files). The interface list shows **BLE sniffer
   (nRF52840 dongle)** with its own toolbar. If it does not, check *Help - About Wireshark - Folders -
   Extcap path* and try *Capture - Refresh Interfaces*.
3. Gear icon: set the serial port. Options: *Only advertising packets*, *Advertising channel hop
   sequence* (default `37,38,39`), *RSSI filter* (default -127 = off), *Dwell time*,
   *Follow scan requests and responses*, *Follow device* (optional start value).
4. Start the capture (double click). The toolbar *Interface Toolbars - BLE sniffer* shows
   **Device** (selector; entries `AA:BB:CC:DD:EE:FF "name" -62 dBm` appear while advertising packets
   arrive), **Adv Hop**, **RSSI filter** and **Defaults**; the status bar shows messages of the sniffer.
   **Following a connection:** select the device in **Device** (the choice is sent to the dongle at once;
   *All advertising devices* switches following off again). From then on only that device's advertising
   packets are captured, and when a central connects to it (CONNECT_IND) the status bar says
   "Following connection ..." and all data packets of the connection appear (both directions, *LE LL*
   with direction M→S / S→M, LL control PDUs such as LL_VERSION_IND, LL_FEATURE_REQ, connection and channel
   map updates, LL_TERMINATE_IND; ATT/GATT/L2CAP are decoded on top). Start the connection **after**
   selecting the device (the CONNECT_IND must be seen). The status bar reports updates and the end of the
   connection ("supervision timeout", "terminated").
5. Packets appear as *LE LL* with the BLE dissector. Display filters: `btle.advertising_header.pdu_type == 0`
   (ADV_IND), `btle.advertising_address == 11:22:33:44:55:66`, `btle.length`, `btle.crc`. Bad-CRC packets are
   marked in the packet details (CRC *incorrect*).

Console mode: `python extcap/xn297l_sniffer.py --print --interface xn297l_ble --port COM5 --adv-hop 37,38,39 --rssi-filter -80`
prints one line per packet and the devices found. Options: `--only-advertising`, `--adv-hop`, `--rssi-filter`,
`--adv-dwell`, `--follow AA:BB:CC:DD:EE:FF[,0|1]`, `--scan-follow-rsp` (Wireshark enables the latter by default;
on the command line pass it explicitly).

### 6.3 Record format (DLT 256)

Per record: a 10 byte pseudo header (RF channel `(f - 2402 MHz) / 2`, signal power, noise power 0,
access address offenses 0, reference access address, flags) followed by access address + PDU + CRC without
preamble. Flags set by the sniffer: de-whitened, signal power valid, reference access address valid (advertising access
address or the one of the followed connection), CRC checked, CRC valid (if the hardware CRC check passed), and
for connection packets the PDU type *data, master to slave* / *data, slave to master*. Packet time = start time of the capture + device time
since the first packet. Format: <https://www.tcpdump.org/linktypes/LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR.html>.
The PHY is not representable in the record except for the PHY bits of the flags (used from the 2M/Coded support on).

### 6.4 Known limits (current release)

- Hardware timing constants (offset of the packet start to the ADDRESS event, RSSI) are not calibrated yet.
- The CRC bytes of the record are the value of the `RXCRC` register; the *CRC valid* flag is authoritative.
- The single radio hops over the advertising channels (dwell 300 ms by default): packets of an advertiser on the
  other two channels are missed like with any single-radio sniffer; choose one channel and a dwell of 0 to
  watch one channel continuously. With a followed device the scan is aligned with the advertiser (after its
  packet the next channel is listened to for 20 ms), so its CONNECT_IND is caught on any of the three channels,
  but a connection made while the sniffer listens on another channel is missed. The first connection event
  after the CONNECT_IND is the most critical one: if it is missed the sniffer has to find the next anchor in a
  window that keeps growing; if no packet is heard within 6 events the connection is given up ("establish").
- Connection following: LE 1M PHY only (no LL_PHY_UPDATE_IND to 2M / Coded, no AUX_CONNECT_REQ, legacy
  CONNECT_IND only), the connection must start while the sniffer follows the device. The window widening
  assumes the master's worst case clock accuracy from the CONNECT_IND (SCA) plus 50 ppm for the sniffer.
- Direction is derived from the position of the packet in the event (first = master). If the master packet of an
  event is missed and only the slave answer is heard, it is labelled M->S (and the *gap* flag is not set for it);
  this cannot be fixed without SN/NESN tracking.
- Encrypted connections: LL_ENC_REQ / ENC_RSP / START_ENC_REQ are seen in clear, afterwards LL control PDUs
  cannot be read. The sniffer keeps following with the parameters it knows; if a connection update or channel
  map update is sent while encrypted, it cannot learn the instant and the connection is lost (supervision
  timeout) and has to be found again by reconnecting. The payload stays encrypted (decryption is planned).
- The RSSI filter applies to advertising packets only; packets of a followed connection are never filtered.
  The device list only shows advertising devices (connection packets do not change it).
- While following a connection no other advertising traffic is captured.

---

## Status

| Part | Verified |
|---|---|
| Firmware build (Zephyr 3.7.0, SDK 0.16.8), UF2 at `0x1000` | ✅ (2.1.0 rebuilt without warnings, 47.5 kB flash, 34.9 kB RAM) |
| BLE sniffer advertising scan (firmware 2.0.0 / 2.1.0, interface `xn297l_ble`) | host side unit tests ✅; hardware test by the user: "looks good" |
| BLE connection following (firmware 2.1.0): channel selection #1 / #2 (Core Spec sample data), follow logic (C code compiled on the host and compared with a Python model), host side | unit tests ✅; **not yet tested on hardware / in Wireshark** |
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
