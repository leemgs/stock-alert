import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import multi_stock_alert as alert


class RuntimeStateTests(unittest.TestCase):
    def test_alert_email_colors_buy_blue_and_sell_red(self):
        cfg = {
            "UPDATE_THRESHOLD_DOWN_PERCENT": 10,
            "UPDATE_THRESHOLD_UP_PERCENT": 10,
        }
        down = [("AI", "Buy", "BUY", 90.0, 100.0, 90.0, "")]
        up = [("AI", "Sell", "SELL", 110.0, 100.0, 110.0, "")]

        html = alert.generate_html_body(cfg, "2026-08-17", down, up, [], [])

        self.assertIn("하락 목표 도달 (매수)", html)
        self.assertIn("color:#2563eb;", html)
        self.assertIn("상승 목표 도달 (매도)", html)
        self.assertIn("color:#dc2626;", html)

    def test_empty_cached_state_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("{}", encoding="utf-8")
            with mock.patch.object(alert, "STATE_PATH", state_path):
                state = alert.load_state()

        self.assertEqual(state["alert_counters"], {"date": None, "per": {}})
        self.assertEqual(state["global_counter"], {"date": None, "count": 0})
        self.assertEqual(state["last_alert_date"], {})
        self.assertEqual(state["last_price"], {})

    def test_smtp_failure_does_not_consume_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            stock_path = base / "stock.txt"
            state_path = base / "state.json"
            history_path = base / "history.json"
            config_path = base / "config.txt"
            original = "AI, Example, EXAMPLE, 90, 100, test\n"
            stock_path.write_text(original, encoding="utf-8")

            env = {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "587",
                "SMTP_USER": "bot@example.com",
                "SMTP_PASS": "secret",
                "EMAIL_FROM": "bot@example.com",
                "EMAIL_TO": "owner@example.com",
            }
            paths = mock.patch.multiple(
                alert,
                CONFIG_PATH=config_path,
                STOCKS_PATH=stock_path,
                STATE_PATH=state_path,
                HISTORY_PATH=history_path,
            )
            with paths, mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(alert, "fetch_price", return_value=110.0), \
                    mock.patch.object(alert, "send_email", side_effect=OSError("SMTP unavailable")):
                with self.assertRaisesRegex(RuntimeError, "메일 발송 실패"):
                    alert.main()

            self.assertEqual(stock_path.read_text(encoding="utf-8"), original)
            self.assertFalse(state_path.exists())
            self.assertFalse(history_path.exists())


if __name__ == "__main__":
    unittest.main()
