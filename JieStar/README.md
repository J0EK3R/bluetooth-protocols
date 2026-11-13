# JIESTAR

Protocol descriptions of the JIESTAR Smart Creative Modules (SCM) and of the original SCM8 handset.
Overview of all vendors: [../README.md](../README.md).

The modules are controlled via **BLE advertising** (manufacturer ID `0xFFF0`); on air the
telegrams appear as XN297L frames, the same radio layer as Mould King
(see [../Chips/XN297L.md](../Chips/XN297L.md)).

## Contents

| File | Content |
|---|---|
| [SCM4.md](SCM4.md) | SCM4 module – 4 analog channels (nibble) × 3 devices, slot = BLE channel 37/38/39 |
| [SCM8.md](SCM8.md) | SCM8 module – 8 analog channels (nibble) × 3 devices, one telegram per device; receiver photos |
| [SCM8-Remote.md](SCM8-Remote.md) | original SCM8 2.4 GHz handset – native XN297L frames, measured with the [XN297L sniffer](../Tools/xn297l-sniffer/README.md): binding, channel hopping, telegram layout; handset photos |
| [SCM8-Capture-Plan.md](SCM8-Capture-Plan.md) | step-by-step measurement plan for the SCM8 handset (in progress, results go to SCM8-Remote.md) |
| [img/](img/README.md) | device images, photos and SVG frame diagrams used by these documents |
