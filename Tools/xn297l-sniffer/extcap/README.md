# XN297L sniffer – Wireshark extcap

Host software that talks to the sniffer firmware over its USB virtual COM port.
Installation and options: [../README.md](../README.md).

| File | Content |
|---|---|
| `xn297l_sniffer.py` | Wireshark extcap interface (streams frames as `DLT_USER0`) **and** console tool (`--print`: prints descrambled, CRC-checked frames; `--mode raw`: prints the bytes after any sync word undecoded). Requires Python 3.8+ and `pyserial` |
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
