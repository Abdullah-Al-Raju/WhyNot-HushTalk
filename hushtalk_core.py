"""WhyNot-HushTalk core: framing, keyed sessions, encoding and decoding.

Pure stdlib so the protocol logic can be unit-tested without scapy,
root privileges or a network stack.
"""

from dataclasses import dataclass
import hashlib
import json
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

CODEBOOK_DIR = "codebooks"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,?!"
START_MARKER = 100
END_MARKER = 999
ACK_MARKER = 0
ICMP_ID = 12345
MAX_MESSAGE_LEN = END_MARKER - START_MARKER - 2
PAD_PAYLOAD = b"abcdefghijklmnop" * 3


@dataclass(frozen=True)
class TimingProfile:
    """Configures delay spacing for different network environments."""
    name: str
    base: float
    step: float
    margin: float
    default_jitter: float
    description: str


PROFILES: Dict[str, TimingProfile] = {
    "standard": TimingProfile(
        name="standard",
        base=500.0,
        step=100.0,
        margin=45.0,
        default_jitter=30.0,
        description="Standard codebook delays (500ms..4500ms), 100ms step",
    ),
    "fast": TimingProfile(
        name="fast",
        base=80.0,
        step=25.0,
        margin=12.0,
        default_jitter=5.0,
        description="Low-latency LAN profile (80ms..1155ms), 25ms step (~4x faster)",
    ),
    "stealth": TimingProfile(
        name="stealth",
        base=2000.0,
        step=500.0,
        margin=150.0,
        default_jitter=80.0,
        description="Stealth profile (2000ms..23500ms), low anomaly score",
    ),
}


def generate_codebook(profile: Union[str, TimingProfile] = "standard") -> Dict[str, float]:
    """Generate a delay mapping for ALPHABET using a timing profile."""
    if isinstance(profile, str):
        if profile not in PROFILES:
            raise ValueError(f"Unknown profile '{profile}'. Choose from: {list(PROFILES.keys())}")
        p = PROFILES[profile]
    else:
        p = profile
    return {ch: p.base + i * p.step for i, ch in enumerate(ALPHABET)}


