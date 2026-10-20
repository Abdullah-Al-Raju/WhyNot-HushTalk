#!/usr/bin/env python3
"""WhyNot-HushTalk sender: encodes a message as inter-ping delays."""

import argparse
import os
import random
import socket
import struct
import sys
import time

from colorama import Fore, Style, init

from hushtalk_core import (
    MAX_MESSAGE_LEN,
    PAD_PAYLOAD,
    PROFILES,
    Session,
    encode_delays,
    generate_codebook,
    generate_payload,
    load_codebook,
    simulate_run,
)

init(autoreset=True)

try:
    from scapy.all import ICMP, IP, Raw, conf, send, sniff

    conf.verb = 0
    SCAPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    SCAPY_AVAILABLE = False


def build_ping(dst, session, seq, ttl=None, payload=None, is_ipv6=False):
    load = payload if payload is not None else PAD_PAYLOAD
    if is_ipv6:
        from scapy.layers.inet6 import IPv6, ICMPv6EchoRequest

        ip = IPv6(dst=dst)
        if ttl:
            ip.hlim = ttl
        return ip / ICMPv6EchoRequest(id=session.icmp_id, seq=seq, data=load)
    else:
        ip = IP(dst=dst)
        if ttl:
            ip.ttl = ttl
        return ip / ICMP(type=8, id=session.icmp_id, seq=seq) / Raw(load=load)


def send_ping(dst, session, seq, ttl=None, iface=None, payload=None, is_ipv6=False):
    pkt = build_ping(dst, session, seq, ttl, payload, is_ipv6)
    if iface:
        return send(pkt, iface=iface, verbose=False)
    return send(pkt, verbose=False)


def send_udp_packet(sock, dst, port, session, seq, payload):
    header = struct.pack("!HH", session.icmp_id, seq)
    sock.sendto(header + payload, (dst, port))


def wait_for_ack(session, target, seconds, quiet=False, is_ipv6=False, transport="icmp", port=9999, sock=None):
    if transport == "udp":
        if sock is None:
            return False
        got = 0
        deadline = time.time() + seconds
        while time.time() < deadline and got < 3:
            remaining = max(0.1, deadline - time.time())
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(1024)
                if len(data) >= 4:
                    hdr_id, hdr_seq = struct.unpack("!HH", data[:4])
                    if hdr_id == session.icmp_id and hdr_seq == session.ack_seq:
                        got += 1
            except (socket.timeout, BlockingIOError):
                break
            except Exception:
                break
        return got >= 3

    got = {"n": 0}

    def prn(pkt):
        if is_ipv6:
            from scapy.layers.inet6 import ICMPv6EchoRequest

            if ICMPv6EchoRequest in pkt:
                icmp = pkt[ICMPv6EchoRequest]
                if icmp.id == session.icmp_id and icmp.seq == session.ack_seq:
                    got["n"] += 1
        else:
            if ICMP in pkt and pkt[ICMP].id == session.icmp_id and pkt[ICMP].seq == session.ack_seq:
                got["n"] += 1

    def stop(pkt):
        return got["n"] >= 3

    bpf = f"icmp6 and src {target}" if is_ipv6 else f"icmp and src {target}"
    try:
        sniff(filter=bpf, prn=prn, stop_filter=stop, timeout=seconds)
    except Exception as exc:
        if not quiet:
            print(f"{Fore.YELLOW}[!] ack sniff failed: {exc}")
        return False
    return got["n"] >= 3


