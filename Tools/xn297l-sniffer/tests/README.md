# XN297L sniffer – Tests

Unit tests of the XN297L decoder and the BLE host side. Back to the tool: [../README.md](../README.md).

| File | Content |
|---|---|
| `test_decoder.py` | tests the decoder of the [Python extcap](../extcap/README.md) and of the [Lua dissector](../wireshark/README.md) against reference frames built by an independent encoder (BLE-domain formulation: LSB-first bytes, BLE whitening LFSR), plus the raw mode of the extcap (configuration commands, output format, pseudo header flag) |
| `test_ble_phdr.py` | BLE pcap output: RF channel mapping, exact PHDR bytes and flags (CRC, PHY, PDU type), pcap header / record |
| `test_ble_pdu.py` | advertising PDU parsing with hand-built packets (ADV_IND, SCAN_RSP, SCAN_REQ, CONNECT_IND, ADV_EXT_IND, AD names, malformed input) |
| `test_ble_csa.py` | channel selection #1 / #2: Core Spec Vol 6 Part C sample data (access address `0x8E89BED6`), hand calculated #1 sequences, properties; the C code (compiled on the host) is compared with the Python model |
| `test_ble_follow.py` | connection following logic: device filter, CONNECT_IND, first window, anchors, widening, supervision, More Data, direction, gap, connection / channel map update at the instant (also across the event counter wrap), terminate, encryption; every scenario runs on the Python model ([ble_follow_model.py](ble_follow_model.py)) and on the firmware C code (host build, [c/follow_driver.c](c/follow_driver.c)), plus a randomized comparison; needs `cc`/`gcc` for the C part (skipped otherwise) |
| `test_ble_follow_host.py` | host side of following: `I conn ...` lines, data channel packets in the pcap (direction flags), CONNECT_IND / LL control parsing, device selection (`bfollow`), `--follow` |
| `test_ble_session.py` | `B`/`I` line parsing, timestamp unwrap, device table, RSSI filter, control channel framing, extcap output of both interfaces (snapshot of the unchanged `xn297l` options), BLE configuration commands, toolbar handler, end-to-end capture with a fake dongle (pcap file and real control FIFOs) |

Run all tests (standard library only, no pyserial needed):

```bash
cd Tools/xn297l-sniffer/tests && python3 -m unittest          # or: python3 -m unittest discover -s tests
python tests/test_decoder.py                                    # a single file
```

The Lua tests run only if the `lupa` package is installed (`pip install lupa`).
