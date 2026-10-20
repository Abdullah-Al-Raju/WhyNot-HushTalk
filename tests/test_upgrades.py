import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hushtalk_core as hc
import whisper


class TestTimingProfilesAndCodebook(unittest.TestCase):
    def test_codebook_resolution_from_any_cwd(self):
        # Should resolve cleanly without specifying directory
        cb = hc.load_codebook("codebook.json")
        self.assertIn("A", cb)
        self.assertEqual(cb["A"], 500.0)
        self.assertEqual(cb["B"], 600.0)

    def test_generate_codebook_standard_matches_json(self):
        cb_json = hc.load_codebook("codebook.json")
        cb_gen = hc.generate_codebook("standard")
        for char, delay in cb_json.items():
            self.assertEqual(cb_gen[char], delay, f"Mismatch for char {char}")

    def test_timing_profiles_parameters(self):
        fast = hc.PROFILES["fast"]
        self.assertLess(fast.base, 100.0)
        self.assertLess(fast.step, 50.0)

        stealth = hc.PROFILES["stealth"]
        self.assertGreater(stealth.base, 1000.0)

    def test_session_fast_profile(self):
        sess = hc.Session("mykey", profile="fast")
        delays = sess.delays_for("HELLO")
        self.assertEqual(len(delays), 5)
        self.assertTrue(all(d < 1500 for d in delays))

    def test_invalid_profile_raises(self):
        with self.assertRaises(ValueError):
            hc.generate_codebook("nonexistent_profile")
        with self.assertRaises(ValueError):
            hc.Session("key", profile="nonexistent_profile")


class TestCoverPayloads(unittest.TestCase):
    def test_pattern_payload(self):
        p = hc.generate_payload("pattern", length=48)
        self.assertEqual(len(p), 48)
        self.assertTrue(p.startswith(b"abcdefghijklmnop"))

    def test_windows_payload(self):
        p = hc.generate_payload("windows", length=32)
        self.assertEqual(len(p), 32)
        self.assertEqual(p, b"abcdefghijklmnopqrstuvwabcdefghi")

    def test_linux_payload(self):
        p = hc.generate_payload("linux", length=56)
        self.assertEqual(len(p), 56)

    def test_random_payload(self):
        p1 = hc.generate_payload("random", length=48)
        p2 = hc.generate_payload("random", length=48)
        self.assertEqual(len(p1), 48)
        self.assertEqual(len(p2), 48)
        self.assertNotEqual(p1, p2)

    def test_zero_payload(self):
        p = hc.generate_payload("zero", length=32)
        self.assertEqual(p, b"\x00" * 32)

    def test_invalid_payload_style(self):
        with self.assertRaises(ValueError):
            hc.generate_payload("quantum")


class TestReceiverTelemetry(unittest.TestCase):
    def test_telemetry_fields(self):
        session = hc.Session(None, profile="fast")
        codebook = hc.generate_codebook("fast")
        sim = hc.simulate_exchange("TEST", session, codebook, jitter=3.0)
        stats = sim["stats"]
        self.assertIsNotNone(stats)
        self.assertEqual(stats["message"], "TEST")
        self.assertEqual(stats["symbols"], 4)
        self.assertEqual(stats["uncertain"], 0)
        self.assertIn("elapsed_ms", stats)
        self.assertIn("cps", stats)
        self.assertIn("avg_jitter_ms", stats)
        self.assertIn("max_jitter_ms", stats)
        self.assertGreater(stats["cps"], 0.0)


class TestSimulationRunner(unittest.TestCase):
    def test_simulate_run_keyed_fast(self):
        res = hc.simulate_run(
            message="TOP SECRET 42",
            key="quantum_vault",
            profile="fast",
            jitter=4.0,
            payload_style="windows",
        )
        self.assertEqual(res["received"], "TOP SECRET 42")
        self.assertEqual(res["session"]["profile"], "fast")
        self.assertEqual(res["session"]["payload_style"], "windows")
        self.assertGreater(res["session"]["icmp_id"], 0)


class TestPacketBuilding(unittest.TestCase):
    def test_build_ipv4_ping(self):
        session = hc.Session("testkey")
        payload = hc.generate_payload("windows", 32)
        pkt = whisper.build_ping("127.0.0.1", session, seq=105, ttl=64, payload=payload, is_ipv6=False)
        self.assertEqual(pkt.dst, "127.0.0.1")
        self.assertEqual(pkt.ttl, 64)
        self.assertEqual(pkt.payload.id, session.icmp_id)
        self.assertEqual(pkt.payload.seq, 105)

    def test_build_ipv6_ping(self):
        session = hc.Session("testkey")
        payload = hc.generate_payload("zero", 32)
        pkt = whisper.build_ping("::1", session, seq=106, ttl=128, payload=payload, is_ipv6=True)
        self.assertEqual(pkt.dst, "::1")
        self.assertEqual(pkt.hlim, 128)
        self.assertEqual(pkt.payload.id, session.icmp_id)
        self.assertEqual(pkt.payload.seq, 106)


if __name__ == "__main__":
    unittest.main()
