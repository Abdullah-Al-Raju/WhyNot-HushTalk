"""WhyNot-HushTalk core: framing, keyed sessions, encoding and decoding.

Pure stdlib so the protocol logic can be unit-tested without scapy,
root privileges or a network stack.
"""

import hashlib
import json
import os
import random

CODEBOOK_DIR = "codebooks"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,?!"
START_MARKER = 100
END_MARKER = 999
ACK_MARKER = 0
ICMP_ID = 12345
MAX_MESSAGE_LEN = END_MARKER - START_MARKER - 2
PAD_PAYLOAD = b"abcdefghijklmnop" * 3


def load_codebook(name="codebook.json", directory=CODEBOOK_DIR):
    path = os.path.join(directory, name)
    with open(path, "r") as f:
        codebook = json.load(f)
    return {str(k).upper(): float(v) for k, v in codebook.items()}


class Session:
    """Protocol parameters for one conversation.

    Without a key the session uses the shared codebook and the public
    markers from v1. With a key, the ICMP id, markers, delay set and symbol
    mapping are all derived from the key, so observers that lack it cannot
    tell which packets belong to a message, let alone decode them.
    """

    def __init__(self, key=None):
        self.key = key
        if key:
            h = hashlib.sha256(("hushtalk:" + key).encode()).digest()
            self.icmp_id = int.from_bytes(h[0:2], "big") or 1
            self.start_seq = 100 + h[3] % 40
            self.end_seq = 900 + h[4] % 40
            self.ack_seq = h[5] % 50
            self.base = 400 + h[6] % 300
            self.step = 150 + (h[7] % 6) * 50
            permutation = list(range(len(ALPHABET)))
            random.Random(h[8:16]).shuffle(permutation)
            self._slot_of = {ch: permutation[i] for i, ch in enumerate(ALPHABET)}
            self._char_of = {v: k for k, v in self._slot_of.items()}
            self._pad = hashlib.sha256(b"pad:" + key.encode()).digest()
        else:
            self.icmp_id = ICMP_ID
            self.start_seq = START_MARKER
            self.end_seq = END_MARKER
            self.ack_seq = ACK_MARKER
            self.base = 0
            self.step = 0
            self._pad = b"\x00"

    def alphabet(self):
        return ALPHABET if self.key else None

    def delays_for(self, message):
        if self.key:
            return [
                self.base + self.step * self._slot_of[ch]
                for ch in self._scramble(message)
            ]
        raise ValueError("unkeyed sessions use delays_from_codebook()")

    def delays_from_codebook(self, message, codebook):
        return [codebook[ch] for ch in message]

    def expected_delays(self, codebook):
        if self.key:
            return [self.base + self.step * slot for slot in range(len(ALPHABET))]
        return [d for _, d in self._table(codebook)]

    def char_for_delay(self, delay_index, codebook):
        if self.key:
            return self._char_of[delay_index]
        return self._table(codebook)[delay_index][0]

    def _keystream(self, i):
        return self._pad[i % len(self._pad)] % len(ALPHABET)

    def map_symbol(self, ch, i):
        return ALPHABET[(ALPHABET.index(ch) + self._keystream(i)) % len(ALPHABET)]

    def unmap_symbol(self, ch, i):
        return ALPHABET[(ALPHABET.index(ch) - self._keystream(i)) % len(ALPHABET)]

    def _scramble(self, message):
        return "".join(self.map_symbol(ch, i) for i, ch in enumerate(message))

    def _table(self, codebook):
        return sorted(((ch, codebook[ch]) for ch in codebook), key=lambda kv: kv[1])


def prepare_message(text, session, codebook):
    allowed = session.alphabet() or set(codebook)
    return "".join(ch if ch in allowed else " " for ch in text.upper())


def encode_delays(message, session, codebook):
    message = prepare_message(message, session, codebook)
    if len(message) > MAX_MESSAGE_LEN:
        raise ValueError(f"message too long: {len(message)} > {MAX_MESSAGE_LEN}")
    if session.key:
        delays = session.delays_for(message)
    else:
        delays = session.delays_from_codebook(message, codebook)
    return delays, message


