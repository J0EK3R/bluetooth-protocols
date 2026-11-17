# XN297L sniffer – Wireshark extcap

Host software that talks to the sniffer firmware over its USB virtual COM port.
Installation and options: [../README.md](../README.md).

| File | Content |
|---|---|
| `xn297l_sniffer.py` | Wireshark extcap with two interfaces: `xn297l` (frames as `DLT_USER0`) and `xn297l_ble` (Bluetooth LE, DLT 256). **Also** console tool (`--print`: prints descrambled, CRC-checked frames; `--mode raw`: prints the bytes after any sync word undecoded; `--interface xn297l_ble`: BLE). Requires Python 3.8+ and `pyserial` |
| `ble_phdr.py` | pcap file header and records for link type 256, RF channel mapping, pseudo header flags |
| `ble_pdu.py` | advertising PDU parser (type, advertiser address, name from the AD structures, extended advertising AdvA) |
| `ble_session.py` | `B`/`I` line parser (incl. `I conn ...`), 32 bit timestamp unwrap, device table (limit 50, stale after 30 s), RSSI filter (advertising only), pcap record builder with data channel direction |
| `ble_control.py` | extcap control channel (interface toolbar): message framing, reader/writer threads |
| `xn297l_sniffer.bat` | Windows wrapper that runs the Python script with the `py` launcher (Wireshark on Windows needs an executable extcap) |

Example (console mode):

```bash
python xn297l_sniffer.py --list-ports
python xn297l_sniffer.py --print --port COM5 --mode address --address C1C2C3C4C5 --channels 2
python xn297l_sniffer.py --print --port COM5 --mode raw --sync AAAAAA --channels 0-83 --dwell 50
```

## Options in the Wireshark "Interface Options" dialog

The options are grouped into three tabs. Each option has a tooltip that names the
modes it is used in and the allowed values. The `--call` names are the command line
options of the script (usable with `--print`).

| Tab | Option (`--call`) | Used in mode | Allowed values |
|---|---|---|---|
| General | Serial port (`--port`) | all | e.g. `COM8`, `/dev/ttyACM0` |
| General | Sync mode (`--mode`) | all | `address`, `promiscuous`, `raw` |
| General | RF channels (`--channels`) | all | channel = MHz - 2400, 0..100; single channels and ranges `n-m` mixed, e.g. `2,26,80`, `0-83`, `1,20,30,40-83`; max. 84 channels in total |
| General | Dwell time (`--dwell`) | all | 0..60000 ms, 0 = stay on the first channel |
| General | Data rate (`--rate`) | all | `nrf1m`, `ble1m`, `nrf2m` |
| XN297L (address / promiscuous) | Address, TX_ADDR order (`--address`) | address only | 3..5 bytes hex |
| XN297L (address / promiscuous) | Address length (`--address-length`) | promiscuous only | 3, 4, 5 bytes |
| XN297L (address / promiscuous) | Payload length (`--payload-length`) | address + promiscuous | 0..64, 0 = find via CRC |
| XN297L (address / promiscuous) | Scrambler off (`--no-scramble`) | address + promiscuous | on / off |
| XN297L (address / promiscuous) | Extra bytes (`--extra-bytes`) | address + promiscuous | 0..200 (total capture max. 250 bytes) |
| Raw mode | Sync word (`--sync`) | raw only | 3..5 bytes hex, on-air order |
| Raw mode | Capture length (`--raw-length`) | raw only | 1..250 bytes |

The RF channel field has a `{validation}` regular expression, so Wireshark marks an
invalid list red (numbers 0..100, ranges, comma separated, spaces tolerated). A regex
cannot check `n <= m` or the 84 channel limit; `parse_channels()` in the script does
that before anything is sent to the dongle and exits with a clear error message.

## BLE interface (`xn297l_ble`, firmware 2.1.0 or newer)

Install all `ble_*.py` next to `xn297l_sniffer.py`. Details and Wireshark steps: [../README.md](../README.md#6-bluetooth-le-sniffer).

| Tab | Option (`--call`) | Allowed values |
|---|---|---|
| General | Serial port (`--port`) | e.g. `COM8`, `/dev/ttyACM0` |
| General | Only advertising packets (`--only-advertising`) | on / off |
| General | Advertising channel hop sequence (`--adv-hop`) | any of 37, 38, 39 in hop order, e.g. `37,38,39` |
| General | RSSI filter (`--rssi-filter`) | -127 ... 0 dBm, -127 = off |
| General | Dwell time (`--adv-dwell`) | 0 ... 60000 ms |
| General | Follow scan requests and responses (`--scan-follow-rsp`) | on / off (default on in Wireshark; pass the flag on the command line) |
| General | Follow device (`--follow`) | empty = all devices, or `AA:BB:CC:DD:EE:FF` optionally `,0` public / `,1` random |

Argument numbers 100 ... 106 (the XN297L interface keeps 0 ... 11). Toolbar controls (number: control):
0 Device (selector, filled at run time), 3 Adv Hop, 4 RSSI filter, 5 Defaults (button, role restore);
numbers 1 and 2 are reserved for the key controls of the planned decryption support. Toolbar changes are sent to the
dongle while the capture is running (`bch`, `brssi`, `bfollow`). Selecting a device in the *Device* selector sends
`bfollow AABBCCDDEEFF,<type>` (the dongle then follows its connection and reports `I conn ...` lines, shown in the
status bar); *All advertising devices* and *Defaults* send `bfollow off`. Data channel packets are written with the
PDU type *data, master to slave* / *slave to master* in the pseudo header.
