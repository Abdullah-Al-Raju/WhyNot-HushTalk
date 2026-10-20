"""WhyNot-HushTalk Full-Duplex Node Engine.

Provides concurrent asynchronous transmission and reception, message lifecycle
management, loopback echo filtering, and real-time telemetry streaming for
the web chat interface.
"""

from collections import deque
from dataclasses import asdict, dataclass, field
import os
import queue
import random
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

import hushtalk_core as hc

try:
    from scapy.all import ICMP, IP, Raw, conf, send, sniff

    conf.verb = 0
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False


@dataclass
class ChatMessage:
    id: str
    direction: str  # "outbound" or "inbound"
    sender: str
    target: str
    text: str
    status: str  # "queued", "transmitting", "delivered", "acknowledged", "failed"
    progress: float = 0.0  # 0.0 to 1.0
    symbols_total: int = 0
    symbols_sent: int = 0
    symbols_clean: int = 0
    symbols_uncertain: int = 0
    elapsed_ms: float = 0.0
    cps: float = 0.0
    avg_jitter_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class HushTalkNode:
    """Full-duplex covert channel communication node."""

    def __init__(
        self,
        target_ip: str = "127.0.0.1",
        port: int = 9999,
        listen_port: Optional[int] = None,
        listen_ip: str = "0.0.0.0",
        key: Optional[str] = None,
        profile: str = "fast",
        transport: str = "udp",
        payload_style: str = "pattern",
        auto_ack: bool = True,
    ):
        self.target_ip = target_ip
        self.port = port
        self.listen_port = listen_port or port
        self.listen_ip = listen_ip
        self.key = key
        self.profile = profile
        self.transport = transport
        self.payload_style = payload_style
        self.auto_ack = auto_ack

        self._lock = threading.RLock()
        self._running = False
        self._send_queue: queue.Queue[ChatMessage] = queue.Queue()
        self._messages: List[ChatMessage] = []
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

        # Ring buffers for telemetry
        self._recent_packets: deque = deque(maxlen=60)
        self._inter_arrival_times: deque = deque(maxlen=200)
        self._own_sent_seqs: deque = deque(maxlen=500)

        # Background threads
        self._sender_thread: Optional[threading.Thread] = None
        self._listener_thread: Optional[threading.Thread] = None

        # Network handles
        self._udp_sock: Optional[socket.socket] = None

        self._refresh_session()

    def _refresh_session(self) -> None:
        with self._lock:
            self.session = hc.Session(self.key, profile=self.profile)
            if self.profile != "standard":
                self.codebook = hc.generate_codebook(self.profile)
            else:
                try:
                    self.codebook = hc.load_codebook()
                except FileNotFoundError:
                    self.codebook = hc.generate_codebook("standard")

    def configure(
        self,
        target_ip: Optional[str] = None,
        port: Optional[int] = None,
        listen_port: Optional[int] = None,
        key: Optional[str] = None,
        profile: Optional[str] = None,
        transport: Optional[str] = None,
        payload_style: Optional[str] = None,
        auto_ack: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update node configuration dynamically."""
        restart_listener = False
        with self._lock:
            if target_ip is not None:
                self.target_ip = target_ip
            if port is not None and port != self.port:
                self.port = port
            if listen_port is not None and listen_port != self.listen_port:
                self.listen_port = listen_port
                restart_listener = True
            if transport is not None and transport != self.transport:
                self.transport = transport
                restart_listener = True
            if key is not None and key != self.key:
                self.key = key if key.strip() else None
                restart_listener = True
            if profile is not None and profile in hc.PROFILES and profile != self.profile:
                self.profile = profile
                restart_listener = True
            if payload_style is not None:
                self.payload_style = payload_style
            if auto_ack is not None:
                self.auto_ack = auto_ack

            self._refresh_session()

        if restart_listener and self._running:
            self._restart_listener()

        self._emit({"type": "config_updated", "data": self.get_status()})
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            # Calculate timing dispersion (Coefficient of Variation)
            iats = list(self._inter_arrival_times)
            if len(iats) >= 5:
                mean_iat = sum(iats) / len(iats)
                variance = sum((x - mean_iat) ** 2 for x in iats) / len(iats)
                std_dev = variance ** 0.5
                cov = (std_dev / mean_iat) if mean_iat > 0 else 0.0
            else:
                mean_iat, std_dev, cov = 0.0, 0.0, 0.0

            return {
                "running": self._running,
                "target_ip": self.target_ip,
                "port": self.port,
                "listen_port": self.listen_port,
                "transport": self.transport,
                "profile": self.profile,
                "has_key": bool(self.key),
                "key_preview": (self.key[:3] + "..." + self.key[-2:]) if self.key and len(self.key) > 5 else (self.key or "unkeyed"),
                "icmp_id": self.session.icmp_id,
                "start_seq": self.session.start_seq,
                "end_seq": self.session.end_seq,
                "ack_seq": self.session.ack_seq,
                "payload_style": self.payload_style,
                "auto_ack": self.auto_ack,
                "packets_observed": len(self._recent_packets),
                "timing_telemetry": {
                    "sample_count": len(iats),
                    "mean_iat_ms": round(mean_iat, 1),
                    "std_dev_ms": round(std_dev, 1),
                    "cov": round(cov, 3),
                },
            }

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _emit(self, event: Dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub(event)
            except Exception:
                pass

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True

            # Start listener
            self._start_listener()

            # Start sender queue worker
            self._sender_thread = threading.Thread(target=self._sender_worker, daemon=True)
            self._sender_thread.start()

        self._emit({"type": "node_started", "data": self.get_status()})

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._udp_sock:
                try:
                    self._udp_sock.close()
                except Exception:
                    pass
                self._udp_sock = None

        self._emit({"type": "node_stopped", "data": {"running": False}})

    def send_chat_message(self, text: str) -> ChatMessage:
        """Enqueue message for asynchronous transmission."""
        msg_id = str(uuid.uuid4())[:8]
        msg = ChatMessage(
            id=msg_id,
            direction="outbound",
            sender="Local Node",
            target=self.target_ip,
            text=text.strip(),
            status="queued",
            progress=0.0,
            symbols_total=len(text.strip()),
        )
        with self._lock:
            self._messages.append(msg)
            self._send_queue.put(msg)

        self._emit({"type": "message_queued", "data": asdict(msg)})
        return msg

    def get_messages(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [asdict(m) for m in self._messages]

    def get_telemetry(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "recent_packets": list(self._recent_packets),
                "inter_arrival_times": list(self._inter_arrival_times),
            }

    # Internal Sender Worker
    def _sender_worker(self) -> None:
        while self._running:
            try:
                msg = self._send_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self._transmit_message(msg)

    def _transmit_message(self, msg: ChatMessage) -> None:
        with self._lock:
            msg.status = "transmitting"
            sess = self.session
            cb = self.codebook
            transport = self.transport
            target_ip = self.target_ip
            port = self.port
            payload_style = self.payload_style

        self._emit({"type": "message_status", "data": asdict(msg)})

        try:
            delays, prepared = hc.encode_delays(msg.text, sess, cb)
        except Exception as exc:
            msg.status = "failed"
            self._emit({"type": "message_status", "data": asdict(msg), "error": str(exc)})
            return

        msg.symbols_total = len(delays)
        payload = hc.generate_payload(payload_style, 48)
        rng = random.Random()
        j = sess.profile.default_jitter

        # Helper to send single packet
        def send_raw(seq: int):
            now_sec = time.time()
            now_ms = now_sec * 1000.0
            with self._lock:
                self._own_sent_seqs.append((seq, now_sec))

            if transport == "udp":
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    hdr = struct.pack("!HH", sess.icmp_id, seq)
                    sock.sendto(hdr + payload, (target_ip, port))
                    sock.close()
                except Exception as exc:
                    pass
            elif transport == "icmp" and SCAPY_AVAILABLE:
                try:
                    pkt = IP(dst=target_ip) / ICMP(type=8, id=sess.icmp_id, seq=seq) / Raw(load=payload)
                    send(pkt, verbose=False)
                except Exception:
                    pass

            pkt_info = {
                "dir": "out",
                "seq": seq,
                "timestamp": now_ms,
                "target": f"{target_ip}:{port}" if transport == "udp" else target_ip,
                "proto": transport.upper(),
            }
            with self._lock:
                self._recent_packets.append(pkt_info)
            self._emit({"type": "packet_event", "data": pkt_info})

        start_time = time.time()
        # 1. Send start marker
        send_raw(sess.start_seq)
        time.sleep(max(0.05, (500.0 + rng.uniform(-j, j)) / 1000.0))

        # 2. Transmit data frames
        for i, delay in enumerate(delays):
            if not self._running:
                break
            seq = sess.start_seq + 1 + i
            send_raw(seq)

            with self._lock:
                msg.symbols_sent = i + 1
                msg.progress = round((i + 1) / len(delays), 2)
            self._emit({"type": "message_progress", "data": asdict(msg)})

            sleep_duration = max(1.0, delay + rng.uniform(-j, j)) / 1000.0
            time.sleep(sleep_duration)

        # 3. Send end marker
        send_raw(sess.end_seq)
        duration = time.time() - start_time

        with self._lock:
            msg.status = "delivered"
            msg.progress = 1.0
            msg.elapsed_ms = round(duration * 1000.0, 1)
            msg.cps = round(len(delays) / duration, 2) if duration > 0 else 0.0
        self._emit({"type": "message_status", "data": asdict(msg)})

    # Internal Listener Worker
    def _start_listener(self) -> None:
        if self.transport == "udp":
            self._listener_thread = threading.Thread(target=self._udp_listener_loop, daemon=True)
            self._listener_thread.start()
        elif self.transport == "icmp" and SCAPY_AVAILABLE:
            self._listener_thread = threading.Thread(target=self._icmp_listener_loop, daemon=True)
            self._listener_thread.start()

    def _restart_listener(self) -> None:
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass
            self._udp_sock = None
        self._start_listener()

    def _udp_listener_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self.listen_ip, self.listen_port))
        except Exception as exc:
            self._emit({"type": "listener_error", "error": f"UDP bind failed on {self.listen_ip}:{self.listen_port} - {exc}"})
            return

        sock.settimeout(0.5)
        self._udp_sock = sock

        def on_event(ev: str, data: Dict[str, Any]):
            self._handle_receiver_event(ev, data, "UDP")

        receiver = hc.Receiver(
            self.session,
            self.codebook,
            margin=self.session.profile.margin,
            on_event=on_event,
        )

        last_packet_ts: Optional[float] = None

        while self._running:
            try:
                data, addr = sock.recvfrom(2048)
                now_ms = time.time() * 1000.0
                if len(data) >= 4:
                    hdr_id, seq = struct.unpack("!HH", data[:4])
                    if hdr_id == self.session.icmp_id:
                        # Echo cancellation for local transmissions (only if target and listen port match on loopback)
                        now_sec = time.time()
                        with self._lock:
                            if self.port == self.listen_port and any(s == seq and (now_sec - t) < 0.15 for s, t in self._own_sent_seqs):
                                continue

                        if last_packet_ts is not None:
                            iat = round(now_ms - last_packet_ts, 1)
                            with self._lock:
                                self._inter_arrival_times.append(iat)
                        last_packet_ts = now_ms

                        pkt_info = {
                            "dir": "in",
                            "seq": seq,
                            "timestamp": now_ms,
                            "src": f"{addr[0]}:{addr[1]}",
                            "proto": "UDP",
                        }
                        with self._lock:
                            self._recent_packets.append(pkt_info)
                        self._emit({"type": "packet_event", "data": pkt_info})

                        receiver.on_packet(now_ms, seq)
            except socket.timeout:
                pass
            except Exception:
                break
            receiver.tick(time.time() * 1000.0)

        sock.close()

    def _icmp_listener_loop(self) -> None:
        def on_event(ev: str, data: Dict[str, Any]):
            self._handle_receiver_event(ev, data, "ICMP")

        receiver = hc.Receiver(
            self.session,
            self.codebook,
            margin=self.session.profile.margin,
            on_event=on_event,
        )

        last_packet_ts: Optional[float] = None

        def prn(pkt):
            if IP not in pkt or ICMP not in pkt:
                return
            icmp = pkt[ICMP]
            if icmp.type != 8 or icmp.id != self.session.icmp_id:
                return

            seq = icmp.seq
            now_sec = time.time()
            with self._lock:
                if any(s == seq and (now_sec - t) < 0.15 for s, t in self._own_sent_seqs):
                    return

            now_ms = time.time() * 1000.0
            nonlocal last_packet_ts
            if last_packet_ts is not None:
                iat = round(now_ms - last_packet_ts, 1)
                with self._lock:
                    self._inter_arrival_times.append(iat)
            last_packet_ts = now_ms

            pkt_info = {
                "dir": "in",
                "seq": seq,
                "timestamp": now_ms,
                "src": pkt[IP].src,
                "proto": "ICMP",
            }
            with self._lock:
                self._recent_packets.append(pkt_info)
            self._emit({"type": "packet_event", "data": pkt_info})

            receiver.on_packet(now_ms, seq)

        while self._running:
            try:
                sniff(prn=prn, store=0, filter="icmp", timeout=1.0)
            except Exception:
                break
            receiver.tick(time.time() * 1000.0)

    def _handle_receiver_event(self, ev: str, data: Dict[str, Any], proto: str) -> None:
        if ev == "start":
            self._emit({"type": "inbound_started", "data": {"proto": proto, "timestamp": time.time()}})
        elif ev == "message":
            msg_id = str(uuid.uuid4())[:8]
            clean_text = data.get("message", "")
            inbound_msg = ChatMessage(
                id=msg_id,
                direction="inbound",
                sender="Remote Peer",
                target="Local Node",
                text=clean_text,
                status="delivered",
                progress=1.0,
                symbols_total=data.get("symbols", len(clean_text)),
                symbols_clean=data.get("symbols", 0) - data.get("uncertain", 0),
                symbols_uncertain=data.get("uncertain", 0),
                elapsed_ms=data.get("elapsed_ms", 0.0),
                cps=data.get("cps", 0.0),
                avg_jitter_ms=data.get("avg_jitter_ms", 0.0),
            )
            with self._lock:
                self._messages.append(inbound_msg)
            self._emit({"type": "message_received", "data": asdict(inbound_msg)})

            # Check if any outbound message is waiting for ACK or send reverse ACK
            if self.auto_ack:
                self._send_ack_burst()
        elif ev == "timeout":
            self._emit({"type": "inbound_timeout", "data": data})

    def _send_ack_burst(self) -> None:
        """Transmit reverse 3-packet acknowledgment burst."""
        target_ip = self.target_ip
        port = self.port
        sess = self.session

        if self.transport == "udp":
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                hdr = struct.pack("!HH", sess.icmp_id, sess.ack_seq)
                for _ in range(3):
                    sock.sendto(hdr + b"\x00" * 16, (target_ip, port))
                    time.sleep(0.05)
                sock.close()
            except Exception:
                pass
        elif self.transport == "icmp" and SCAPY_AVAILABLE:
            try:
                for _ in range(3):
                    pkt = IP(dst=target_ip) / ICMP(type=8, id=sess.icmp_id, seq=sess.ack_seq) / Raw(load=b"\x00" * 16)
                    send(pkt, verbose=False)
                    time.sleep(0.05)
            except Exception:
                pass
