"""Offline tests for file matching, stale scores and bounded polling."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/aicomp-results/scripts"))
import check_score as score


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "id": "registration-1", "CSBH_": "entry-1",
            "ZPDAWD_": score.PREFIX + "unique_result.zip",
        }
        self.row = {
            "id": "score-1", "TJRZH_": "owner-1", "CSBH_": "entry-1",
            "ZPDAWD_": score.OSS_ORIGIN + self.source["ZPDAWD_"],
            "ZPZHTJSJ_": "2026-09-19 19:49:47",
            "createTime": "2026-09-19 19:49:47",
            "lastModifiedTime": "2026-09-19 19:53:16",
            "DFSJ_": "2026-09-19 19:53:16", "DQZT_": "DONE",
            "BZ_": "打分成功，mIoU=0.692610", "SBYY_": "",
        }

    def test_query_filters_and_success(self):
        client = Mock()
        client.request.return_value = {"content": [self.row], "last": True}
        found = score.find_score(client, self.source, "owner-1")
        query = client.request.call_args.kwargs["model"]
        filters = query["whereGroup"]["whereElementList"][0]
        self.assertEqual(
            {f["fieldName"]: f["value"] for f in filters},
            {"TJRZH_": "owner-1", "CSBH_": "entry-1", "ZPDAWD_": self.row["ZPDAWD_"]},
        )
        report = score.score_report(self.source, found)
        self.assertEqual(report["outcome"], "score_completed")
        self.assertEqual(report["miou_text"], "0.692610")
        self.assertAlmostEqual(report["miou"], 0.692610)

    def test_wrong_file_or_owner_rejected(self):
        for field, value in [
            ("ZPDAWD_", score.OSS_ORIGIN + score.PREFIX + "old.zip"),
            ("TJRZH_", "another-owner"), ("CSBH_", "another-entry"),
        ]:
            with self.subTest(field=field):
                row = dict(self.row, **{field: value})
                client = Mock()
                client.request.return_value = {"content": [row], "last": True}
                with self.assertRaises(RuntimeError):
                    score.find_score(client, self.source, "owner-1")

    def test_stale_attempt_excluded_and_latest_pending_wins(self):
        client = Mock()
        client.request.return_value = {"content": [self.row], "last": True}
        self.assertIsNone(score.find_score(
            client, self.source, "owner-1", after="2026-09-19 19:50:00",
        ))
        later = dict(self.row, id="score-2", DQZT_="RUNNING",
                     ZPZHTJSJ_="2026-09-19 20:00:00",
                     lastModifiedTime="2026-09-19 20:00:00")
        client.request.return_value["content"].append(later)
        found = score.find_score(client, self.source, "owner-1")
        report = score.score_report(self.source, found)
        self.assertEqual(report["outcome"], "pending")
        self.assertIsNone(report["miou"])  # Old message must not become a new score.

    def test_failed_and_zero_score(self):
        failed = dict(self.row, DQZT_="FAILED", SBYY_="Invalid ZIP")
        report = score.score_report(self.source, failed)
        self.assertEqual(score.score_exit_code(report), 2)
        self.assertIsNone(report["miou"])
        zero = dict(self.row, BZ_="打分成功，mIoU=0.000000")
        self.assertEqual(score.score_report(self.source, zero)["miou"], 0.0)

    def test_numeric_score_without_remark(self):
        row = dict(self.row, BZ_=None, FS_="81.23456789012345")
        report = score.score_report(self.source, row)
        self.assertEqual(report["outcome"], "score_completed")
        self.assertEqual(report["score_text"], "81.23456789012345")
        self.assertEqual(report["score"], 81.23456789012345)
        self.assertEqual(report["score_source"], "FS_")
        self.assertIsNone(report["miou"])
        self.assertEqual(report["message"], "")

    def test_server_score_and_miou_remain_separate(self):
        report = score.score_report(self.source, dict(self.row, FS_="69.260983"))
        self.assertEqual(report["score_text"], "69.260983")
        self.assertEqual(report["miou_text"], "0.692610")

    def test_incomplete_or_failed_rows_do_not_expose_stale_numeric_score(self):
        for status, failure in [("RUNNING", ""), ("FAILED", ""), ("DONE", "Invalid ZIP")]:
            report = score.score_report(self.source, dict(self.row, DQZT_=status,
                                                        SBYY_=failure, FS_="99.9"))
            self.assertIsNone(report["score"])
            self.assertIsNone(report["score_text"])
            self.assertIsNone(report["score_source"])

    def test_numeric_score_zero_missing_and_invalid(self):
        for raw in [0, "0", "0.000000"]:
            report = score.score_report(self.source, dict(self.row, FS_=raw))
            self.assertEqual(report["score"], 0.0)
        for raw in [None, "", "--", "NaN", "Infinity", True, {}, []]:
            report = score.score_report(self.source, dict(self.row, FS_=raw))
            self.assertIsNone(report["score"])
            self.assertIsNone(report["score_text"])

    def test_poll_pending_then_done(self):
        with patch.object(score, "find_score", side_effect=[None, self.row]) as query, \
                patch.object(score, "save_json"), \
                patch.object(score.time, "monotonic", side_effect=[0, 0, 15]), \
                patch.object(score.time, "sleep") as sleep:
            report = score.wait_for_score(Mock(), self.source, "owner-1", timeout=600)
        self.assertEqual(report["outcome"], "score_completed")
        self.assertEqual(query.call_count, 2)
        sleep.assert_called_once_with(15)

    def test_poll_timeout_is_not_success(self):
        with patch.object(score, "find_score", return_value=None), \
                patch.object(score, "save_json"), \
                patch.object(score.time, "monotonic", side_effect=[0, 0, 10]), \
                patch.object(score.time, "sleep") as sleep:
            report = score.wait_for_score(Mock(), self.source, "owner-1", timeout=10)
        self.assertEqual(report["outcome"], "timed_out")
        self.assertEqual(score.score_exit_code(report), 3)
        sleep.assert_called_once_with(10)


if __name__ == "__main__":
    unittest.main()
