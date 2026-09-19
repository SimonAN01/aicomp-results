"""Read the current submitted ZIP's score; optionally poll for completion."""

import datetime
import math
import re
import sys
import time
from urllib.parse import unquote, urlsplit

from client import RESULT_FIELD, compact, save_json

SCORE_MENU = "65b75207a58fdc32c79e9842"
OSS_ORIGIN = "https://trans-from-yuntu-resourse.oss-cn-beijing.aliyuncs.com/"
PREFIX = "smartSchool/appCreator/school/sjc/user/app/JSGLPT/JSBMB/zip/"
MIOU = re.compile(r"\bmIoU\s*[=:：]\s*(\d+(?:\.\d+)?)(?![\d.eE])", re.IGNORECASE)


def object_key(value):
    """Normalize the registration's key and the scoring table's full URL."""
    if not isinstance(value, str) or not value:
        raise ValueError("No result ZIP path.")
    if value.startswith(("https://", "http://")):
        parsed = urlsplit(value)
        if parsed.hostname != urlsplit(OSS_ORIGIN).hostname:
            raise ValueError("Unexpected result file host.")
        value = unquote(parsed.path.lstrip("/"))
    if not value.startswith(PREFIX) or ".." in value.split("/"):
        raise ValueError("Unexpected result ZIP path.")
    return value


def timestamp(value):
    if not value:
        raise ValueError("Missing submission timestamp.")
    parsed = datetime.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    return parsed.timestamp()


def validate_poll_options(timeout, interval):
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Timeout must be a finite number >= 0.")
    if not math.isfinite(interval) or not 1 <= interval <= 60:
        raise ValueError("Interval must be between 1 and 60 seconds.")


def find_score(client, source, owner, *, after=None, score_id=None):
    """Match owner, competition entry and exact file; never use another ZIP's score."""
    key = object_key(source.get(RESULT_FIELD))
    entry = source.get("CSBH_")
    if not entry:
        raise ValueError("The registration has no competition entry number.")
    cutoff = timestamp(after) if after else None
    filters = [
        {"fieldName": name, "whereOp": "is", "value": value, "location": "ZPDFB"}
        for name, value in [
            ("TJRZH_", owner), ("CSBH_", entry), (RESULT_FIELD, OSS_ORIGIN + key),
        ]
    ]
    if score_id:
        filters.append({"fieldName": "id", "whereOp": "is", "value": score_id, "location": "ZPDFB"})
    candidates = {}
    page = 0
    while True:
        result = client.request(
            "/common/findByQuery",
            model={
                "pageNo": page, "pageSize": 100, "queryType": "All",
                "whereGroup": {"whereElementList": [filters]},
            },
            headers={"metaId": "ZPDFB", "menuId": SCORE_MENU},
        )
        rows = result.get("content")
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected score query response.")
        for row in rows:
            if row.get("TJRZH_") != owner or row.get("CSBH_") != entry:
                raise RuntimeError("Score query returned a different account or entry.")
            if object_key(row.get(RESULT_FIELD)) != key:
                raise RuntimeError("Score query returned a different ZIP.")
            if score_id and row.get("id") != score_id:
                raise RuntimeError("Score query returned a different grading attempt.")
            submitted = row.get("ZPZHTJSJ_") or row.get("createTime")
            if cutoff is None or timestamp(submitted) >= cutoff:
                candidates[row["id"]] = row
        if result.get("last") is True or len(rows) < 100:
            break
        page += 1
        if page >= 100:
            raise RuntimeError("Too many score pages; narrow the query before retrying.")
    if not candidates:
        return None
    return max(candidates.values(), key=lambda row: (
        timestamp(row.get("ZPZHTJSJ_") or row.get("createTime")),
        timestamp(row.get("lastModifiedTime") or row.get("createTime")),
        row["id"],
    ))


def score_report(source, row):
    report = {
        "record_id": source["id"], "team": source.get("TDMC_"),
        "problem": source.get("STMC_"), "server_file": object_key(source.get(RESULT_FIELD)),
        "outcome": "awaiting_score_record", "status": None, "miou": None,
        "miou_text": None, "message": None, "failure_reason": None,
    }
    if row is None:
        return report
    status = str(row.get("DQZT_") or "")
    message = str(row.get("BZ_") or "")
    failure = str(row.get("SBYY_") or "")
    report.update(
        score_record_id=row["id"], status=status, message=message,
        failure_reason=failure or None, submitted_at=row.get("ZPZHTJSJ_"),
        scored_at=row.get("DFSJ_"), outcome="pending",
    )
    if failure or status.upper() in {"FAILED", "FAIL", "ERROR"} or "打分失败" in message:
        report["outcome"] = "score_failed"
    elif status.upper() == "DONE":
        report["outcome"] = "score_completed"
        match = MIOU.search(message)
        if match:
            number = float(match[1])
            if 0 <= number <= 1:
                report.update(miou=number, miou_text=match[1])
    return report


def wait_for_score(client, source, owner, *, timeout=0, interval=15, after=None, score_id=None):
    validate_poll_options(timeout, interval)
    started = time.monotonic()
    attempts = 0
    while True:
        row = find_score(client, source, owner, after=after, score_id=score_id)
        report = score_report(source, row)
        attempts += 1
        elapsed = time.monotonic() - started
        report.update(attempts=attempts, elapsed_seconds=round(elapsed, 2))
        terminal = report["outcome"] in {"score_completed", "score_failed"}
        expired = elapsed >= timeout
        if not terminal and timeout > 0 and expired:
            report["outcome"] = "timed_out"
        save_json("last_score.json", report)
        if terminal or expired:
            return report
        print(compact({"score_poll": attempts, "outcome": report["outcome"],
                       "status": report["status"], "elapsed_seconds": report["elapsed_seconds"]}),
              file=sys.stderr, flush=True)
        time.sleep(min(interval, timeout - elapsed))


def score_exit_code(report):
    if report["outcome"] == "score_completed":
        return 0
    return 2 if report["outcome"] == "score_failed" else 3
