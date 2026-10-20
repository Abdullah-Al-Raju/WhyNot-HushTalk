# 🔇 WhyNot-HushTalk

**Hide secret messages inside network ping delays. No encryption. No special packets. Hidden in the timing.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk/actions/workflows/ci.yml/badge.svg)](https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk/actions)

> A covert messaging system that encodes text as delays between ICMP ping packets. A timing channel, the same technique real malware has used to signal across restricted networks — built to understand how detection works.

---

## 🎯 How It Works

Each symbol is carried by the **time between two packets**, not by packet contents. Packets look like ordinary pings; the message lives in the gaps.

| Step | What Happens |
|------|--------------|
| 1 | Sender converts `HELLO` to delays: `[1200, 900, 1600, 1600, 1900]` ms (or fast LAN profile) |
| 2 | Pings go out with those delays between them (± jitter), framed by start/end marker pings |
| 3 | Receiver measures inter-arrival times and snaps each to the nearest expected delay |
| 4 | With a `--key`, the marker sequence numbers, ICMP id, delay set **and** symbol mapping are all derived from the key — without it you cannot even tell which pings are part of a message |

**Protocol:** `start marker → data pings (delay after ping i = symbol i) → end marker`
The last symbol is carried by the interval between the final data ping and the end marker. Sequence numbers are contiguous, so lost pings are detected and symbol alignment is preserved (lost symbols become `?`).

---

## ✨ Features (v2.1)

- 🧪 **Root-Free Simulation**: Run full end-to-end transmissions in memory with `--simulate` or `hushtalk demo` — zero privileges or network stack required.
- ⚡ **Timing Profiles**: Choose `--profile fast` for high-throughput LANs (~2.5 chars/s), `standard` for realistic WAN delays, or `stealth` for low-frequency exfiltration.
- 🛡️ **Realistic Cover Payloads**: Defeat static IDS signatures by mimicking Windows `ping.exe`, Linux `iputils`, pseudo-random bytes, or zero-byte payloads (`--payload windows|linux|random|zero`).
- 🌐 **IPv6 & IPv4**: Native support for both IPv4 ICMP and IPv6 ICMPv6 (`--ipv6` or auto-detected).
- 📊 **Telemetry & SIEM Output**: Live jitter tracking, throughput calculation (chars/sec), and `--json` streaming events for SOC/SIEM pipeline integration.
- 🔄 **Unified CLI**: Run via `python3 hushtalk.py {whisper,listen,demo,info,benchmark}` or standalone scripts `whisper.py` and `listen.py`.

