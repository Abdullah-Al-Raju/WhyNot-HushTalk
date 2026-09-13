#!/usr/bin/env python3
"""WhyNot-HushTalk sender: encodes a message as inter-ping delays."""

import argparse
import random
import sys
import time

from colorama import Fore, Style, init

from hushtalk_core import MAX_MESSAGE_LEN, PAD_PAYLOAD, Session, encode_delays, load_codebook

init(autoreset=True)

try:
    from scapy.all import ICMP, IP, Raw, conf, send, sniff

    conf.verb = 0
except ImportError:  # pragma: no cover
    print("scapy is required: pip install scapy")
    sys.exit(1)


def build_ping(dst, session, seq, ttl=None):
    ip = IP(dst=dst)
    if ttl:
        ip.ttl = ttl
    return ip / ICMP(type=8, id=session.icmp_id, seq=seq) / Raw(load=PAD_PAYLOAD)


def send_ping(dst, session, seq, ttl=None, iface=None):
    pkt = build_ping(dst, session, seq, ttl)
    if iface:
        return send(pkt, iface=iface, verbose=False)
    return send(pkt, verbose=False)


def wait_for_ack(session, target, seconds, quiet):
    got = {"n": 0}

    def prn(pkt):
        if ICMP in pkt and pkt[ICMP].id == session.icmp_id and pkt[ICMP].seq == session.ack_seq:
            got["n"] += 1

    def stop(pkt):
        return got["n"] >= 3

    try:
        sniff(filter=f"icmp and src {target}", prn=prn, stop_filter=stop, timeout=seconds)
    except Exception as exc:  # BPF quirks on some platforms
        if not quiet:
            print(f"{Fore.YELLOW}[!] ack sniff failed: {exc}")
        return False
    return got["n"] >= 3


def main():
    parser = argparse.ArgumentParser(description="HushTalk sender: hide messages in ping timing")
    parser.add_argument("--to", required=True, help="target IPv4")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-m", "--message", help="message text (use - to read stdin)")
    group.add_argument("--file", help="read message from file")
    parser.add_argument("--codebook", default="codebook.json")
    parser.add_argument("--key", default=None, help="shared secret; keys markers, delays and symbols")
    parser.add_argument("--iface", default=None, help="egress interface")
    parser.add_argument("--ttl", type=int, default=None)
    parser.add_argument("--jitter", type=float, default=30.0, help="± ms randomness on each delay (0 disables)")
    parser.add_argument("--gap", type=float, default=500.0, help="ms between start marker and first data ping")
    parser.add_argument("--wait-ack", type=float, default=0.0, metavar="SEC", help="wait for receiver ack burst")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    text = args.message
    if args.file:
        with open(args.file) as f:
            text = f.read()
    elif text == "-":
        text = sys.stdin.read()
    if not text:
        print(f"{Fore.RED}[!] empty message")
        sys.exit(1)

    codebook = load_codebook(args.codebook)
    session = Session(args.key)
    try:
        delays, prepared = encode_delays(text, session, codebook)
    except ValueError as exc:
        print(f"{Fore.RED}[!] {exc}")
        sys.exit(1)

    rng = random.Random()
    j = max(args.jitter, 0.0)
    quiet = args.quiet

    if not quiet:
        style = Fore.GREEN if args.key else Fore.CYAN
        what = "keyed session" if args.key else "codebook session"
        print(f"{style}[→] HushTalk {what}: icmp_id={session.icmp_id} "
              f"seq {session.start_seq}..{session.end_seq}")
        print(f"{Fore.CYAN}[→] Sending: {prepared}")
        if args.verbose:
            print(f"{Fore.YELLOW}[→] Delays (ms): {[round(d) for d in delays]}")
        print()

    send_ping(args.to, session, session.start_seq, args.ttl, args.iface)
    if args.verbose:
        print(f"{Fore.BLUE}    start marker seq={session.start_seq}")
    time.sleep(max(args.gap + rng.uniform(-j, j), 50.0) / 1000.0)

    for i, delay in enumerate(delays):
        seq = session.start_seq + 1 + i
        send_ping(args.to, session, seq, args.ttl, args.iface)
        if args.verbose:
            print(f"{Fore.BLUE}    [{i + 1}/{len(delays)}] seq={seq} -> wait {delay:.0f}ms")
        time.sleep(max(delay + rng.uniform(-j, j), 1.0) / 1000.0)

    send_ping(args.to, session, session.end_seq, args.ttl, args.iface)
    if args.verbose:
        print(f"{Fore.BLUE}    end marker seq={session.end_seq}")
    print(f"\n{Fore.GREEN}[✓] {len(prepared)} chars sent to {args.to}")

    if args.wait_ack > 0:
        if wait_for_ack(session, args.to, args.wait_ack, quiet):
            print(f"{Fore.GREEN}[✓] ack received from {args.to}")
        else:
            print(f"{Fore.YELLOW}[!] no ack after {args.wait_ack:.0f}s (receiver offline or --ack not set)")


if __name__ == "__main__":
    main()
