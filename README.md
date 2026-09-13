# 🔇 WhyNot-HushTalk

**Hide secret messages inside network ping delays. No encryption. No special packets. Hidden in the timing.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> A covert messaging system that encodes text as delays between ICMP ping packets. A timing channel, the same technique real malware has used to signal across restricted networks — built to understand how detection works.

## 🎯 How It Works

Each symbol is carried by the **time between two packets**, not by packet contents. Packets look like ordinary pings; the message lives in the gaps.

| Step | What Happens |
|------|--------------|
| 1 | Sender converts `HELLO` to delays: `[1200, 900, 1600, 1600, 1900]` ms |
| 2 | Pings go out with those delays between them (± jitter), framed by start/end marker pings |
| 3 | Receiver measures inter-arrival times and snaps each to the nearest expected delay |
| 4 | With a `--key`, the marker sequence numbers, ICMP id, delay set **and** symbol mapping are all derived from the key — without it you cannot even tell which pings are part of a message |

**Protocol:** `start marker → data pings (delay after ping i = symbol i) → end marker`
The last symbol is carried by the interval between the final data ping and the end marker. Sequence numbers are contiguous, so lost pings are detected and symbol alignment is preserved (lost symbols become `?`).

## 🚀 Quick Start

```bash
pip install -r requirements.txt
```

Linux/macOS need root for raw sockets (`sudo`). **Windows needs [Npcap](https://npcap.com/)** installed, both for sending and capturing.

**Terminal 1 — listen:**
```bash
sudo python3 listen.py                      # plain codebook mode
sudo python3 listen.py --key SECRET         # keyed mode
```

**Terminal 2 — send:**
```bash
python3 whisper.py --to 127.0.0.1 -m "HELLO"
python3 whisper.py --to 192.168.1.100 -m "SECRET" --key SECRET --wait-ack 30
```

**Keyed sender + keyed receiver:**
```bash
sudo python3 listen.py --iface eth0 --src 192.168.1.50 --key SECRET --ack
python3 whisper.py --to 192.168.1.100 --key SECRET --file message.txt
```

### Flags

| `whisper.py` | |
|---|---|
| `-m` / `--file` | message text (`-` reads stdin) or file |
| `--key` | shared secret (must match receiver) |
| `--jitter` | ± ms of timing noise per symbol (default 30, `0` off) |
| `--gap` | ms between start marker and first ping (default 500) |
| `--wait-ack N` | wait up to N s for the receiver's ack burst |
| `--iface`, `--ttl` | egress interface / IP TTL |

| `listen.py` | |
|---|---|
| `--iface` | capture interface (default: all) |
| `--src` | ignore pings from anyone else |
| `--key` | shared secret (must match sender) |
| `--margin` | max ms deviation accepted when snapping to a symbol (default 45) |
| `--timeout` | seconds of silence before abandoning a message (default: auto from delays) |
| `--ack` | reply with an ack burst after each successful decode |

## 🧪 Tests

The whole protocol (framing, jitter tolerance, loss resync, keyed mode) runs in pure Python — no network, no root:

```bash
python3 -m unittest discover -s tests -v
```

## 🔐 What the key actually does

With `--key`, everything a defender could pattern-match on becomes key-dependent:

| Parameter | Without key | With key |
|---|---|---|
| ICMP id | fixed `12345` | derived from key |
| start / end / ack markers | `100 / 999 / 0` | derived from key |
| delays | codebook (100 ms steps) | key-selected set + permutation |
| symbol stream | plain codebook chars | polyalphabetic shift (same letter → different delay each time) |

Without the key you see a stream of ICMP echo requests. With timing analysis you could still *detect* suspicious regularity; you cannot decode or even bound which packets belong to which message.

## 🛰 Detection (be honest about it)

Calling this "undetectable" would be marketing. What detection **can** do:

- **Timing histograms** — inter-arrival peaks at fixed symbol offsets, unlike natural jitter
- **Marker/ICMP-id signatures** — trivial for the unkeyed demo mode
- **Rate profiling** — sustained machine-precise ping trains are anomalous for most hosts

Mitigations built in: randomized session parameters, jitter, padded payloads, source filtering. Mitigations that remain your problem: overall send-rate entropy and cover traffic. Classic covert-channel tradeoff: throughput buys stealth and vice versa (~0.2–0.5 chars/s here by design).

## 📁 Files

| File | Purpose |
|---|---|
| `hushtalk_core.py` | protocol: framing, keyed sessions, encoder, resyncing receiver FSM (pure stdlib, unit-testable) |
| `whisper.py` | sender CLI (scapy) |
| `listen.py` | receiver CLI (scapy) |
| `codebooks/codebook.json` | plain-mode delay table |
| `tests/` | protocol simulation tests (`python -m unittest`) |

## ⚠️ Ethical Use

Only run this on networks you own or have explicit permission to test. Unauthorized covert-channel use is a crime in most jurisdictions. The repo exists to make detection better, not weaker.

## 👤 Author

Raju (Abdullah Al Raju) — Network engineer / SOC analyst.
Building extreme tools for a German Ausbildung. WhyNot-* series.
