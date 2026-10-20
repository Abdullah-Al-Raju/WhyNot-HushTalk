#!/usr/bin/env python3
"""WhyNot-HushTalk unified CLI: covert ICMP timing-channel communication suite."""

import argparse
import sys
import time

from colorama import Fore, Style, init

import hushtalk_core as hc
import listen
import whisper

init(autoreset=True)


def cmd_info(args):
    print(f"{Fore.CYAN}{Style.BRIGHT}{'=' * 60}")
    print(f"{Fore.CYAN}{Style.BRIGHT}  WhyNot-HushTalk Covert Channel Suite")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'=' * 60}\n")
    print(f"{Fore.YELLOW}Author: Abduallah Al Raju\n")
    print(f"{Fore.YELLOW}Supported Alphabet ({len(hc.ALPHABET)} symbols):")
    print(f"  {hc.ALPHABET}\n")
    print(f"{Fore.YELLOW}Default Marker Sequences & IDs:")
    print(f"  ICMP ID:      {hc.ICMP_ID}")
    print(f"  Start Marker: seq {hc.START_MARKER}")
    print(f"  End Marker:   seq {hc.END_MARKER}")
    print(f"  Ack Marker:   seq {hc.ACK_MARKER}")
    print(f"  Max Msg Len:  {hc.MAX_MESSAGE_LEN} characters\n")

    print(f"{Fore.YELLOW}Timing Profiles:")
    for name, p in hc.PROFILES.items():
        print(f"  * {Fore.GREEN}{name:<10}{Fore.RESET} base={p.base}ms step={p.step}ms margin=+/-{p.margin}ms jitter=+/-{p.default_jitter}ms")
        print(f"    {Style.DIM}{p.description}{Style.RESET_ALL}")
    print()

    if args.key:
        sess = hc.Session(args.key, profile=args.profile)
        print(f"{Fore.GREEN}Keyed Session Parameters for key={args.key!r} (profile={args.profile}):")
        print(f"  Keyed ICMP ID:   {sess.icmp_id}")
        print(f"  Keyed Start Seq: {sess.start_seq}")
        print(f"  Keyed End Seq:   {sess.end_seq}")
        print(f"  Keyed Ack Seq:   {sess.ack_seq}")
        print(f"  Base Delay:      {sess.base}ms")
        print(f"  Step Delay:      {sess.step}ms")
        print()


def cmd_demo(args):
    whisper.run_simulation_mode(
        text=args.message,
        key=args.key,
        profile_name=args.profile,
        jitter=args.jitter if args.jitter is not None else hc.PROFILES[args.profile].default_jitter,
        payload_style=args.payload,
    )


def cmd_benchmark(args):
    print(f"{Fore.CYAN}{Style.BRIGHT}[*] Running HushTalk Timing & Noise Tolerance Benchmark...")
    print(f"    Testing profile '{args.profile}' across various jitter and loss conditions\n")

    test_messages = [
        "HELLO WORLD",
        "COVERT PING EXFILTRATION 2026",
        "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG",
    ]

    jitter_levels = [0.0, 5.0, 15.0, 25.0, 40.0]
    session = hc.Session(args.key, profile=args.profile)
    codebook = hc.generate_codebook(args.profile)

    print(f"{'Message':<28} | {'Jitter':<8} | {'Status':<10} | {'Clean':<10} | {'Throughput':<12}")
    print("-" * 75)

    for msg in test_messages:
        for j in jitter_levels:
            r = hc.simulate_exchange(msg, session, codebook, jitter=j)
            stats = r["stats"] or {}
            uncertain = stats.get("uncertain", 0)
            total = stats.get("symbols", len(msg))
            clean_pct = f"{((total - uncertain) / total * 100):.0f}%" if total else "0%"
            status = "PASS" if uncertain == 0 else "DEGRADED"
            color = Fore.GREEN if uncertain == 0 else Fore.YELLOW
            cps_str = f"{stats.get('cps', 0.0):.2f} c/s"
            disp_msg = (msg[:25] + "..") if len(msg) > 27 else msg
            print(f"{disp_msg:<28} | +/-{j:>4.1f}ms  | {color}{status:<10}{Fore.RESET} | {clean_pct:<10} | {cps_str:<12}")

    print(f"\n{Fore.GREEN}[+] Benchmark complete.\n")


def cmd_web(args):
    try:
        import uvicorn
    except ImportError:
        print(f"{Fore.RED}[!] uvicorn is required for the web interface: pip install uvicorn fastapi")
        sys.exit(1)

    print(f"{Fore.CYAN}{Style.BRIGHT}[+] Starting WhyNot-HushTalk Web Chat System on http://{args.host}:{args.port}")
    uvicorn.run("web_app:app", host=args.host, port=args.port, log_level="info")


