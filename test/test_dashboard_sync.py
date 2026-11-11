import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "generate_dashboard_data.py"
spec = importlib.util.spec_from_file_location("generate_dashboard_data", SRC)
gdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gdd)


def _write(tmp, stock_lines, tickers, generated_at="2026-11-10T15:25:38+09:00"):
    stock = tmp / "stock.txt"
    stock.write_text("\n".join(stock_lines) + "\n", encoding="utf-8")
    hist = tmp / "history.json"
    hist.write_text(json.dumps({
        "generated_at": generated_at, "domains": ["항공"], "count": len(tickers),
        "tickers": tickers, "errors": [],
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return stock, hist


def _jeju(up=7600.0, down=3726.0):
    return {"name": "Jeju Air", "domain": "항공", "ticker": "089590.KS", "desc": "LCC",
            "down": down, "up": up, "current": 7430.0, "series": [["2026-11-10", 7430.0]]}


class SyncThresholdsTests(unittest.TestCase):
    def test_bot_threshold_update_is_reflected_without_touching_prices(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            stock, hist = _write(tmp, ["항공, Jeju Air, 089590.KS, 3726, 8360.00, LCC"],
                                 {"089590.KS": _jeju()})
            changes = gdd.sync_thresholds(stock, hist)
            self.assertEqual(changes, [("089590.KS", "up", 7600.0, 8360.0)])
            out = json.loads(hist.read_text(encoding="utf-8"))
            t = out["tickers"]["089590.KS"]
            self.assertEqual(t["up"], 8360.0)
            self.assertEqual(t["down"], 3726.0)
            self.assertEqual(t["current"], 7430.0)                       # 시세는 그대로
            self.assertEqual(t["series"], [["2026-11-10", 7430.0]])      # 차트도 그대로
            self.assertEqual(out["generated_at"], "2026-11-10T15:25:38+09:00")

    def test_no_change_does_not_rewrite_file(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            stock, hist = _write(tmp, ["항공, Jeju Air, 089590.KS, 3726, 7600, LCC"],
                                 {"089590.KS": _jeju()})
            before = hist.read_bytes()
            mtime = hist.stat().st_mtime_ns
            self.assertEqual(gdd.sync_thresholds(stock, hist), [])
            self.assertEqual(hist.read_bytes(), before)
            self.assertEqual(hist.stat().st_mtime_ns, mtime)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            stock, hist = _write(tmp, ["항공, Jeju Air, 089590.KS, 3726, 8360.00, LCC"],
                                 {"089590.KS": _jeju()})
            self.assertEqual(len(gdd.sync_thresholds(stock, hist)), 1)
            self.assertEqual(gdd.sync_thresholds(stock, hist), [])

    def test_ticker_not_in_history_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            stock, hist = _write(
                tmp,
                ["항공, Jeju Air, 089590.KS, 3726, 7600, LCC",
                 "농업, Teucrium Corn Fund, CORN, 16, 20, 옥수수"],
                {"089590.KS": _jeju()})
            self.assertEqual(gdd.sync_thresholds(stock, hist), [])
            self.assertNotIn("CORN", json.loads(hist.read_text(encoding="utf-8"))["tickers"])

    def test_blank_threshold_becomes_null(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            stock, hist = _write(tmp, ["항공, Jeju Air, 089590.KS, , 7600, LCC"],
                                 {"089590.KS": _jeju()})
            gdd.sync_thresholds(stock, hist)
            t = json.loads(hist.read_text(encoding="utf-8"))["tickers"]["089590.KS"]
            self.assertIsNone(t["down"])
            self.assertEqual(t["up"], 7600.0)

    def test_name_domain_desc_edits_are_synced_and_domains_rebuilt(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            stock, hist = _write(tmp, ["여행, 제주항공, 089590.KS, 3726, 7600, 새 설명"],
                                 {"089590.KS": _jeju()})
            gdd.sync_thresholds(stock, hist)
            out = json.loads(hist.read_text(encoding="utf-8"))
            t = out["tickers"]["089590.KS"]
            self.assertEqual((t["name"], t["domain"], t["desc"]), ("제주항공", "여행", "새 설명"))
            self.assertEqual(out["domains"], ["여행"])

    def test_missing_history_file_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            stock = tmp / "stock.txt"
            stock.write_text("항공, Jeju Air, 089590.KS, 3726, 7600, LCC\n", encoding="utf-8")
            self.assertEqual(gdd.sync_thresholds(stock, tmp / "nope.json"), [])

    def test_real_history_roundtrip_is_byte_identical(self):
        """동기화로 불필요한 diff 가 생기지 않는지: 변경이 없을 때 실제 파일을 건드리지 않아야 한다."""
        repo = Path(__file__).resolve().parent.parent
        real = repo / "docs" / "data" / "history.json"
        if not real.exists():
            self.skipTest("history.json 없음")
        raw = real.read_text(encoding="utf-8")
        again = json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
        self.assertEqual(again, raw)


if __name__ == "__main__":
    unittest.main()
