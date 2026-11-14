# XN297L sniffer – Wireshark dissector

Lua dissector for the frames delivered by the [extcap](../extcap/README.md) (link type `DLT_USER0`).
Back to the tool: [../README.md](../README.md).

| File | Content |
|---|---|
| `xn297l.lua` | shows the pseudo header (channel, frequency, RSSI, …), removes the scrambler, finds the payload length via the CRC, shows address, payload and CRC status, and hands the payload to the dissector table `xn297l.address` for device-specific dissectors; raw captures (flag bit 2, `--mode raw`) are shown undecoded as sync word + bytes (protocol *RAW 2.4G*) |

Installation: copy `xn297l.lua` into Wireshark's personal Lua plugins folder
(*Help → About Wireshark → Folders → Personal Lua Plugins*).