def generate_payload(style: str = "pattern", length: int = 48) -> bytes:
    """Generate realistic or custom ping payload to avoid static IDS signatures.

    Styles:
      - 'pattern': Legacy HushTalk pattern (b"abcdefghijklmnop" * 3)
      - 'windows': Standard Windows ping payload (32-byte alphabet repeated)
      - 'linux': Standard Linux iputils ping payload (timestamp + sequential bytes)
      - 'random': Randomized bytes
      - 'zero': Null bytes
    """
    if style == "pattern":
        return (b"abcdefghijklmnop" * ((length // 16) + 1))[:length]
    elif style == "windows":
        win_pattern = b"abcdefghijklmnopqrstuvwabcdefghi"
        return (win_pattern * ((length // len(win_pattern)) + 1))[:length]
    elif style == "linux":
        ts_bytes = int(time.time()).to_bytes(8, "little")
        counter = bytes((i + 16) % 256 for i in range(max(0, length - 8)))
        return (ts_bytes + counter)[:length]
    elif style == "random":
        return os.urandom(length)
    elif style == "zero":
        return b"\x00" * length
    else:
        raise ValueError(
            f"Unknown payload style '{style}'. Choose from: pattern, windows, linux, random, zero"
        )


def load_codebook(name: str = "codebook.json", directory: Optional[str] = None) -> Dict[str, float]:
    """Load a codebook JSON mapping symbols to millisecond delays.

    Searches across:
      1. Direct path / absolute path
      2. User-provided directory
      3. Module's own codebooks directory
      4. Current working directory
    """
    candidates = []
    if os.path.isabs(name) and os.path.exists(name):
        candidates.append(name)
    if directory:
        candidates.append(os.path.join(directory, name))

    module_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(module_dir, CODEBOOK_DIR, name))
    candidates.append(os.path.join(module_dir, name))
    candidates.append(os.path.join(os.getcwd(), CODEBOOK_DIR, name))
    candidates.append(os.path.join(os.getcwd(), name))
    candidates.append(os.path.join(CODEBOOK_DIR, name))

    for candidate in candidates:
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                codebook = json.load(f)
            return {str(k).upper(): float(v) for k, v in codebook.items()}

    raise FileNotFoundError(
        f"Codebook '{name}' not found. Checked locations: {candidates}"
    )


class Session:
    """Protocol parameters for one conversation.

    Without a key the session uses the shared codebook and the public
    markers from v1. With a key, the ICMP id, markers, delay set and symbol
    mapping are all derived from the key, so observers that lack it cannot
    tell which packets belong to a message, let alone decode them.
    """

    def __init__(
        self,
        key: Optional[str] = None,
        profile: Union[str, TimingProfile] = "standard",
    ):
        self.key = key
        if isinstance(profile, str):
            if profile not in PROFILES:
                raise ValueError(f"Unknown profile '{profile}'. Choose from: {list(PROFILES.keys())}")
            self.profile = PROFILES[profile]
        else:
            self.profile = profile

        if key:
            h = hashlib.sha256(("hushtalk:" + key).encode()).digest()
            self.icmp_id = int.from_bytes(h[0:2], "big") or 1
            self.start_seq = 100 + h[3] % 40
            self.end_seq = 900 + h[4] % 40
            self.ack_seq = h[5] % 50

            if self.profile.name == "standard":
                self.base = 400 + h[6] % 300
                self.step = 150 + (h[7] % 6) * 50
            elif self.profile.name == "fast":
                self.base = 60 + (h[6] % 40)
                self.step = 20 + (h[7] % 4) * 10
            else:  # stealth
                self.base = 1500 + (h[6] % 1000)
                self.step = 300 + (h[7] % 5) * 100

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

    def alphabet(self) -> Optional[str]:
        return ALPHABET if self.key else None

    def delays_for(self, message: str) -> List[float]:
        if self.key:
            return [
                float(self.base + self.step * self._slot_of[ch])
                for ch in self._scramble(message)
            ]
        raise ValueError("unkeyed sessions use delays_from_codebook()")

    def delays_from_codebook(self, message: str, codebook: Dict[str, float]) -> List[float]:
        return [float(codebook[ch]) for ch in message]

    def expected_delays(self, codebook: Dict[str, float]) -> List[float]:
        if self.key:
            return [float(self.base + self.step * slot) for slot in range(len(ALPHABET))]
        return [float(d) for _, d in self._table(codebook)]

    def char_for_delay(self, delay_index: int, codebook: Dict[str, float]) -> str:
        if self.key:
            return self._char_of[delay_index]
        return self._table(codebook)[delay_index][0]

    def _keystream(self, i: int) -> int:
        return self._pad[i % len(self._pad)] % len(ALPHABET)

    def map_symbol(self, ch: str, i: int) -> str:
        return ALPHABET[(ALPHABET.index(ch) + self._keystream(i)) % len(ALPHABET)]

    def unmap_symbol(self, ch: str, i: int) -> str:
        return ALPHABET[(ALPHABET.index(ch) - self._keystream(i)) % len(ALPHABET)]

    def _scramble(self, message: str) -> str:
        return "".join(self.map_symbol(ch, i) for i, ch in enumerate(message))

    def _table(self, codebook: Dict[str, float]) -> List[Tuple[str, float]]:
        return sorted(((ch, codebook[ch]) for ch in codebook), key=lambda kv: kv[1])


def prepare_message(text: str, session: Session, codebook: Dict[str, float]) -> str:
    allowed = session.alphabet() or set(codebook)
    return "".join(ch if ch in allowed else " " for ch in text.upper())


def encode_delays(
    message: str,
    session: Session,
    codebook: Dict[str, float],
) -> Tuple[List[float], str]:
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

    def __init__(
        self,
        session: Session,
        codebook: Dict[str, float],
        margin: Optional[float] = None,
        timeout_ms: Optional[float] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.session = session
        self.codebook = codebook
        self.margin = margin if margin is not None else session.profile.margin
        self.expected = session.expected_delays(codebook)
        if timeout_ms is None:
            timeout_ms = max(self.expected) + self.margin + 2000.0
        self.timeout_ms = timeout_ms
        self.on_event = on_event or (lambda ev, data: None)
        self.reset()

    def reset(self) -> None:
        self.started = False
        self.symbols: List[Optional[str]] = []
        self.prev_ts: Optional[float] = None
        self.first_seen = False
        self.expected_seq: Optional[int] = None
        self.last_activity: Optional[float] = None
        self.start_time: Optional[float] = None
        self.deviations: List[float] = []

    def tick(self, now_ms: float) -> None:
        if (
            self.started
            and self.last_activity
            and now_ms - self.last_activity > self.timeout_ms
        ):
            self.on_event("timeout", {"partial": self.current_message()})
            self.reset()

    def on_packet(self, ts_ms: float, seq: int) -> None:
        self.tick(ts_ms)
        s = self.session
        if seq == s.start_seq:
            self.reset()
            self.started = True
            self.last_activity = ts_ms
            self.start_time = ts_ms
            self.expected_seq = s.start_seq + 1
            self.on_event("start", {})
            return
        if not self.started or seq == s.ack_seq:
            return
        if seq == s.end_seq:
            if self.prev_ts is not None and self.first_seen:
                self._decode_interval(ts_ms - self.prev_ts)
            elapsed = (ts_ms - self.start_time) if self.start_time is not None else 0.0
            total_symbols = len(self.symbols)
            uncertain_symbols = self.symbols.count(None)
            stats = {
                "message": self.current_message(),
                "symbols": total_symbols,
                "uncertain": uncertain_symbols,
                "elapsed_ms": round(elapsed, 1),
                "cps": round(total_symbols / (elapsed / 1000.0), 3) if elapsed > 0 else 0.0,
                "avg_jitter_ms": round(sum(self.deviations) / len(self.deviations), 2) if self.deviations else 0.0,
                "max_jitter_ms": round(max(self.deviations), 2) if self.deviations else 0.0,
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

    def _decode_interval(self, interval: float) -> None:
        idx = min(
            range(len(self.expected)), key=lambda i: abs(self.expected[i] - interval)
        )
        dev = abs(self.expected[idx] - interval)
        if dev <= self.margin:
            self.symbols.append(self.session.char_for_delay(idx, self.codebook))
            self.deviations.append(dev)
        else:
            self.symbols.append(None)

    def current_message(self) -> str:
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


def simulate_exchange(
    message: str,
    session: Session,
    codebook: Dict[str, float],
    jitter: float = 30.0,
    drop_seqs: Sequence[int] = (),
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
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

    result: Dict[str, Any] = {"received": None, "stats": None, "events": []}
    receiver = Receiver(
        session,
        codebook,
        margin=session.profile.margin if hasattr(session, "profile") else 45.0,
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


def simulate_run(
    message: str,
    key: Optional[str] = None,
    profile: str = "standard",
    jitter: Optional[float] = None,
    drop_seqs: Sequence[int] = (),
    payload_style: str = "pattern",
    seed: Optional[int] = 42,
) -> Dict[str, Any]:
    """High-level simulation runner for testing and CLI demonstration."""
    session = Session(key=key, profile=profile)
    codebook = generate_codebook(profile) if profile != "standard" else load_codebook()
    eff_jitter = jitter if jitter is not None else session.profile.default_jitter
    rng = random.Random(seed) if seed is not None else random.Random()
    payload = generate_payload(payload_style)
    res = simulate_exchange(message, session, codebook, jitter=eff_jitter, drop_seqs=drop_seqs, rng=rng)
    res["session"] = {
        "key": key,
        "profile": session.profile.name,
        "icmp_id": session.icmp_id,
        "start_seq": session.start_seq,
        "end_seq": session.end_seq,
        "payload_len": len(payload),
        "payload_style": payload_style,
        "jitter_simulated_ms": eff_jitter,
    }
    return res
