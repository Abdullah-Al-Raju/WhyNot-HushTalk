#!/usr/bin/env python3
"""
WhyNot-HushTalk - SCAPY SENDER (FIXED)
Waits for the final delay before sending end marker.
"""

import time
import json
import os
import argparse
from colorama import init, Fore, Style
from scapy.all import IP, ICMP, sr1, conf

init(autoreset=True)
conf.verb = 0

CODEBOOK_DIR = "codebooks"

def load_codebook(name):
    path = os.path.join(CODEBOOK_DIR, name)
    with open(path, "r") as f:
        return json.load(f)

def encode_message(message, codebook):
    delays = []
    for char in message.upper():
        if char in codebook:
            delays.append(codebook[char])
        else:
            delays.append(codebook.get("?", 4100))
    return delays

def send_ping_with_seq(target_ip, seq_num):
    """Send ICMP echo request with custom sequence number"""
    packet = IP(dst=target_ip)/ICMP(type=8, id=12345, seq=seq_num)
    sr1(packet, timeout=1, verbose=False)
    return True

def send_message(target_ip, message, codebook):
    delays = encode_message(message, codebook)
    print(f"{Fore.CYAN}[→] Sending: {message}")
    print(f"{Fore.YELLOW}[→] Encoded delays (ms): {delays}")
    print(f"{Fore.YELLOW}[→] Using custom sequence numbers (100+)\n")
    
    # Send start marker
    print(f"{Fore.BLUE}    Sending start marker (seq 100)")
    send_ping_with_seq(target_ip, 100)
    time.sleep(0.5)
    
    # Send data pings with delays
    for i, delay in enumerate(delays):
        seq_num = 101 + i
        print(f"{Fore.BLUE}    [{i+1}/{len(delays)}] Sending ping seq={seq_num}, then waiting {delay}ms")
        send_ping_with_seq(target_ip, seq_num)
        time.sleep(delay / 1000.0)  # Wait the encoded delay
    
    # Send end marker AFTER all delays
    print(f"{Fore.BLUE}    Sending end marker (seq 999)")
    send_ping_with_seq(target_ip, 999)
    print(f"\n{Fore.GREEN}[✓] Message sent to {target_ip}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--to', required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--codebook', default='codebook.json')
    args = parser.parse_args()
    
    codebook = load_codebook(args.codebook)
    send_message(args.to, args.message, codebook)

if __name__ == "__main__":
    main()