def main():
    parser = argparse.ArgumentParser(
        description="WhyNot-HushTalk: Network ping timing-channel covert communication suite by Abduallah Al Raju",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="command to run")

    # web subparser
    sp_web = subparsers.add_parser("web", help="Launch the local tactical web chat dashboard")
    sp_web.add_argument("--host", default="127.0.0.1", help="host address to bind (default: 127.0.0.1)")
    sp_web.add_argument("--port", type=int, default=8080, help="port to listen on (default: 8080)")

    # whisper subparser
    sp_whisper = subparsers.add_parser("whisper", help="Send a covert message via ICMP/UDP timing delays")
    sp_whisper.add_argument("--to", default=None, help="target IPv4/IPv6 address")
    grp_w = sp_whisper.add_mutually_exclusive_group(required=True)
    grp_w.add_argument("-m", "--message", help="message text")
    grp_w.add_argument("--file", help="read message from file")
    sp_whisper.add_argument("--profile", choices=list(hc.PROFILES.keys()), default="standard")
    sp_whisper.add_argument("--transport", choices=["icmp", "udp"], default="icmp")
    sp_whisper.add_argument("--port", type=int, default=9999)
    sp_whisper.add_argument("--key", default=None, help="shared secret key")
    sp_whisper.add_argument("--payload", choices=["pattern", "windows", "linux", "random", "zero"], default="pattern")
    sp_whisper.add_argument("--payload-len", type=int, default=48)
    sp_whisper.add_argument("--ipv6", action="store_true")
    sp_whisper.add_argument("--iface", default=None)
    sp_whisper.add_argument("--ttl", type=int, default=None)
    sp_whisper.add_argument("--jitter", type=float, default=None)
    sp_whisper.add_argument("--gap", type=float, default=500.0)
    sp_whisper.add_argument("--wait-ack", type=float, default=0.0)
    sp_whisper.add_argument("--simulate", "--dry-run", action="store_true")
    sp_whisper.add_argument("-q", "--quiet", action="store_true")
    sp_whisper.add_argument("-v", "--verbose", action="store_true")

    # listen subparser
    sp_listen = subparsers.add_parser("listen", help="Listen for and decode ICMP/UDP timing delays")
    sp_listen.add_argument("--iface", default=None)
    sp_listen.add_argument("--src", default=None)
    sp_listen.add_argument("--transport", choices=["icmp", "udp"], default="icmp")
    sp_listen.add_argument("--port", type=int, default=9999)
    sp_listen.add_argument("--profile", choices=list(hc.PROFILES.keys()), default="standard")
    sp_listen.add_argument("--key", default=None)
    sp_listen.add_argument("--margin", type=float, default=None)
    sp_listen.add_argument("--timeout", type=float, default=None)
    sp_listen.add_argument("--ack", action="store_true")
    sp_listen.add_argument("--ipv6", action="store_true")
    sp_listen.add_argument("--json", action="store_true")
    sp_listen.add_argument("-v", "--verbose", action="store_true")

    # demo subparser
    sp_demo = subparsers.add_parser("demo", help="Run end-to-end simulated covert exchange without root")
    sp_demo.add_argument("-m", "--message", default="HELLO FROM HUSHTALK", help="message text")
    sp_demo.add_argument("--key", default=None, help="shared secret key")
    sp_demo.add_argument("--profile", choices=list(hc.PROFILES.keys()), default="fast")
    sp_demo.add_argument("--jitter", type=float, default=None)
    sp_demo.add_argument("--payload", choices=["pattern", "windows", "linux", "random", "zero"], default="pattern")

    # info subparser
    sp_info = subparsers.add_parser("info", help="Display protocol details, profiles, and key derivations")
    sp_info.add_argument("--key", default=None)
    sp_info.add_argument("--profile", choices=list(hc.PROFILES.keys()), default="standard")

    # benchmark subparser
    sp_bench = subparsers.add_parser("benchmark", help="Benchmark channel throughput and jitter resistance")
    sp_bench.add_argument("--key", default=None)
    sp_bench.add_argument("--profile", choices=list(hc.PROFILES.keys()), default="fast")

    args = parser.parse_args()

    if args.subcommand == "whisper":
        whisper.main()
    elif args.subcommand == "listen":
        listen.main()
    elif args.subcommand == "demo":
        cmd_demo(args)
    elif args.subcommand == "info":
        cmd_info(args)
    elif args.subcommand == "benchmark":
        cmd_benchmark(args)
    elif args.subcommand == "web":
        cmd_web(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
