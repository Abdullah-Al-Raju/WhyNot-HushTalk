# 🔇 WhyNot-HushTalk Live Signal Transmission & Verification

An actual live test was performed across two endpoints over local loopback (`127.0.0.1`), demonstrating the end-to-end covert timing channel with a keyed session, fast timing profile, jitter tolerance, and automatic ACK confirmation.

---

## 🎯 Test Configuration

| Parameter | Value | Description |
|---|---|---|
| **Target** | `127.0.0.1` | Local loopback interface |
| **Message** | `"WHYNOT HUSHTALK LIVE"` | 20 characters covert plaintext |
| **Session Key** | `"TESTKEY123"` | Cryptographic shared secret |
| **Profile** | `fast` | 80ms base, 25ms step, ±12ms tolerance margin |
| **Keyed ID** | `42126` | Derived pseudorandom session ID |
| **Start / End Markers** | `seq 120` / `seq 937` | Key-derived framing markers |
| **ACK Confirmation** | Enabled (`--ack`, `--wait-ack 10`) | Reverse burst confirmation |

---

## 📸 Screenshots

### 1. Sender Terminal (`whisper.py`)

The sender converted `"WHYNOT HUSHTALK LIVE"` into 20 micro-timed inter-packet gaps, dispatched the key-derived start marker, transmitted each data packet with precision timing sleeps, sent the end marker, and waited for the ACK.

![Terminal 1: HushTalk Sender](sender.png)

---

### 2. Receiver Terminal (`listen.py`)

The receiver detected the keyed start marker, measured the inter-arrival gaps between successive packets, snapped each interval to the nearest keyed delay slot, unmapped the polyalphabetic keystream, perfectly decoded all 20 symbols, and replied with an ACK burst.

![Terminal 2: HushTalk Receiver](hushtalk-listener.png)

---

## 📊 Live Verification Results

```
========================================================
[DECODED] 'WHYNOT HUSHTALK LIVE'
[+] Status: CLEAN DECODE, 20/20 symbols (0 uncertain)
[+] Telemetry: Duration: 23.6s (0.85 chars/s) | Jitter avg: 2.1ms max: 5.3ms
========================================================
[+] ACK burst sent to 127.0.0.1:34754
```

- **Accuracy**: 100% (20/20 symbols clean, 0 uncertain).
- **Average Jitter**: 2.1 ms (well within the ±12 ms margin).
- **Bidirectional Channel**: Sender successfully received the 3-packet ACK burst.
