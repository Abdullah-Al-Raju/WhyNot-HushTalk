<!--
SEO Metadata & Indexing Information
Primary Keywords: ICMP covert channel, timing channel, network steganography, data exfiltration, packet inter-arrival time, detection engineering, SOC analysis, Scapy network security
Author: Abduallah Al Raju
Repository: https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk
-->

# WhyNot-HushTalk

**A Network Protocol Timing-Channel Steganography and Detection Engineering Framework**

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk/actions)
[![Topic: Cybersecurity](https://img.shields.io/badge/topic-cybersecurity-red.svg)](https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk)
[![Topic: Network Steganography](https://img.shields.io/badge/topic-network--steganography-orange.svg)](https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk)

WhyNot-HushTalk is a covert communication suite that encodes alphanumeric messages exclusively within the temporal intervals (inter-arrival delays) separating standard network ping packets. Rather than altering packet header fields or payload contents, information is embedded inside the temporal gaps of the transmission.

Designed and developed by **Abduallah Al Raju**, this framework serves as both an implementation of timing-channel communications and a testbed for Security Operations Center (SOC) analysts and detection engineers researching covert exfiltration telemetry.

---

## Live Verification

The transmission protocol was verified over local loopback using a key-derived polyalphabetic session. Full telemetry and step-by-step logs are documented in the [Verification Report](VERIFICATION_REPORT.md).

### Sender Console (whisper.py)
![HushTalk Sender Console](sender.png)

### Receiver Console (listen.py)
![HushTalk Receiver Console](hushtalk-listener.png)

---

## Theoretical Foundations

In traditional network steganography, data is concealed within unused or mutable header fields (e.g., IP Identification, TCP Initial Sequence Numbers, or ICMP payload padding). Modern Deep Packet Inspection (DPI) engines and Intrusion Detection Systems (IDS) detect these static anomalies using header entropy and payload signature matching.

WhyNot-HushTalk operates at the temporal layer, establishing a pure **timing channel**:

```
Packet Stream:
[Start Marker] ---> (Delay T1) ---> [Data Pkt 1] ---> (Delay T2) ---> [Data Pkt 2] ---> [End Marker]
                         |                                 |
                     Symbol 1                          Symbol 2
```

1. **Information Carrier**: Information exists solely in the metric $\Delta t = t_{i} - t_{i-1}$, representing the duration elapsed between consecutive packet arrivals.
2. **Packet Innocuity**: Packets carry standard ICMP Echo Request payloads (e.g., mirroring standard Windows `ping.exe` or Linux `iputils` implementations). No secret data exists inside packet buffers.
3. **Quantization & Noise Tolerance**: To withstand real-world network jitter, the receiver quantizes measured inter-arrival times against a discretized delay alphabet using a bounded tolerance window ($\pm \delta$).

---

## Protocol Specification

The transmission lifecycle consists of three distinct phases: Session Initialization, Sequential Data Modulation, and Session Termination.

### 1. Alphabet and Symbol Space

The protocol supports a 41-character discrete alphabet ($\Sigma$):

```
ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,?!
```

Each character $c \in \Sigma$ maps to an index $k \in [0, 40]$.

### 2. Delay Function and Timing Profiles

The expected interval $D(k)$ for symbol index $k$ is governed by:

$$D(k) = \text{base} + (k \times \text{step})$$

| Profile Name | Base Delay | Step Increment | Snap Margin | Default Jitter | Target Environment |
|---|---|---|---|---|---|
| `fast` | 80 ms | 25 ms | $\pm$ 12 ms | $\pm$ 5 ms | High-speed LAN, loopback testing (~2.5 chars/sec) |
| `standard` | 500 ms | 100 ms | $\pm$ 45 ms | $\pm$ 30 ms | Default WAN profile (0.3 to 0.5 chars/sec) |
| `stealth` | 2000 ms | 500 ms | $\pm$ 150 ms | $\pm$ 80 ms | Low-frequency evasion against rate-limiting anomaly detection |

### 3. Cryptographic Key Derivation

When initialized with a shared secret key $K$, session parameters are derived deterministically via SHA-256:

$$H = \text{SHA-256}(\text{"hushtalk:"} \parallel K)$$

- **Session ICMP Identifier**: Derived from bytes $H[0:2]$.
- **Framing Markers**: Start sequence number derived from $H[3]$; end sequence from $H[4]$; acknowledgment sequence from $H[5]$.
- **Base and Step Offsets**: Pseudo-randomly shifted using bytes $H[6]$ and $H[7]$.
- **Permuted Symbol Mapping**: A cryptographically seeded permutation of the 41-symbol alphabet prevents direct frequency analysis.
- **Polyalphabetic Keystream Encryption**: Each symbol at position $i$ is shifted along the alphabet modulo 41 via a continuous keystream derived from $\text{SHA-256}(\text{"pad:"} \parallel K)$, ensuring identical consecutive characters produce distinct delays.

```
Plaintext:          A      A      A      A
Key Stream Shift:  +3     +14    +27    +5
Transmitted:        D      O      1      F
Resulting Delay:   155ms  430ms  755ms  205ms
```

### 4. Sequence Alignment and Packet Loss Recovery

Packets are indexed with strictly monotonically increasing sequence numbers:

- If a packet is lost in transit, a sequence gap $g = \text{seq}_{\text{received}} - \text{seq}_{\text{expected}}$ occurs.
- The receiver finite state machine detects the discontinuity, preserves symbol alignment by inserting $g$ unknown markers (`?`), and resynchronizes its reference timestamp to the current packet.

---

## Architectural Workflow

```
+-------------------------------------------------------------+
|                     Sender (whisper.py)                     |
|  1. Text Input -> Cleanse & Uppercase                       |
|  2. Polyalphabetic Scramble (Session Key)                   |
|  3. Quantized Delay Mapping + Synthetic Jitter              |
|  4. Packet Transmission via Raw Sockets or UDP Userland     |
+-------------------------------------------------------------+
                               |
                   [ Network / Loopback Link ]
                               |
+-------------------------------------------------------------+
|                    Receiver (listen.py)                     |
|  1. Capture ICMP/UDP Packet with Arrival Timestamp          |
|  2. Validate Identifier & Filter Source IP                  |
|  3. State Machine: Start Marker -> Data Intervals -> End    |
|  4. Quantize Intervals -> Decrypt Keystream -> Plaintext    |
|  5. Transmit Triple-Burst Acknowledgment Handshake          |
+-------------------------------------------------------------+
```

---

## Core Capabilities

- **Multi-Transport Layer**: Supports standard raw ICMP Echo Requests (`--transport icmp`) for realistic ping covert channel operations, and unprivileged userland UDP probe modulation (`--transport udp`) for testing without root or administrative privileges.
- **IDS Signature Defeat**: Standard ping tools use characteristic payload byte structures. WhyNot-HushTalk can format its payload to match legitimate host implementations:
  - `windows`: Replicates the 32-byte alphabetical sequence of Windows `ping.exe`.
  - `linux`: Emulates the 8-byte kernel timestamp prefix and counter sequence of `iputils-ping`.
  - `random`: Generates cryptographic pseudo-random noise.
  - `zero`: Emulates zeroed diagnostic ping frames.
- **IPv4 and IPv6 Support**: Operates over standard IPv4 (`ICMP type 8`) as well as modern IPv6 infrastructure (`ICMPv6 type 128`).
- **Real-Time Telemetry**: Measures elapsed session time, effective character-per-second throughput, and empirical timing jitter distribution.
- **SIEM / SOC Integration**: Supports structured JSON streaming (`--json`) for ingestion into SIEM platforms (Splunk, Elastic, OpenSearch).
- **In-Memory Simulation Engine**: Provides a zero-dependency CLI simulation runner (`hushtalk.py demo` or `--simulate`) that tests framing, noise models, and loss resynchronization without opening network sockets.

---

## Installation & Prerequisites

### Prerequisites

- Python 3.9 or higher
- Linux, macOS, or Windows
- **Administrative Privileges**: Raw socket capture (ICMP) requires `sudo` / `root` on Linux/macOS or [Npcap](https://npcap.com/) on Windows.
- **Unprivileged Alternative**: When operating in restricted containers or non-root shells, use `--transport udp` or `--simulate`.

### Installation Steps

```bash
git clone https://github.com/Abdullah-Al-Raju/WhyNot-HushTalk.git
cd WhyNot-HushTalk
pip install -r requirements.txt
```

To install the executable binaries directly into your environment PATH:

```bash
pip install -e .
```

---

## Usage Guide

### 1. In-Memory Simulation (No Root Required)

Verify protocol encoding and decoding directly in your console:

```bash
python3 hushtalk.py demo -m "DEFENSE IN DEPTH" --profile fast
```

Or execute via the sender CLI:

```bash
python3 whisper.py --simulate -m "SECURE COMM" --key "alpha-charlie" --profile fast
```

### 2. Live Unprivileged UDP Mode

Run sender and receiver in separate terminal sessions without root permissions:

**Terminal 1 (Listener):**
```bash
python3 listen.py --transport udp --port 9999 --profile fast --key "SECRET_KEY" --ack
```

**Terminal 2 (Sender):**
```bash
python3 whisper.py --to 127.0.0.1 --transport udp --port 9999 --profile fast --key "SECRET_KEY" -m "SYSTEM OK" --wait-ack 10
```

### 3. Live ICMP Ping Mode (Requires Root)

**Terminal 1 (Listener):**
```bash
sudo python3 listen.py --key "ENTERPRISE_KEY" --profile standard --ack
```

**Terminal 2 (Sender):**
```bash
sudo python3 whisper.py --to 192.168.1.100 --key "ENTERPRISE_KEY" --profile standard -m "PING EXFILTRATION" --payload windows --wait-ack 30
```

---

## Command-Line Interface Reference

### Unified Runner (`hushtalk.py`)

```bash
python3 hushtalk.py info [--key KEY] [--profile {standard,fast,stealth}]
python3 hushtalk.py benchmark [--profile {standard,fast,stealth}]
python3 hushtalk.py demo -m "TEXT" [--profile {standard,fast,stealth}] [--key KEY]
python3 hushtalk.py whisper [whisper arguments...]
python3 hushtalk.py listen [listen arguments...]
```

### Sender Options (`whisper.py`)

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--to` | String | Required | Destination IPv4 or IPv6 address |
| `-m`, `--message` | String | Exclusive | Plaintext message string (use `-` for stdin) |
| `--file` | Filepath | Exclusive | Read plaintext payload from file |
| `--key` | String | `None` | Shared cryptographic secret key |
| `--profile` | Choice | `standard` | Timing profile (`standard`, `fast`, `stealth`) |
| `--transport` | Choice | `icmp` | Transport driver (`icmp` for raw sockets, `udp` for userland) |
| `--port` | Integer | `9999` | Destination UDP port when using `--transport udp` |
| `--payload` | Choice | `pattern` | Cover payload structure (`pattern`, `windows`, `linux`, `random`, `zero`) |
| `--payload-len`| Integer | `48` | Payload byte length |
| `--ipv6` | Flag | `False` | Force IPv6 ICMPv6 Echo Request transmission |
| `--jitter` | Float | Profile | Synthetic timing jitter in milliseconds |
| `--gap` | Float | `500.0` | Delay between start marker and initial data frame (ms) |
| `--wait-ack` | Float | `0.0` | Maximum wait time in seconds for confirmation burst |
| `--simulate` | Flag | `False` | Execute in-memory noise simulation without network transmission |
| `--iface` | String | `None` | Egress network interface name |
| `--ttl` | Integer | `None` | Outgoing IP TTL or IPv6 Hop Limit |
| `-v`, `--verbose`| Flag | `False` | Output detailed frame-by-frame transmission telemetry |

### Receiver Options (`listen.py`)

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--iface` | String | `None` | Capture interface (default: listen across all interfaces) |
| `--src` | String | `None` | Source IP filter (discards packets from other senders) |
| `--listen-ip`| String | `""` | IP address to bind when running in UDP transport mode |
| `--transport` | Choice | `icmp` | Transport driver (`icmp` for packet sniffer, `udp` for userland socket) |
| `--port` | Integer | `9999` | UDP listening port when using `--transport udp` |
| `--key` | String | `None` | Shared cryptographic secret key |
| `--profile` | Choice | `standard` | Expected timing profile |
| `--margin` | Float | Profile | Maximum allowable deviation window when quantizing intervals (ms) |
| `--timeout` | Float | Auto | Inactivity duration before terminating pending sessions (seconds) |
| `--ack` | Flag | `False` | Emit reverse acknowledgment burst upon clean message completion |
| `--ipv6` | Flag | `False` | Capture IPv6 ICMPv6 Echo Requests |
| `--json` | Flag | `False` | Stream machine-readable JSON events to stdout |
| `-v`, `--verbose`| Flag | `False` | Print real-time packet arrival sequences |

---

## Defensive Detection Engineering

A critical goal of the WhyNot-HushTalk project is providing telemetry to improve defensive visibility against temporal covert channels.

### 1. Statistical Dispersion (Coefficient of Variation)

Legitimate network ping trains exhibit natural Poisson-like or Gaussian delay distributions influenced by network queueing, operating system scheduling, and router bufferbloat.

A naive timing channel exhibits artificial clustering at discrete interval bins:

$$CoV = \frac{\sigma}{\mu}$$

Where $\sigma$ represents the standard deviation and $\mu$ represents the mean inter-arrival time. Defenses can flag ping sequences where inter-arrival times cluster tightly around discrete multiples of a fixed interval.

### 2. Payload Fingerprinting

Security Operations teams frequently deploy IDS rules checking for unexpected ping payloads. WhyNot-HushTalk provides realistic cover payloads (`--payload windows`, `--payload linux`) to illustrate why payload inspection alone is insufficient to identify sophisticated covert channels.

### 3. Rate Anomaly Detection

Sustained machine-precise ping sequences from non-monitoring endpoints indicate possible command-and-control (C2) or exfiltration activity. Network behavior analytics (NBA) platforms should monitor:

- Hosts transmitting regular ICMP requests exceeding baseline network administration frequencies.
- Outbound ping bursts directed toward external or unfamiliar endpoints without corresponding DNS lookups.

---

## Automated Testing & CI

The test suite validates the framing state machine, cryptographic key derivations, interval snapping margins, synthetic jitter tolerance, and packet construction:

```bash
pytest -v tests/
```

To execute continuous jitter and throughput benchmarking:

```bash
python3 hushtalk.py benchmark --profile fast
```

GitHub Actions workflows run automated tests across Ubuntu, Windows, and macOS runtimes for Python versions 3.9 through 3.14.

---

## Author & Attribution

**Abduallah Al Raju**  
Network Engineer and SOC Analyst  
Creator of the WhyNot Security Research Toolset

- GitHub: [@Abdullah-Al-Raju](https://github.com/Abdullah-Al-Raju)
- Project Series: WhyNot-*

---

## Ethical and Legal Use Notice

WhyNot-HushTalk is developed solely for defensive security research, academic study, authorized penetration testing, and detection rule engineering. Deploying covert channels across networks without explicit, documented authorization from the network owner is illegal and unethical. The author disclaims all liability for misuse of this software.