---

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk.git
cd WhyNot-HushTalk
pip install -r requirements.txt
```

*(Optional: install as editable CLI package)*
```bash
pip install -e .
```

### 2. Immediate Demo (No Root / No Network Required)

Test the complete encode/decode pipeline immediately:
```bash
python3 hushtalk.py demo -m "HELLO FROM HUSHTALK" --profile fast
# or
python3 whisper.py --simulate -m "SUPER SECRET" --key "my-passphrase"
```

### 3. Live Network Usage

> **Note on Permissions:** Linux/macOS raw sockets require `sudo` or `CAP_NET_RAW`. **Windows needs [Npcap](https://npcap.com/)** installed.

**Terminal 1 — listen:**
```bash
sudo python3 listen.py                           # standard mode
sudo python3 listen.py --profile fast            # fast LAN mode
sudo python3 listen.py --key SECRET --profile fast --ack # keyed + fast mode
```

**Terminal 2 — send:**
```bash
python3 whisper.py --to 127.0.0.1 -m "HELLO"
python3 whisper.py --to 192.168.1.100 -m "SECRET" --profile fast --key SECRET --wait-ack 30
```

**IPv6 Transmission:**
```bash
sudo python3 listen.py --ipv6 --key SECRET
python3 whisper.py --to "fe80::1" --key SECRET -m "SECRET IPV6"
```

---

## ⚙️ CLI Reference

### Unified Runner (`hushtalk.py`)
```bash
python3 hushtalk.py info [--key KEY] [--profile {standard,fast,stealth}]
python3 hushtalk.py benchmark [--profile {standard,fast,stealth}]
python3 hushtalk.py demo -m "TEXT" [--profile {standard,fast,stealth}] [--key KEY]
python3 hushtalk.py whisper [whisper flags...]
python3 hushtalk.py listen [listen flags...]
```

### Sender Flags (`whisper.py`)

| Flag | Description |
|---|---|
| `--to IP` | Target IPv4 or IPv6 address (auto-detects IPv6 if `:` in IP) |
| `-m` / `--file` | Message text (`-` reads stdin) or file path |
| `--key` | Shared secret key (keys markers, delays, and symbols) |
| `--profile` | `standard` (default), `fast` (LAN / lab), `stealth` (low rate) |
| `--payload` | Cover payload style: `pattern`, `windows`, `linux`, `random`, `zero` |
| `--payload-len` | Payload byte length (default: 48) |
| `--ipv6` | Force IPv6 ICMPv6 Echo Request |
| `--jitter` | ± ms timing noise per symbol (default: auto from profile) |
| `--gap` | ms between start marker and first data ping (default: 500) |
| `--wait-ack N` | Wait up to N seconds for receiver's ACK burst |
| `--simulate` | Run in dry-run simulation mode without network packets |
| `--iface`, `--ttl` | Egress interface / IP TTL (Hop Limit) |

### Receiver Flags (`listen.py`)

| Flag | Description |
|---|---|
| `--iface` | Capture interface (default: all) |
| `--src IP` | Only accept pings from this source IP |
| `--key` | Shared secret key (must match sender) |
| `--profile` | `standard` (default), `fast`, `stealth` |
| `--margin` | Max ms deviation accepted when snapping delay (default: auto from profile) |
| `--timeout` | Seconds of silence before abandoning message (default: auto from profile) |
| `--ack` | Reply with an ACK burst after each successful decode |
| `--ipv6` | Listen for IPv6 ICMPv6 Echo Requests |
| `--json` | Emit structured JSON events (ideal for SIEM / detection pipelines) |

---

## 🧪 Tests & Verification

Run the comprehensive unit test suite (no network or root required):

```bash
pytest -v tests/
# or
python3 -m unittest discover -s tests -v
```

Run the built-in channel noise benchmark:
```bash
python3 hushtalk.py benchmark --profile fast
```

---

## 🔐 What the Key Actually Does

With `--key`, everything an analyst or IDS could pattern-match on becomes pseudorandom and key-dependent:

| Parameter | Without key | With key |
|---|---|---|
| ICMP ID | fixed `12345` | derived from key |
| start / end / ack markers | `100 / 999 / 0` | derived from key |
| delays | codebook table | key-selected set + permutation |
| symbol stream | plain codebook characters | polyalphabetic keystream shift |

Without the key you see ordinary ICMP echo requests. With timing analysis a defender might note timing regularity; they cannot decode the text or identify which packets belong to the session.

---

## 🛰 Detection (Be Honest About It)

Calling timing channels "undetectable" is marketing. What SOC detection **can** do:

- **Timing histograms** — inter-arrival peaks at fixed symbol offsets, unlike natural network jitter.
- **Payload signatures** — mitigated by `--payload windows` or `--payload linux` to mimic legitimate OS diagnostics.
- **Rate profiling** — sustained machine-precise ping trains are anomalous for most endpoints.

**Mitigations built into HushTalk:**
1. Randomized session parameters (keyed markers and IDs)
2. Configurable Gaussian/uniform jitter (`--jitter`)
3. OS cover payloads (Windows / Linux / randomized bytes)
4. Source filtering and ACK confirmations

---

## 📁 Repository Structure

```
WhyNot-HushTalk/
├── hushtalk_core.py      # Core protocol FSM, timing profiles, crypto derivation, simulation
├── hushtalk.py           # Unified CLI suite (info, demo, benchmark, whisper, listen)
├── whisper.py            # Sender CLI (Scapy / raw ICMP)
├── listen.py             # Receiver CLI (Scapy / packet sniffer)
├── codebooks/
│   └── codebook.json     # Standard delay lookup table
├── tests/
│   ├── test_protocol.py  # Protocol simulation and loss resync tests
│   └── test_upgrades.py  # Timing profiles, payloads, IPv6, telemetry tests
├── pyproject.toml        # PEP 621 packaging and project metadata
├── requirements.txt      # Runtime dependencies (scapy, colorama)
└── .github/workflows/
    └── ci.yml            # Multi-OS automated testing matrix
```

---

## ⚠️ Ethical Use

Only run this on networks you own or have explicit permission to test. Unauthorized covert-channel use is prohibited in most jurisdictions. This project exists to advance defensive detection engineering and timing analysis research.

---

## 👤 Author

**Raju (Abdullah Al Raju)** — Network Engineer / SOC Analyst  
Building extreme tools for a German Ausbildung. *WhyNot-\** series.
