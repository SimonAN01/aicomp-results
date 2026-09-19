from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/aicomp-results/scripts"))
import leaderboard


class Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode()
    def __enter__(self):
        return BytesIO(self.data)
    def __exit__(self, *args):
        return False


class LeaderboardTests(unittest.TestCase):
    def test_parse_url(self):
        values = leaderboard.parse_detail_url(
            "https://reg.aicomp.cn/special/phb/detail?id=board&rwId=task&stbh=problem"
        )
        self.assertEqual(values, {"id": "board", "rwId": "task", "stbh": "problem"})

    def test_public_requests_and_all_rows(self):
        calls = []
        responses = [
            {"success": True, "code": 0, "data": {
                "STMC_": "Problem", "JSMC_": "Contest", "JDMC_": "初赛,复赛",
                "RWID_": "task", "GXFS_": "实时榜单",
            }},
            {"success": True, "code": 0, "total": 2, "data": [
                {"XH_": 1, "FS_": "88.1", "TDMC_": "A", "CSBH_": "entry-a", "SDSTBH_": "problem", "DQJD_": "初赛"},
                {"XH_": 2, "FS_": "77.2", "TDMC_": "B", "CSBH_": "entry-b", "SDSTBH_": "problem", "DQJD_": "初赛"},
            ]},
        ]
        def fake(request, timeout=45):
            calls.append(json.loads(request.data))
            return Response(responses.pop(0))
        with patch.object(leaderboard, "urlopen", fake):
            info = leaderboard.get_stages("board", "problem")
            rows, total = leaderboard.fetch_scores("task", "problem", "初赛")
        self.assertEqual(info["stages"], ["初赛", "复赛"])
        self.assertEqual((len(rows), total), (2, 2))
        self.assertEqual(calls[1]["type"], "JSDF")
        self.assertNotIn("auth", calls[1])

    def test_partial_response_is_not_reported_complete(self):
        with patch.object(leaderboard, "_post", return_value={"total": 2, "data": []}):
            with self.assertRaisesRegex(RuntimeError, "row count"):
                leaderboard.fetch_scores("task", "problem", "初赛")

    def test_cli_dispatch_does_not_authenticate(self):
        import aicomp
        with patch.object(aicomp, "leaderboard_main", return_value=0) as run, \
                patch.object(aicomp, "authenticate") as auth:
            self.assertEqual(aicomp.main(["leaderboard", "--help"]), 0)
        run.assert_called_once_with(["--help"])
        auth.assert_not_called()
