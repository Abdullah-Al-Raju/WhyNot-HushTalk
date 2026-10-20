import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from hushtalk_node import HushTalkNode
import web_app


class TestHushTalkNode(unittest.TestCase):
    def test_node_lifecycle_and_configuration(self):
        node = HushTalkNode(
            target_ip="127.0.0.1",
            port=19999,
            key="SECRET_TEST",
            profile="fast",
            transport="udp",
        )
        status = node.get_status()
        self.assertEqual(status["target_ip"], "127.0.0.1")
        self.assertEqual(status["port"], 19999)
        self.assertEqual(status["profile"], "fast")
        self.assertTrue(status["has_key"])

        # Update config
        updated = node.configure(target_ip="10.0.0.5", profile="standard")
        self.assertEqual(updated["target_ip"], "10.0.0.5")
        self.assertEqual(updated["profile"], "standard")

    def test_node_subscribers_and_message_enqueue(self):
        node = HushTalkNode(port=19998)
        events = []
        node.subscribe(lambda ev: events.append(ev))

        msg = node.send_chat_message("TEST MESSAGE")
        self.assertEqual(msg.text, "TEST MESSAGE")
        self.assertEqual(msg.status, "queued")
        self.assertTrue(any(ev["type"] == "message_queued" for ev in events))

        msgs = node.get_messages()
        self.assertGreaterEqual(len(msgs), 1)
        self.assertEqual(msgs[-1]["text"], "TEST MESSAGE")


class TestWebAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web_app.app)

    def test_api_status(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("transport", data)
        self.assertIn("profile", data)
        self.assertIn("timing_telemetry", data)

    def test_api_config(self):
        payload = {
            "target_ip": "127.0.0.1",
            "port": 9999,
            "profile": "fast",
            "key": "web_test_key",
        }
        response = self.client.post("/api/config", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["config"]["key_preview"], "web...ey")

    def test_api_messages(self):
        response = self.client.post("/api/messages", json={"message": "WEB CHAT TEST"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "enqueued")
        self.assertIn("message_id", data)

        res_list = self.client.get("/api/messages")
        self.assertEqual(res_list.status_code, 200)
        msgs = res_list.json()["messages"]
        self.assertTrue(any(m["text"] == "WEB CHAT TEST" for m in msgs))

    def test_api_telemetry(self):
        response = self.client.get("/api/telemetry")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("recent_packets", data)
        self.assertIn("inter_arrival_times", data)

    def test_api_demo(self):
        response = self.client.post("/api/demo", json={"message": "DEMO TEST", "profile": "fast"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["received"], "DEMO TEST")


if __name__ == "__main__":
    unittest.main()
