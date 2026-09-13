#!/usr/bin/env python3
"""WhyNot-HushTalk receiver: listens for ICMP timing patterns and decodes them."""

import argparse
import sys
import time

from colorama import Fore, Style, init

from hushtalk_core import Receiver, Session, load_codebook

init(autoreset=True)

try:
    from scapy.all import ICMP, IP, Raw, conf, send, sniff

    conf.verb = 0
except ImportError:  # pragma: no cover
    print("scapy is required: pip install scapy")
    sys.exit(1)


def send_ack(target, session, iface=None):
    for _ in range(3):
        pkt = IP(dst=target) / ICMP(type=8, id=session.icmp_id, seq=session.ack_seq) / Raw(load=b"\x00" * 16)
        if iface:
            send(pkt, iface=iface, verbose=False)
        else:
            send(pkt, verbose=False)
        time.sleep(0.05)


def make_handler(session, codebook, args):
    state = {"sender": None}

    def on_event(ev, data):
        if ev == "start":
            print(f"{Fore.YELLOW}[🎯] message started")
        elif ev == "message":
            msg, uncertain, total = data["message"], data["uncertain"], data["symbols"]
            color = Fore.GREEN if uncertain == 0 else Fore.YELLOW
            print(f"{color}{Style.BRIGHT}{'=' * 50}")
            print(f"[📨] DECODED: {msg!r}")
            if uncertain:
                print(f"{color}[!] {uncertain}/{total} symbols uncertain")
            else:
                print(f"{color}[✓] clean decode, {total} symbols")
            print(f"{Style.BRIGHT}{'=' * 50}\n")
            if args.ack and state["sender"]:
                send_ack(state["sender"], session, args.iface)
                print(f"{Fore.GREEN}[→] ack sent to {state['sender']}")
        elif ev == "timeout":
            partial = data.get("partial", "")
            if partial:
                print(f"{Fore.RED}[⌛] message timed out, partial: {partial!r}")

    receiver = Receiver(
        session,
        codebook,
        margin=args.margin,
        timeout_ms=args.timeout * 1000.0 if args.timeout else None,
        on_event=on_event,
    )

    def handler(pkt):
        if IP not in pkt or ICMP not in pkt:
            return
        icmp = pkt[ICMP]
        if icmp.type != 8 or icmp.id != session.icmp_id:
            return
        if args.src and pkt[IP].src != args.src:
            return
        state["sender"] = pkt[IP].src
        now = time.time() * 1000.0
        if args.verbose:
            print(f"{Fore.CYAN}    seq={icmp.seq} from {pkt[IP].src}")
        receiver.on_packet(now, icmp.seq)

    return handler


def main():
    parser = argparse.ArgumentParser(description="HushTalk receiver: decode hidden messages from ping timing")
    parser.add_argument("--iface", default=None, help="interface to listen on (default: all)")
    parser.add_argument("--src", default=None, help="only accept pings from this IP")
    parser.add_argument("--codebook", default="codebook.json")
    parser.add_argument("--key", default=None, help="shared secret (must match sender)")
    parser.add_argument("--margin", type=float, default=45.0, help="max ms deviation from expected delay")
    parser.add_argument("--timeout", type=float, default=None,
                        help="seconds of silence before abandoning a message (default: derived from session delays)")
    parser.add_argument("--ack", action="store_true", help="reply with an ack burst after each decode")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    codebook = load_codebook(args.codebook)
    session = Session(args.key)
    handler = make_handler(session, codebook, args)

    what = "keyed" if args.key else "codebook"
    print(f"{Fore.CYAN}{Style.BRIGHT}[👂] HushTalk listening ({what} session)")
    print(f"{Fore.YELLOW}      icmp_id={session.icmp_id} "
          f"seq {session.start_seq}..{session.end_seq} margin=±{args.margin:.0f}ms")
    if args.iface is None:
        print(f"{Fore.YELLOW}      all interfaces (use --iface to narrow)")
    print(f"{Fore.CYAN}[👂] Send from another shell: "
          f"python whisper.py --to <this-ip> -m \"HELLO\""
          + (f" --key <secret>" if args.key else "") + "\n")

    bpf = "icmp"
    if args.src:
        bpf += f" and src {args.src}"

    try:
        sniff(iface=args.iface, prn=handler, store=0, filter=bpf)
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}[👂] stopped.")


if __name__ == "__main__":
    main()
