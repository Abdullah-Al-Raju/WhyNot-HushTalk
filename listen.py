#!/usr/bin/env python3
"""
WhyNot-HushTalk - PERFECT WITH FINAL 'O'
Captures ALL intervals including the last one to end marker.
"""

import time
import json
import os
from colorama import init, Fore, Style
from scapy.all import sniff, IP, ICMP

init(autoreset=True)

CODEBOOK_DIR = "codebooks"

def load_codebook(name):
    path = os.path.join(CODEBOOK_DIR, name)
    with open(path, "r") as f:
        return json.load(f)

def fuzzy_decode_big(delays, codebook, margin=60):
    reverse_cb = {v: k for k, v in codebook.items()}
    expected_delays = sorted(reverse_cb.keys())
    
    message = ""
    print(f"\n{Fore.CYAN}    Decoding {len(delays)} intervals for {len(delays)+1} letters:")
    for i, d in enumerate(delays):
        closest = min(expected_delays, key=lambda x: abs(x - d))
        diff = abs(closest - d)
        if diff <= margin:
            char = reverse_cb[closest]
            message += char
            print(f"        {Fore.GREEN}→ Letter {i+1}: '{char}' ({d}ms, expected {closest}ms, diff {diff:.0f}ms)")
        else:
            message += "?"
            print(f"        {Fore.RED}→ Letter {i+1}: '?' ({d}ms, closest {closest}ms, diff {diff:.0f}ms)")
    return message

def listen_perfect():
    print(f"{Fore.CYAN}{Style.BRIGHT}[👂] WhyNot-HushTalk - FULL 'HELLO' VERSION")
    print(f"{Fore.YELLOW}[👂] Capturing ALL intervals (including last to end marker)")
    print(f"{Fore.YELLOW}[👂] Tolerance: ±60ms\n")
    
    try:
        codebook = load_codebook("codebook.json")
        print(f"{Fore.GREEN}[✓] Codebook loaded: {len(codebook)} characters\n")
    except:
        print(f"{Fore.RED}[!] Codebook not found")
        return
    
    last_seq = None
    last_time = None
    message_delays = []
    message_started = False
    expected_seq = 101
    first_ping = True
    last_data_time = None
    
    def packet_handler(packet):
        nonlocal last_seq, last_time, message_delays, message_started, expected_seq, first_ping, last_data_time
        
        if IP in packet and ICMP in packet:
            if packet[ICMP].type == 8:
                seq = packet[ICMP].seq
                current_time = time.time() * 1000
                
                # Start marker
                if seq == 100:
                    print(f"{Fore.YELLOW}[🎯] Message started!\n")
                    message_delays = []
                    message_started = True
                    last_time = current_time
                    expected_seq = 101
                    first_ping = True
                    last_data_time = None
                
                # Data packets (101-105)
                elif message_started and 101 <= seq <= 105:
                    if seq == expected_seq and last_time:
                        interval = current_time - last_time
                        
                        if not first_ping:
                            message_delays.append(round(interval, 1))
                            print(f"{Fore.MAGENTA}    Seq {seq}: interval = {interval:.1f}ms (letter {len(message_delays)})")
                        else:
                            print(f"{Fore.CYAN}    Seq {seq}: first ping (skipped)")
                            first_ping = False
                        
                        last_time = current_time
                        last_data_time = current_time
                        expected_seq += 1
                
                # End marker - capture final interval
                elif seq == 999 and message_started and last_data_time:
                    final_interval = current_time - last_data_time
                    message_delays.append(round(final_interval, 1))
                    print(f"{Fore.MAGENTA}    Seq 999: FINAL interval = {final_interval:.1f}ms (letter {len(message_delays)})")
                    
                    if len(message_delays) >= 3:
                        decoded = fuzzy_decode_big(message_delays, codebook)
                        print(f"{Fore.GREEN}{Style.BRIGHT}\n{'='*50}")
                        print(f"[📨] DECODED MESSAGE: '{decoded}'")
                        print(f"{'='*50}\n")
                    
                    message_delays = []
                    message_started = False
                    first_ping = True
                    last_data_time = None

    print(f"{Fore.CYAN}[👂] Listening...")
    print(f"{Fore.YELLOW}Send: sudo python whisper_scapy.py --to 127.0.0.1 --message \"HELLO\"\n")
    
    try:
        sniff(iface="lo", prn=packet_handler, store=0, filter="icmp")
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}[👂] Stopped.")

if __name__ == "__main__":
    listen_perfect()
