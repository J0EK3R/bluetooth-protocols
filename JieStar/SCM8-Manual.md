# JIESTAR SCM8 – Operating instructions (summary)

> Source: printed bilingual (Chinese / English) leaflet that came with the set: *"J101 主控 – Operating instructions – 机械积木操作说明书"* (mechanical building blocks operating instructions). Photographed 2026-11-14; content summarised and re-worded here, not reproduced.
> Section numbers 1 … 3, 5, 6 follow the leaflet (it has no section 4); sections 7 and 8 are added here.
> Last updated: 2026-11-14

The leaflet calls the receiver **Smart Creative Module** (主控模块, "main control module") and
names it **J101 主控** on the cover. The handset is the **Remote Control** (遥控器). This file lists
what the leaflet says and links each point to the measurements in
[SCM8-Remote.md](SCM8-Remote.md) and [SCM8.md](SCM8.md). Statements of the leaflet are not
verified unless a measurement is linked.

## 1. Package contents

| Item | Leaflet name |
|---|---|
| Receiver | Smart Creative Module (主控模块), "J101" |
| Handset | Remote Control (遥控器) |
| Cable | USB charging cable (专用USB充电线) |

## 2. Product description

### 2.1 Receiver (Smart Creative Module)

| Element | Leaflet | Repo |
|---|---|---|
| Outputs | 8 outputs "Rotary 360°" (动力孔, "power hole") **A … H**: lower row A, C, E, G, upper row B, D, F, H | same layout as the photo in [SCM8.md §8](SCM8.md#8-hardware) |
| Power | push button (开关) | the square button next to the USB socket |
| Indicator light | one indicator light (指示灯) between the pin holes | the small hole between the pin-hole rows ([SCM8.md §8](SCM8.md#8-hardware)) |
| Charging | charging port (充电口) and a separate charging indicator light (充电指示灯) | the USB-C socket and the hole next to it |

### 2.2 Handset (Remote Control)

Front view: two sticks, a round button and the power button in the centre with the indicator
light between them, two button groups below. Back view: battery box for **2 × AAA (1.5 V)**.

Labels of the operation drawing (section 3.1 of the leaflet):

| Leaflet label | Control | Telegram ([SCM8-Remote.md §5](SCM8-Remote.md#5-control-telegram-8-bytes)) |
|---|---|---|
| A Key, B Key | left stick | CH1, CH2 |
| C Key, D Key | right stick | CH3, CH4 |
| E Key, F Key | left button group: E and F twice each (top row E, F; bottom row F, E) | B6 bits 0 … 3 |
| G Key, H Key | right button group: G and H twice each (top row G, H; bottom row H, G) | B6 bits 4 … 7 |
| A/B Switching Forward/Reverse Button (A/B切换正反转按键) | the two shoulder buttons on each side | B7 bits 0 … 3 |
| series (串连) | round button with the ring symbol | not sent as a flag – the handset sends mixed stick values |
| ON/OFF (开关) | power button | – |
| Indicator light (指示灯) | LED between the two centre buttons | – |

## 3. Method of operation

### 3.1 Handset

1. Insert 2 AAA batteries.
2. Switch the handset on – the indicator light **flashes slowly**.
3. The A key drives port A of the receiver, the B key port B, and so on.
   **Confirmed (R4.2):** every control drives the port with its own letter.
4. **Series mode:** pressing the *series* key for 1 s makes the indicator flash once. The E / F /
   G / H keys are then disabled and the ports A, B, C, D are driven together by the A / B / C / D
   keys. Pressing the series key again for 1 s leaves series mode.
   **Measured (R4.6, R4.7):** after the ring button the handset sends CH1 = CH2 = A and
   CH3 = CH4 = `FF` − A (stick A) or all four channels equal (stick B); stick C acts like A and D
   like B; ports A … D run. **Difference:** in R4.7 the handset still sent the B6 bits of E … H in
   series mode – the keys are probably ignored by the receiver, not by the handset (port reaction
   not recorded).
5. **Direction reversal:**
   - the four top (shoulder) buttons, held for 1 s, reverse the direction of ports A, B, C, D;
     **measured (R4.2, R4.5):** each shoulder button toggles one bit of B7, the receiver reverses
     the port;
   - for E, F, G, H the direction is reversed by holding **two** of the keys at the same time for
     1 s – **not measured yet** (capture plan R4.8).

### 3.2 Receiver

1. Hold the power button for 1 s to switch on or off; the indicator light flashes to show the
   state.
2. After the receiver and the handset are paired (对频), the indicator light stays **on**.

### 3.3 Connecting

Switch on the receiver first, then insert the batteries into the handset and switch it on. The
handset connects automatically; the connection is made when the receiver's indicator light stays
on. If the set has not been used for a long time, the leaflet recommends taking the handset
batteries out and inserting them again.

Measured: the handset sends its bind telegram on 2411 MHz from power-on until a receiver answers,
also when it is switched on first ([SCM8-Remote.md §1](SCM8-Remote.md#1-sequence)).

### 3.4 Charging (receiver)

The receiver has a built-in battery. Connect the USB cable to a computer or USB charger and to the
charging port of the receiver. While charging the charging indicator flashes slowly; when the
battery is full it stays on. Charging takes about 4 hours.

## 5. App

The app is installed via a QR code on the leaflet; it needs iOS 9.0 or Android 5.0 or newer (some
Android models may not be supported).

## 6. App operation

- The app can control **up to three receivers at the same time** (module 1, 2, 3).
- After switching on, the receiver's indicator light flashes. Connect via the Bluetooth button in
  the app; when connected, the indicator light stays on.
- **Module selection on the receiver:** the default is module 1. Holding the power button for 1 s
  switches to module 2 (the indicator light flashes rapidly), holding it again for 1 s to module 3.
- In the app the module is selected with the module buttons in the upper right corner.

Repo: this is the device slot of the app protocol – **Device 1 / 2 / 3** with the telegram
identifiers `0x41` / `0x42` / `0x43` ([SCM8.md §3](SCM8.md#3-command-telegram-8-bytes-raw)). The
app screenshots on the leaflet show two virtual sticks with the labels advance / backward /
rotate left / rotate right, the 8 port buttons and the module buttons 1 … 3.

## 7. Notes (safety)

The receiver must not be opened or exposed to mechanical shocks, contains a battery (keep away
from fire and temperatures of 60 °C), must not be charged for a long time, and the set contains
small parts (not for children under three years).

## 8. Open points from the leaflet

| Point | Status |
|---|---|
| Series mode: are E … H really ignored by the receiver? | to check (R4.8) |
| Direction reversal of E … H by holding two keys for 1 s: is it sent in the telegram? | to check (R4.8) |
| Module 1 … 3 selection with the power button: does it affect the handset link? | to check |
| Indicator light behaviour of handset and receiver | LED table in the [capture plan §9](SCM8-Capture-Plan.md#9-recording-the-results) |
