#!/usr/bin/env python3
"""WhyNot-HushTalk receiver: listens for ICMP/UDP timing patterns and decodes them."""

import argparse
import json
import socket
import struct
import sys
import time

from colorama import Fore, Style, init

from hushtalk_core import (
    PROFILES,
    Receiver,
    Session,
    generate_codebook,
    load_codebook,
)

init(autoreset=True)

try:
    from scapy.all import ICMP, IP, Raw, conf, send, sniff

    conf.verb = 0
    SCAPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    SCAPY_AVAILABLE = False


def send_ack(target, session, iface=None, is_ipv6=False, transport="icmp", port=9999, sock=None):
    if transport == "udp":
        if sock:
            hdr = struct.pack("!HH", session.icmp_id, session.ack_seq)
            for _ in range(3):
                try:
                    sock.sendto(hdr + b"\x00" * 16, target)
                except Exception:
                    pass
                time.sleep(0.05)
        return

    for _ in range(3):
        if is_ipv6:
            from scapy.layers.inet6 import IPv6, ICMPv6EchoRequest

            pkt = IPv6(dst=target) / ICMPv6EchoRequest(id=session.icmp_id, seq=session.ack_seq, data=b"\x00" * 16)
        else:
            pkt = IP(dst=target) / ICMP(type=8, id=session.icmp_id, seq=session.ack_seq) / Raw(load=b"\x00" * 16)
        if iface:
            send(pkt, iface=iface, verbose=False)
        else:
            send(pkt, verbose=False)
        time.sleep(0.05)


def make_handler(session, codebook, args, is_ipv6=False, udp_sock=None):
    state = {"sender": None, "sender_addr": None}

    def on_event(ev, data):
        if args.json:
            event_obj = {"event": ev, "timestamp": time.time(), "data": data}
            print(json.dumps(event_obj))
            sys.stdout.flush()
            if ev == "message" and args.ack:
                if args.transport == "udp" and state["sender_addr"]:
                    send_ack(state["sender_addr"], session, transport="udp", sock=udp_sock)
                elif state["sender"]:
                    send_ack(state["sender"], session, args.iface, is_ipv6)
            return

        if ev == "start":
            print(f"{Fore.YELLOW}[🎯] message started")
        elif ev == "message":
            msg = data.get("message", "")
            uncertain = data.get("uncertain", 0)
            total = data.get("symbols", 0)
            elapsed_s = data.get("elapsed_ms", 0.0) / 1000.0
            cps = data.get("cps", 0.0)
            avg_j = data.get("avg_jitter_ms", 0.0)
            max_j = data.get("max_jitter_ms", 0.0)

            color = Fore.GREEN if uncertain == 0 else Fore.YELLOW
            print(f"{color}{Style.BRIGHT}{'=' * 56}")
            print(f"[📨] DECODED: {msg!r}")
            if uncertain:
                print(f"{color}[!] {uncertain}/{total} symbols uncertain")
            else:
                print(f"{color}[✓] clean decode, {total} symbols")
            print(f"{Fore.CYAN}[📊] Duration: {elapsed_s:.1f}s ({cps:.2f} chars/s) | Jitter avg: {avg_j:.1f}ms max: {max_j:.1f}ms")
            print(f"{Style.BRIGHT}{'=' * 56}\n")
            if args.ack:
                if args.transport == "udp" and state["sender_addr"]:
                    send_ack(state["sender_addr"], session, transport="udp", sock=udp_sock)
                    print(f"{Fore.GREEN}[→] ack sent to {state['sender_addr'][0]}:{state['sender_addr'][1]}")
                elif state["sender"]:
                    send_ack(state["sender"], session, args.iface, is_ipv6)
                    print(f"{Fore.GREEN}[→] ack sent to {state['sender']}")
        elif ev == "timeout":
            partial = data.get("partial", "")
            if partial:
                print(f"{Fore.RED}[⌛] message timed out, partial: {partial!r}")

    receiver = Receiver(
        session,
        codebook,
        margin=args.margin if args.margin is not None else session.profile.margin,
        timeout_ms=args.timeout * 1000.0 if args.timeout else None,
        on_event=on_event,
    )

    def packet_handler(pkt):
        if is_ipv6:
            from scapy.layers.inet6 import IPv6, ICMPv6EchoRequest

            if IPv6 not in pkt or ICMPv6EchoRequest not in pkt:
                return
            icmp = pkt[ICMPv6EchoRequest]
            if icmp.id != session.icmp_id:
                return
            src = pkt[IPv6].src
            seq = icmp.seq
        else:
            if IP not in pkt or ICMP not in pkt:
                return
            icmp = pkt[ICMP]
            if icmp.type != 8 or icmp.id != session.icmp_id:
                return
            src = pkt[IP].src
            seq = icmp.seq

        if args.src and src != args.src:
            return
        state["sender"] = src
        now = time.time() * 1000.0
        if args.verbose and not args.json:
            print(f"{Fore.CYAN}    seq={seq} from {src}")
        receiver.on_packet(now, seq)

    return packet_handler, receiver, state