class Receiver:
    """Timing-channel receiver state machine.

    Feed it ICMP echo requests with (arrival_time_ms, seq). Symbols are
    carried by the interval ending at each data packet; the final symbol is
    the interval between the last data packet and the end marker.
    """

    def __init__(self, session, codebook, margin=45.0, timeout_ms=None, on_event=None):
        self.session = session
        self.codebook = codebook
        self.margin = margin
        self.expected = session.expected_delays(codebook)
        if timeout_ms is None:
            timeout_ms = max(self.expected) + margin + 2000.0
        self.timeout_ms = timeout_ms
        self.on_event = on_event or (lambda ev, data: None)
        self.reset()

    def reset(self):
        self.started = False
        self.symbols = []
        self.prev_ts = None
        self.first_seen = False
        self.expected_seq = None
        self.last_activity = None

    def tick(self, now_ms):
        if (
            self.started
            and self.last_activity
            and now_ms - self.last_activity > self.timeout_ms
        ):
            self.on_event("timeout", {"partial": self.current_message()})
            self.reset()

    def on_packet(self, ts_ms, seq):
        self.tick(ts_ms)
        s = self.session
        if seq == s.start_seq:
            self.reset()
            self.started = True
            self.last_activity = ts_ms
            self.expected_seq = s.start_seq + 1
            self.on_event("start", {})
            return
        if not self.started or seq == s.ack_seq:
            return
        if seq == s.end_seq:
            if self.prev_ts is not None and self.first_seen:
                self._decode_interval(ts_ms - self.prev_ts)
            stats = {
                "message": self.current_message(),
                "symbols": len(self.symbols),
                "uncertain": self.symbols.count(None),
            }
            self.on_event("message", stats)
            self.reset()
            return
        if s.start_seq < seq < s.end_seq:
            self.last_activity = ts_ms
            if seq < self.expected_seq:
                return
            gap = seq - self.expected_seq
            if not self.first_seen:
                self.first_seen = True
                if gap > 0:
                    self.symbols.extend([None] * gap)
                self.prev_ts = ts_ms
                self.expected_seq = seq + 1
                return
            if gap > 0:
                self.symbols.extend([None] * (gap + 1))
            else:
                self._decode_interval(ts_ms - self.prev_ts)
            self.prev_ts = ts_ms
            self.expected_seq = seq + 1

    def _decode_interval(self, interval):
        idx = min(
            range(len(self.expected)), key=lambda i: abs(self.expected[i] - interval)
        )
        if abs(self.expected[idx] - interval) <= self.margin:
            self.symbols.append(self.session.char_for_delay(idx, self.codebook))
        else:
            self.symbols.append(None)

    def current_message(self):
        out = []
        keyed = bool(self.session.key)
        for i, sym in enumerate(self.symbols):
            if sym is None:
                out.append("?")
            elif keyed:
                out.append(self.session.unmap_symbol(sym, i))
            else:
                out.append(sym)
        return "".join(out)


def simulate_exchange(message, session, codebook, jitter=30.0, drop_seqs=(), rng=None):
    """Noise model for tests: sender schedules pings with jittered sleeps,
    a lossy link drops selected seqs, the receiver reassembles."""
    rng = rng or random.Random(42)
    delays, prepared = encode_delays(message, session, codebook)
    seq = session.start_seq + 1
    t = 0.0
    frames = [("start", session.start_seq, t)]
    for delay in delays:
        frames.append(("data", seq, t))
        t += max(delay + (rng.uniform(-jitter, jitter) if jitter else 0.0), 1.0)
        seq += 1
    frames.append(("end", session.end_seq, t))

    result = {"received": None, "stats": None, "events": []}
    receiver = Receiver(
        session,
        codebook,
        margin=45.0,
        on_event=lambda ev, d: result["events"].append((ev, d)),
    )
    for _, fr_seq, ts in frames:
        if fr_seq in drop_seqs:
            continue
        receiver.on_packet(ts, fr_seq)
    for ev, d in result["events"]:
        if ev == "message":
            result["received"] = d["message"]
            result["stats"] = d
    result["prepared"] = prepared
    return result