def run_simulation_mode(text, key, profile_name, jitter, payload_style):
    print(f"{Fore.MAGENTA}{Style.BRIGHT}[🧪] Running HushTalk in Simulation Mode (No root/network required)")
    sim = simulate_run(
        message=text,
        key=key,
        profile=profile_name,
        jitter=jitter,
        payload_style=payload_style,
    )
    sess_info = sim["session"]
    stats = sim["stats"]
    print(f"{Fore.CYAN}    Session: profile={sess_info['profile']} | icmp_id={sess_info['icmp_id']} | "
          f"seq {sess_info['start_seq']}..{sess_info['end_seq']}")
    print(f"{Fore.CYAN}    Cover Payload: style={sess_info['payload_style']} ({sess_info['payload_len']} bytes)")
    print(f"{Fore.CYAN}    Simulated Jitter: ±{sess_info['jitter_simulated_ms']:.1f}ms")
    print(f"{Fore.GREEN}[→] Input:    {sim['prepared']}")
    print(f"{Fore.GREEN}[✓] Decoded:  {sim['received']!r}")
    if stats:
        uncertain = stats.get("uncertain", 0)
        total = stats.get("symbols", len(sim["prepared"]))
        elapsed_s = stats.get("elapsed_ms", 0.0) / 1000.0
        cps = stats.get("cps", 0.0)
        avg_j = stats.get("avg_jitter_ms", 0.0)
        max_j = stats.get("max_jitter_ms", 0.0)
        status_color = Fore.GREEN if uncertain == 0 else Fore.YELLOW
        print(f"{status_color}    Stats:    {total - uncertain}/{total} symbols clean | "
              f"duration={elapsed_s:.1f}s ({cps:.2f} chars/s) | jitter avg={avg_j:.1f}ms max={max_j:.1f}ms")
    print(f"{Fore.MAGENTA}[✓] Simulation complete.\n")


