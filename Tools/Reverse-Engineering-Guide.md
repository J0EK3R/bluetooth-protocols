# Decoding the radio link of a new device – working together with an AI

> How the protocols in this repository were worked out: a person with the hardware and the
> nRF52840 dongle, and an AI assistant (Claude Code) that plans the measurements, analyses the
> captures and writes the documentation. The examples come from the
> [JIESTAR SCM8 handset](../JieStar/SCM8-Remote.md) and the [CaDA CJV8011 / CJV1010](../CaDA/CJV8011.md)
> investigations ([capture plan with all runs](../CaDA/CJV8011-Capture-Plan.md)).
> Last updated: 2026-11-15

## Contents

1. [Division of work](#1-division-of-work)
2. [Phase 0 – Collect what is known before measuring](#2-phase-0--collect-what-is-known-before-measuring)
3. [Phase 1 – Write a capture plan](#3-phase-1--write-a-capture-plan)
4. [Phase 2 – Find the transmitter](#4-phase-2--find-the-transmitter)
5. [Phase 3 – Lock on and decode the frame](#5-phase-3--lock-on-and-decode-the-frame)
6. [Phase 4 – Map the controls](#6-phase-4--map-the-controls)
7. [Phase 5 – Pairing, IDs, the other direction](#7-phase-5--pairing-ids-the-other-direction)
8. [Using the sniffer](#8-using-the-sniffer)
9. [Analysis techniques](#9-analysis-techniques)
10. [Pitfalls we ran into](#10-pitfalls-we-ran-into)
11. [Documentation and git](#11-documentation-and-git)
12. [Checklist for a new device](#12-checklist-for-a-new-device)

---

## 1. Division of work

| Person | AI |
|---|---|
| owns the hardware: switches devices on / off, moves the controls, opens housings, takes photos | collects product data, reads the photos (chip markings, crystal, board names), suggests hypotheses |
| runs the captures exactly as specified and saves one file per run | writes the capture plan: questions, sessions, runs with **exact** settings |
| writes down what happened that the radio cannot show: order of actions, LEDs, "the motor runs", "the switch jams" | parses the capture files, finds structure, checks hypotheses against **all** frames |
| decides when to stop, what to commit and what to publish | writes the results into the documents, keeps the plan's status current, commits on request |

The loop that worked best:

```
AI: table of runs (state, settings, duration, question)
        │
Person: runs them, puts R<n>.pcapng into one folder, adds short notes
        │
AI: analyses → result table in the plan → device document → next runs
        │
Person: "commit and push"
```

Keep each loop small (2 … 6 runs). A surprising result changes the next runs, so long plans
written in advance are mostly wasted.

---

## 2. Phase 0 – Collect what is known before measuring

- **Product pages and manuals**: channels, controls, batteries, compatibility notes ("only EU
  variant"), pairing hints. Link the sources in the device document.
- **Photos of the opened devices** are the cheapest information source:
  - **Crystal frequency** – it narrows down the radio chip: 16 MHz → XN297L / nRF24L01 class
    (Mould King, JIESTAR); **12 MHz** → other families (CaDA turned out to be DSSS, probably
    Cypress CYRF6936 class).
  - Chip markings (often missing on the RF chip), board names and date codes, antenna, number of
    output drivers.
- **What the user observes in use**: number of states per channel (CaDA: only neutral / plus /
  minus), reversal switches, pairing behaviour, colour coding of ports and controls.

The AI turns this into the overview table of the device document and a list of open questions.

---

## 3. Phase 1 – Write a capture plan

A separate document (`<Device>-Capture-Plan.md`) with:

- **Numbered questions** (C1, C2, … or S1, S2, …) and a status column (open / partly / answered,
  with the run that answered it).
- **Sessions** that group runs by device state (handset alone, handset + receiver, mapping, pairing).
- **Runs** `R<session>.<n>` as tables: device state, sniffer settings (sync mode, sync word, capture
  length, channels, dwell, data rate), duration, question.
- A **result section per session** with measured values only; interpretations are marked
  *interpretation*.
- Fallbacks (SDR, logic analyzer on the SPI bus between MCU and RF chip).

Ask cheap exclusion questions first (is it BLE? is it XN297L?) – they cost minutes and save hours.

---

## 4. Phase 2 – Find the transmitter

Order that worked for the CaDA handset (receiver off, so the handset stays in its bind / search
mode and transmits all the time):

1. **BLE?** nRF Sniffer for BLE, compare a run with everything off against a run with the device on.
2. **XN297L?** XN297L sniffer, promiscuous mode, all channels (`0-83`, dwell 50 ms). Frames with a
   valid CRC answer the question at once (SCM8: found on 2411 MHz in the first run).
3. **Unknown chip:** raw mode with the alternating preamble as sync word:
   - `AAAAAA` and `555555` (both bit phases) × `nrf1m`, `ble1m`, `nrf2m` = 6 runs, 2 minutes each,
     all channels, dwell 50 ms, capture length 64.
   - **Always one reference run with everything off** – Wi-Fi and other devices produce many
     hits, especially with `nrf2m`.
   - Operate the controls continuously during the runs.
4. Look for **bit-identical captures** that occur only with the device on (CaDA: the same 32 bytes
   in 10 of ~250 captures, on 2446 and 2466 MHz, absent in the reference run). The bytes right
   after the preamble are the candidate sync word / start of frame.

If nothing shows up: the preamble may be too short, or the data rate is not 1 / 2 Mbps → SDR.

---

## 5. Phase 3 – Lock on and decode the frame

- Use a sync word taken **from the frame itself**, 5 bytes, and capture the maximum length (250).
  Lock on one channel with dwell 0 to get hundreds of frames per minute.
- If the frame is longer than 250 bytes, use a **second sync word from the middle of the frame**
  to capture its end (CaDA: the frame is 2440 chips; the end marker `1001` was found that way).
- Determine **timing and hopping**: frame interval on one channel (dwell 0), channel order with a
  short channel list and a dwell shorter than the cycle (CaDA: `6,27,46,62`, dwell 9 ms →
  2406 → 2427 → 2446 → 2462 MHz, 7.2 ms apart, cycle 33.6 ms).
- Look at the structure (section 9): repeating blocks, codewords, length, check fields.

---

## 6. Phase 4 – Map the controls

The most productive runs: **one action at a time**, in a fixed order, with neutral pauses
in between, on one channel with dwell 0:

```
10 s neutral
channel 1 plus 5 s – neutral 5 s – minus 5 s – neutral 5 s
channel 2 …, channel 3 …, channel 4 …
then combinations (1+2 plus, 1+2 minus, 3 plus + 4 minus, all plus)
then each reversal switch with all channels plus
```

The person only needs to note the **order**; the AI segments the capture by content changes.
Single actions give the bit / value of each control, combinations show how values combine
(CaDA: masks, 1 + 2 = 3), switch runs show whether a function is applied in the handset or sent as
a flag. Make sure the receiver is connected – in bind mode the CaDA handset does not send the
controls at all.

---

## 7. Phase 5 – Pairing, IDs, the other direction

- Power-cycle the handset several times (is the ID fixed?), use a **second handset** (which bytes
  differ?), pair with another receiver if available.
- Capture the change from bind to operation (CaDA: bind → about 0.3 s link frames → operation).
- The receiver's answer is the hardest part: it may be weak, short, on other channels or in
  another format. Put the dongle **next to the receiver** and the handset far away – RSSI tells
  who is sending.

---

## 8. Using the sniffer

Tool: [XN297L sniffer](xn297l-sniffer/README.md) (nRF52840 dongle, Wireshark extcap or console
`--print`). Raw captures are saved as `.pcapng` per run; the AI reads them directly (the format is
the 12-byte pseudo header described in the tool README, followed by the captured bytes).

| Mode | Sync word | Use |
|---|---|---|
| **address** | known XN297L address | decoding a known XN297L device |
| **promiscuous** | XN297L preamble `71 0F 55` | finding an XN297L device and its address |
| **raw** | any 3 … 5 bytes (`--sync`), `--raw-length` up to 250 | everything else: unknown chips, frame structure, frames longer than one capture |

Settings that matter:

| Setting | Search | Lock on / mapping |
|---|---|---|
| Channels | `0-83` | the found channel(s) |
| Dwell | 50 ms (one sweep ≈ 4.2 s) | `0` (stay) – or a short list with a dwell below the cycle time for the hopping order |
| Capture length | 64 | 250 |
| Data rate | try `nrf1m`, `ble1m`, `nrf2m` | the one that works (`ble1m` tolerates a larger deviation) |
| Duration | 1 … 2 min | 30 s … 1.5 min (device time wraps after 71.6 min) |

Rules learned the hard way:

- **Do not start a lock-on sync word with preamble bytes.** An alternating preamble `AA AA …`
  matches at every even bit offset; the sync `AA 4E 22 C3 2B` caught the normal CaDA frames
  **2 bits late** and looked like a second codeword set. Start the sync after the preamble, or
  check the alignment in the analysis.
- One file per run, named after the run (`R2.4.pcapng`), all in one folder; a run that went wrong
  is repeated with a letter (`R3.3a`).
- Note what the radio cannot see: when the receiver was switched on, whether the motor ran,
  which lever was held.
- Raw captures are not committed – only the results.

---

## 9. Analysis techniques

The AI writes small throw-away Python scripts (pcapng parser, statistics) outside the repository.
Techniques that decided the CaDA case:

| Technique | What it shows | CaDA example |
|---|---|---|
| frames per channel and RSSI, compared with the reference run | where the device transmits | 2446 / 2466 MHz only with the handset on |
| repeated substrings across captures | real frames vs. noise | the same 32-byte block in 10 captures |
| bit-level search with shifts and inversion | the same signal at another bit phase | `555555` runs showed the frame shifted by 1 bit |
| period / linear complexity (Berlekamp–Massey) | test pattern / scrambler vs. data | period 256 bits, not an LFSR |
| cutting the stream into fixed blocks and clustering | codewords / symbols | 16 codewords of 64 chips, ≥ 21 chips apart |
| segmentation of a long capture by content changes | effect of each user action | control state in symbol positions 14 … 17 |
| relations between fields (complement, XOR, rotation) | check fields, related code sets | positions 16 / 17 = 15 − positions 14 / 15 |
| verification over **all** frames | confirms or kills a hypothesis | complement rule true in 5057 of 5057 operation frames |
| anchors for ambiguous assignments | resolves symmetric cases | the black-switch step fixed the values 5 / A and 6 / 9 |

Write down every value with the run that produced it; keep interpretations separate.

---

## 10. Pitfalls we ran into

- **Wi-Fi** looks like a transmitter at 2 Mbps (2431 … 2442 MHz) – always compare with a reference run.
- **Bit-phase locking** on preamble bytes (section 8) – an artefact was documented as a "second
  codeword set" and had to be withdrawn.
- **Human observations can be wrong in a systematic way**: a jammed reversal switch made one
  channel look inverted; in one run all levers were obviously moved the other way. Ask before
  building a special case into the protocol.
- **Truncated captures** (250 bytes) hide the frame end – use a mid-frame sync.
- **Too short runs** give too few frames on a sweep; with dwell 50 ms each channel is heard only
  50 ms per 4.2 s.
- **Over-interpretation**: chip family, IDs, check fields stay *interpretation* until a run or a
  datasheet confirms them.

---

## 11. Documentation and git

- One document per device (`<Vendor>/<Device>.md`) with sources and "Last updated" at the top,
  measured tables, interpretations marked, open questions at the end.
- The capture plan keeps the status of every question and session; results go into the plan
  (with run details) **and** condensed into the device document.
- Images in `img/` next to the documents, credited in the main README.
- Commit after each loop or session with a message that names the runs and the main finding;
  the person decides when to commit and push.

---

## 12. Checklist for a new device

1. Product data, photos (inside: crystal, chips, board names), user observations → device document.
2. Capture plan with questions, sessions, runs.
3. BLE check, XN297L promiscuous sweep.
4. Raw sweeps `AAAAAA` / `555555` × 3 data rates + reference run.
5. Candidate frame → sync from inside the frame → lock on, full length, frame end, timing, hopping.
6. Mapping runs: single actions, combinations, switches.
7. Second handset, power cycles, receiver on / off → IDs and pairing.
8. Receiver direction (dongle next to the receiver).
9. Assessment: can a phone (BLE) or a bridge transmitter reproduce the frames? (see
   [CaDA CJV8011 §3](../CaDA/CJV8011.md#3-control-by-smartphone-or-an-own-transmitter-assessment))
10. Commit, push, update the READMEs.
