# PowerBox

Protocol descriptions of the PowerBox modules.
Overview of all vendors: [../README.md](../README.md).

The modules are controlled via **BLE advertising** (manufacturer ID `0xFF00`); on air the
telegrams appear as XN297L frames, the same radio layer as Mould King
(see [../Chips/XN297L.md](../Chips/XN297L.md)).

## Contents

| File | Content |
|---|---|
| [A-Series.md](A-Series.md) | PowerBox A Series – 4 analog channels (nibble) |
| [M-Battery.md](M-Battery.md) | PowerBox M Battery – 1 analog channel (special byte, sent twice) |
| [img/](img/README.md) | device images and SVG frame diagrams used by these documents |
