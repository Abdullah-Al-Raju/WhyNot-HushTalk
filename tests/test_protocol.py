import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hushtalk_core as hc


def codebook():
    return hc.load_codebook("codebook.json", directory=hc.os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "codebooks"))


CB = codebook()


class EncodeDecode(unittest.TestCase):
    def test_roundtrip_no_jitter(self):
        r = hc.simulate_exchange("HELLO", hc.Session(None), CB, jitter=0.0)
        self.assertEqual(r["received"], "HELLO")

    def test_roundtrip_with_jitter_many_seeds(self):
        session = hc.Session(None)
        for seed in range(15):
            for msg in ["HELLO", "ATTACK AT DAWN", "EXFIL TRAITOR 12345?", "A"]:
                r = hc.simulate_exchange(
                    msg, session, CB, jitter=30.0, rng=random.Random(seed * 131 + len(msg))
                )
                self.assertEqual(r["received"], msg, f"seed={seed} msg={msg!r}")

    def test_long_message_regression(self):
        msg = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 END"
        self.assertGreater(len(msg), 5)
        r = hc.simulate_exchange(msg, hc.Session(None), CB, jitter=30.0, rng=random.Random(7))
        self.assertEqual(r["received"], msg)

    def test_case_folding_and_unknown_chars(self):
        prepared = hc.prepare_message("hello; world!", hc.Session(None), CB)
        self.assertEqual(prepared, "HELLO  WORLD!")

    def test_too_long_message(self):
        with self.assertRaises(ValueError):
            hc.encode_delays("A" * (hc.MAX_MESSAGE_LEN + 1), hc.Session(None), CB)


class LossResync(unittest.TestCase):
    def test_single_loss_keeps_alignment(self):
        msg = "ABCDEFGH"
        session = hc.Session(None)
        delays, prepared = hc.encode_delays(msg, session, CB)
        lost_seq = session.start_seq + 3
        r = hc.simulate_exchange(msg, session, CB, jitter=20.0,
                                 drop_seqs={lost_seq}, rng=random.Random(3))
        self.assertIsNotNone(r["received"])
        self.assertEqual(len(r["received"]), len(prepared))
        for got, want in zip(r["received"], prepared):
            if got != "?":
                self.assertEqual(got, want)
        self.assertGreater(r["received"].count("?"), 0)

    def test_stale_and_reordered_packets_ignored(self):
        session = hc.Session(None)
        r = {}
        rec = hc.Receiver(session, CB, on_event=lambda ev, d: r.update(ev=ev, data=d))
        rec.on_packet(0.0, session.start_seq)        # start marker
        rec.on_packet(500.0, session.start_seq + 1)  # first data ping (skipped)
        rec.on_packet(1700.0, session.start_seq + 2)  # interval 1200 -> 'H'
        rec.on_packet(1700.0, session.start_seq + 1)  # stale duplicate, ignored
        rec.on_packet(1600.0, session.start_seq + 1)  # out-of-order, ignored
        rec.on_packet(3000.0, session.end_seq)       # interval 1300 -> 'I'
        self.assertEqual(r["data"]["message"], "HI")

    def test_timeout_resets_state(self):
        session = hc.Session(None)
        events = []
        rec = hc.Receiver(session, CB, timeout_ms=6500, on_event=lambda ev, d: events.append((ev, d)))
        rec.on_packet(0.0, session.start_seq)
        rec.on_packet(1000.0, session.start_seq + 1)
        rec.on_packet(100000.0, session.start_seq + 2)
        self.assertTrue(any(ev == "timeout" for ev, _ in events))
        self.assertFalse(rec.started)


class KeyedSession(unittest.TestCase):
    KEY = "correct horse"

    def test_keyed_roundtrip(self):
        session = hc.Session(self.KEY)
        for seed in range(8):
            r = hc.simulate_exchange("MEET AT BRIDGE 9", session, CB, jitter=30.0,
                                     rng=random.Random(seed))
            self.assertEqual(r["received"], "MEET AT BRIDGE 9")

    def test_keyed_markers_and_id_are_not_defaults(self):
        session = hc.Session(self.KEY)
        self.assertNotEqual(session.icmp_id, hc.ICMP_ID)
        self.assertNotEqual(session.start_seq, hc.START_MARKER)
        self.assertNotEqual(session.end_seq, hc.END_MARKER)
        other = hc.Session("different key")
        self.assertNotEqual(session.icmp_id, other.icmp_id)

    def test_keyed_delays_are_polyalphabetic(self):
        session = hc.Session(self.KEY)
        delays, _ = hc.encode_delays("AAAAAAAAAA", session, CB)
        self.assertGreater(len(set(delays)), 1)
        self.assertNotEqual(delays, [CB["A"]] * 10)
        for d in delays:
            self.assertIn(d, session.expected_delays(CB))

    def test_wrong_key_does_not_recover_plaintext(self):
        session = hc.Session(self.KEY)
        rec = hc.Receiver(hc.Session("wrong key"), CB)
        delays, _ = hc.encode_delays("TOP SECRET", session, CB)
        t = 0.0
        rec.on_packet(t, session.start_seq)
        for i, d in enumerate(delays):
            t += d
            rec.on_packet(t, session.start_seq + 1 + i)
        t += delays[-1]
        rec.on_packet(t, session.end_seq)
        self.assertNotEqual(rec.current_message(), "TOP SECRET")


class Ack(unittest.TestCase):
    def test_ack_packets_do_not_disturb_receiver(self):
        session = hc.Session("k")
        r = {}
        rec = hc.Receiver(session, CB, on_event=lambda ev, d: r.update(data=d))
        rec.on_packet(0.0, session.start_seq)
        rec.on_packet(500.0, session.start_seq + 1)
        rec.on_packet(1000.0, session.ack_seq)
        rec.on_packet(1000.0, session.ack_seq)
        rec.on_packet(1500.0, session.end_seq)
        self.assertIn("data", r)


if __name__ == "__main__":
    unittest.main()