def main():
    parser = argparse.ArgumentParser(description="HushTalk receiver: decode hidden messages from ping timing")
    parser.add_argument("--iface", default=None, help="interface to listen on (default: all)")
    parser.add_argument("--src", default=None, help="only accept packets from this IP")
    parser.add_argument("--listen-ip", default="", help="bind IP for UDP transport (default: 0.0.0.0 or ::)")
    parser.add_argument("--transport", choices=["icmp", "udp"], default="icmp",
                        help="transport mode: icmp (default, requires root/Npcap) or udp (unprivileged userland)")
    parser.add_argument("--port", type=int, default=9999, help="listen UDP port when using --transport udp")
    parser.add_argument("--codebook", default="codebook.json", help="path to custom codebook JSON")
    parser.add_argument("--profile", choices=list(PROFILES.keys()), default="standard",
                        help="timing profile: standard (default), fast (LAN/lab), stealth (low rate)")
    parser.add_argument("--key", default=None, help="shared secret (must match sender)")
    parser.add_argument("--margin", type=float, default=None,
                        help="max ms deviation from expected delay (default: auto from profile)")
    parser.add_argument("--timeout", type=float, default=None,
                        help="seconds of silence before abandoning a message (default: auto from delays)")
    parser.add_argument("--ack", action="store_true", help="reply with an ack burst after each decode")
    parser.add_argument("--ipv6", action="store_true", help="listen for IPv6")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON events")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.transport == "icmp" and not SCAPY_AVAILABLE:
        print(f"{Fore.RED}[!] scapy is required for ICMP sniffing: pip install scapy")
        sys.exit(1)

    profile_name = args.profile
    if profile_name != "standard":
        codebook = generate_codebook(profile_name)
    else:
        try:
            codebook = load_codebook(args.codebook)
        except FileNotFoundError as err:
            if not args.json:
                print(f"{Fore.YELLOW}[!] Codebook '{args.codebook}' not found, using standard profile: {err}")
            codebook = generate_codebook("standard")

    session = Session(args.key, profile=profile_name)

    eff_margin = args.margin if args.margin is not None else session.profile.margin

    if not args.json:
        what = "keyed" if args.key else "codebook"
        proto_label = f"UDP:{args.port}" if args.transport == "udp" else ("IPv6/ICMPv6" if args.ipv6 else "IPv4/ICMP")
        print(f"{Fore.CYAN}{Style.BRIGHT}[👂] HushTalk listening ({what} session, profile={profile_name}) [{proto_label}]")
        print(f"{Fore.YELLOW}      id={session.icmp_id} "
              f"seq {session.start_seq}..{session.end_seq} margin=±{eff_margin:.0f}ms")
        if args.transport == "icmp" and args.iface is None:
            print(f"{Fore.YELLOW}      all interfaces (use --iface to narrow)")
        send_cmd = (
            f"python whisper.py --to 127.0.0.1 -m \"HELLO\" --profile {profile_name}"
            + (f" --transport udp --port {args.port}" if args.transport == "udp" else "")
            + (f" --key <secret>" if args.key else "")
            + (" --ipv6" if args.ipv6 else "")
        )
        print(f"{Fore.CYAN}[👂] Send from another shell: {send_cmd}\n")

    if args.transport == "udp":
        sock = socket.socket(socket.AF_INET6 if args.ipv6 else socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((args.listen_ip, args.port))
        sock.settimeout(1.0)
        packet_handler, receiver, state = make_handler(session, codebook, args, is_ipv6=args.ipv6, udp_sock=sock)

        try:
            while True:
                try:
                    data, addr = sock.recvfrom(2048)
                    if len(data) >= 4:
                        hdr_id, seq = struct.unpack("!HH", data[:4])
                        if hdr_id == session.icmp_id:
                            src_ip = addr[0]
                            if args.src and src_ip != args.src:
                                continue
                            state["sender"] = src_ip
                            state["sender_addr"] = addr
                            now = time.time() * 1000.0
                            if args.verbose and not args.json:
                                print(f"{Fore.CYAN}    seq={seq} from {src_ip}:{addr[1]}")
                            receiver.on_packet(now, seq)
                except socket.timeout:
                    pass
                receiver.tick(time.time() * 1000.0)
        except KeyboardInterrupt:
            if not args.json:
                print(f"\n{Fore.RED}[👂] stopped.")
        finally:
            sock.close()
        return

    # ICMP mode
    packet_handler, receiver, state = make_handler(session, codebook, args, is_ipv6=args.ipv6)
    bpf = "icmp6" if args.ipv6 else "icmp"
    if args.src:
        bpf += f" and src {args.src}"

    try:
        while True:
            sniff(iface=args.iface, prn=packet_handler, store=0, filter=bpf, timeout=1.0)
            receiver.tick(time.time() * 1000.0)
    except (PermissionError, Exception) as exc:
        if isinstance(exc, KeyboardInterrupt):
            if not args.json:
                print(f"\n{Fore.RED}[👂] stopped.")
        else:
            if not args.json:
                print(f"{Fore.RED}[!] Sniffer failed: {exc}")
                print(f"{Fore.YELLOW}[!] Note: Sniffing raw ICMP packets requires root privileges (sudo python3 listen.py) or CAP_NET_RAW capability.")
                print(f"{Fore.YELLOW}[!] Alternatively, run in userland mode without root using: --transport udp --port {args.port}")
            else:
                print(json.dumps({"error": str(exc)}))
            sys.exit(1)


if __name__ == "__main__":
    main()
