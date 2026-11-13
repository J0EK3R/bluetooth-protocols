# XN297L sniffer – Wireshark extcap

Host software that talks to the sniffer firmware over its USB virtual COM port.
Installation and options: [../README.md](../README.md).

| File | Content |
|---|---|
| `xn297l_sniffer.py` | Wireshark extcap interface (streams frames as `DLT_USER0`) **and** console tool (`--print`: prints descrambled, CRC-checked frames). Requires Python 3.8+ and `pyserial` |
| `xn297l_sniffer.bat` | Windows wrapper that runs the Python script with the `py` launcher (Wireshark on Windows needs an executable extcap) |

Example (console mode):

```bash
python xn297l_sniffer.py --list-ports
python xn297l_sniffer.py --print --port COM5 --mode address --address C1C2C3C4C5 --channels 2
```
