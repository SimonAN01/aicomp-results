import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/aicomp-results/scripts"))
import aicomp
import client
import submit_result as submission


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "result.zip"
        with zipfile.ZipFile(self.file, "w") as archive:
            archive.writestr("test.txt", "synthetic test data")
        self.digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.row = {
            "id": "registration-1", "CJRZH_": "owner-1", "CSBH_": "entry-1",
            "CSZPMC_": "Original", "ZPDAWD_": submission.PREFIX + "old.zip",
            "ZPTJQK_": "已提交", "version": 1, "SCZPKSSJ_": "2000-01-01",
            "SCZPJZSJ_": "2099-12-31", "JFZT_": "已缴费",
            "TJKG_ZPDAWD_": "开启", "TJKG_CSZPMC_": "开启",
            "lastModifiedTime": "2026-09-19 19:49:47",
        }
        self.identity = {"code": "owner-1", "groupIdList": []}

    def test_identical_submission_does_not_write(self):
        api = Mock()
        with patch.object(submission, "remote_digest", return_value=self.digest), \
                patch.object(submission, "upload") as upload, \
                patch.object(submission, "save_json", return_value="local-receipt.json"):
            report = submission.submit(api, self.identity, self.row, self.file, "Original")
        self.assertEqual(report["outcome"], "already_submitted_identical_file")
        api.request.assert_not_called()
        upload.assert_not_called()

    def test_title_validation_before_request(self):
        api = Mock()
        for title in ["", "x" * 21, "😀" * 11, "a\nb"]:
            with self.subTest(title=title), self.assertRaises(ValueError):
                submission.submit(api, self.identity, self.row, self.file, title)
        api.request.assert_not_called()

    def test_submission_updates_title_and_zip_and_checks_receipt(self):
        api = Mock(clock_offset=0)
        saved = dict(self.row)
        writes = []

        def request(path, **kwargs):
            if path == "/createdTableMeta/findOne":
                return {"isProcessExist": False, "dbStructureDefinitionList": [
                    {"fieldName": key, "fieldType": "VARCHAR"} for key in
                    ["CSZPMC_", "ZPDAWD_", "ZPTJQK_", "CSBH_", "CJRZH_"]
                ]}
            if path == "/createdMenu/findOne":
                return {"actionConfig": {"pageFunctionConfigList": [{
                    "id": "rowModify", "afterScriptId": "CCUTONLINE_JSGLPT_syncJsbmbToZpdfb",
                }]}}
            if path == "/common/upInsert":
                writes.append(kwargs["model"]["data"])
                saved.update(kwargs["model"]["data"], version=2)
                return {"id": saved["id"]}
            raise AssertionError(path)

        api.request.side_effect = request
        with patch.object(submission, "remote_digest", return_value=self.digest), \
                patch.object(submission, "upload") as upload, \
                patch.object(submission, "get_record", side_effect=[self.row, saved]), \
                patch.object(submission, "save_json", return_value="local-receipt.json"):
            report = submission.submit(api, self.identity, self.row, self.file, "New title")
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["CSZPMC_"], "New title")
        self.assertNotEqual(writes[0]["ZPDAWD_"], self.row["ZPDAWD_"])
        self.assertEqual(writes[0]["CSBH_"], self.row["CSBH_"])
        self.assertEqual(report["server_file"], writes[0]["ZPDAWD_"])
        self.assertEqual(report["outcome"], "business_record_saved")
        upload.assert_called_once()

    def test_receipt_still_targets_old_zip_after_new_submission(self):
        path = Path(self.directory.name) / "receipt.json"
        receipt = {
            "receipt_version": 1, "owner": "owner-1", "record_id": self.row["id"],
            "entry": self.row["CSBH_"], "server_file": self.row["ZPDAWD_"],
        }
        path.write_text(json.dumps(receipt), encoding="utf-8")
        current = dict(self.row, ZPDAWD_=submission.PREFIX + "new.zip")
        with patch.object(aicomp, "resolve_record", return_value=current):
            loaded, source = aicomp.receipt_source(Mock(), "owner-1", path)
        self.assertEqual(source["ZPDAWD_"], receipt["server_file"])
        with self.assertRaises(ValueError):
            aicomp.receipt_source(Mock(), "different-owner", path)

    def test_multiple_registrations_require_selection(self):
        api = Mock()
        api.request.return_value = {"content": [
            self.row, dict(self.row, id="registration-2"),
        ], "last": True}
        with self.assertRaisesRegex(ValueError, "Choose --record-id"):
            client.resolve_record(api, "owner-1")
        model = api.request.call_args.kwargs["model"]
        self.assertEqual(model["whereGroup"]["whereElementList"][0][0]["value"], "owner-1")

    def test_missing_auth_never_searches_or_loads_a_default(self):
        with patch.dict(client.os.environ, {}, clear=True), \
                patch.object(client.sys.stdin, "isatty", return_value=False), \
                patch.object(client, "Client") as api:
            with self.assertRaisesRegex(ValueError, "Provide AICOMP_AUTH"):
                client.authenticate()
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
