# XN297L sniffer – Tests

Unit tests for the XN297L decoder. Back to the tool: [../README.md](../README.md).

| File | Content |
|---|---|
| `test_decoder.py` | tests the decoder of the [Python extcap](../extcap/README.md) and of the [Lua dissector](../wireshark/README.md) against reference frames built by an independent encoder (BLE-domain formulation: LSB-first bytes, BLE whitening LFSR) |

Run:

```bash
python tests/test_decoder.py
```

The Lua tests run only if the `lupa` package is installed (`pip install lupa`).