def main():
    parser = argparse.ArgumentParser(description="HushTalk sender: hide messages in ping timing")
    parser.add_argument("--to", default=None, help="target IPv4 or IPv6 address")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-m", "--message", help="message text (use - to read stdin)")
    group.add_argument("--file", help="read message from file")
    parser.add_argument("--codebook", default="codebook.json", help="path to custom codebook JSON")
    parser.add_argument("--profile", choices=list(PROFILES.keys()), default="standard",
                        help="timing profile: standard (default), fast (LAN/lab), stealth (low rate)")
    parser.add_argument("--transport", choices=["icmp", "udp"], default="icmp",
                        help="transport mode: icmp (default, requires root/Npcap) or udp (unprivileged userland)")
    parser.add_argument("--port", type=int, default=9999, help="target UDP port when using --transport udp")
    parser.add_argument("--key", default=None, help="shared secret; keys markers, delays and symbols")
    parser.add_argument("--payload", choices=["pattern", "windows", "linux", "random", "zero"],
                        default="pattern", help="cover ping payload style to evade static IDS signatures")
    parser.add_argument("--payload-len", type=int, default=48, help="payload byte length")
    parser.add_argument("--ipv6", action="store_true", help="use IPv6")
    parser.add_argument("--iface", default=None, help="egress interface")
    parser.add_argument("--ttl", type=int, default=None, help="IP TTL or IPv6 Hop Limit")
    parser.add_argument("--jitter", type=float, default=None,
                        help="± ms randomness on each delay (default: from profile)")
    parser.add_argument("--gap", type=float, default=500.0, help="ms between start marker and first data ping")
    parser.add_argument("--wait-ack", type=float, default=0.0, metavar="SEC", help="wait for receiver ack burst")
    parser.add_argument("--simulate", "--dry-run", action="store_true",
                        help="dry-run simulation without sending packets or requiring root")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    text = args.message
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif text == "-":
        text = sys.stdin.read()
    if not text:
        print(f"{Fore.RED}[!] empty message")
        sys.exit(1)

    profile_name = args.profile
    prof = PROFILES[profile_name]
    jitter = args.jitter if args.jitter is not None else prof.default_jitter

    if args.simulate:
        run_simulation_mode(text, args.key, profile_name, jitter, args.payload)
        return

    if not args.to:
        print(f"{Fore.RED}[!] --to <target-ip> is required when not running with --simulate")
        sys.exit(1)

    is_ipv6 = args.ipv6 or (":" in args.to)

    if args.transport == "icmp" and not SCAPY_AVAILABLE:
        print(f"{Fore.RED}[!] scapy is required for ICMP network transmission: pip install scapy")
        sys.exit(1)

    if profile_name != "standard":
        codebook = generate_codebook(profile_name)
    else:
        try:
            codebook = load_codebook(args.codebook)
        except FileNotFoundError as err:
            print(f"{Fore.YELLOW}[!] Codebook file '{args.codebook}' not found, falling back to standard profile generator: {err}")
            codebook = generate_codebook("standard")

    session = Session(args.key, profile=profile_name)
    try:
        delays, prepared = encode_delays(text, session, codebook)
    except ValueError as exc:
        print(f"{Fore.RED}[!] {exc}")
        sys.exit(1)

    payload_data = generate_payload(args.payload, args.payload_len)
    rng = random.Random()
    j = max(jitter, 0.0)
    quiet = args.quiet

    udp_sock = None
    if args.transport == "udp":
        udp_sock = socket.socket(socket.AF_INET6 if is_ipv6 else socket.AF_INET, socket.SOCK_DGRAM)

    if not quiet:
        style = Fore.GREEN if args.key else Fore.CYAN
        what = f"keyed session ({profile_name})" if args.key else f"codebook session ({profile_name})"
        proto_label = f"UDP:{args.port}" if args.transport == "udp" else ("IPv6/ICMPv6" if is_ipv6 else "IPv4/ICMP")
        print(f"{style}[→] HushTalk {what} [{proto_label}]: id={session.icmp_id} "
              f"seq {session.start_seq}..{session.end_seq}")
        print(f"{Fore.CYAN}[→] Payload: {args.payload} ({len(payload_data)} bytes) | Jitter: ±{j:.1f}ms")
        print(f"{Fore.CYAN}[→] Sending: {prepared}")
        if args.verbose:
            print(f"{Fore.YELLOW}[→] Delays (ms): {[round(d) for d in delays]}")
        print()

    def do_send(seq):
        if args.transport == "udp":
            send_udp_packet(udp_sock, args.to, args.port, session, seq, payload_data)
        else:
            send_ping(args.to, session, seq, args.ttl, args.iface, payload_data, is_ipv6)

    try:
        do_send(session.start_seq)
    except (PermissionError, Exception) as exc:
        print(f"{Fore.RED}[!] Packet transmission failed: {exc}")
        if args.transport == "icmp":
            print(f"{Fore.YELLOW}[!] Note: Raw ICMP sockets require root privileges (sudo python3 whisper.py) or CAP_NET_RAW capability.")
            print(f"{Fore.YELLOW}[!] Alternatively, run in userland mode without root using: --transport udp --port 9999")
        sys.exit(1)

    if args.verbose:
        print(f"{Fore.BLUE}    start marker seq={session.start_seq}")
    time.sleep(max(args.gap + rng.uniform(-j, j), 50.0) / 1000.0)

    for i, delay in enumerate(delays):
        seq = session.start_seq + 1 + i
        do_send(seq)
        if args.verbose:
            print(f"{Fore.BLUE}    [{i + 1}/{len(delays)}] seq={seq} -> wait {delay:.0f}ms")
        time.sleep(max(delay + rng.uniform(-j, j), 1.0) / 1000.0)

    do_send(session.end_seq)
    if args.verbose:
        print(f"{Fore.BLUE}    end marker seq={session.end_seq}")
    print(f"\n{Fore.GREEN}[✓] {len(prepared)} chars sent to {args.to}")

    if args.wait_ack > 0:
        if wait_for_ack(session, args.to, args.wait_ack, quiet, is_ipv6, args.transport, args.port, udp_sock):
            print(f"{Fore.GREEN}[✓] ack received from {args.to}")
        else:
            print(f"{Fore.YELLOW}[!] no ack after {args.wait_ack:.0f}s (receiver offline or --ack not set)")

    if udp_sock:
        udp_sock.close()


if __name__ == "__main__":
    main()
