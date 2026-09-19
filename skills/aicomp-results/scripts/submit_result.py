"""Check, or explicitly submit, one result ZIP through HTTP requests."""

import datetime
import hashlib
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

from client import FORM_MENU, RESULT_FIELD, get_record, save_json

OSS_BUCKET = "trans-from-yuntu-resourse"
OSS_ENDPOINT = "https://oss-cn-beijing.aliyuncs.com"
OSS_ORIGIN = f"https://{OSS_BUCKET}.oss-cn-beijing.aliyuncs.com/"
PREFIX = "smartSchool/appCreator/school/sjc/user/app/JSGLPT/JSBMB/zip/"
STORED_TYPES = {
    "VARCHAR", "TEXT", "INTEGER", "BIGINT", "DECIMAL", "URL", "DATE",
    "TIME", "DATETIME", "YEAR", "YEARMONTH", "PHONE", "EMAIL", "RADIO",
    "CHECKBOX", "BOOLEAN", "DICTIONARY", "FILE", "OFFICE_STAMP",
    "RICHTEXT", "RICHTEXTV2", "SIGNATURE", "DATA_API",
}
SYSTEM_FIELDS = {
    "id", "masterBusinessDataId", "masterCreatedTableMetaId", "slaveInfo",
    "serialCode", "createTime", "lastModifiedTime", "extend", "status",
    "storeStatus", "belong", "currentActivityStatus", "currentActivityName",
    "createdProcessId", "createdProcessInstanceId", "version", "operateInfo",
    "cloneDataId", "logicDeleteFlag", "creatorId", "creatorCode",
    "currentActivityInfo", "nextActivityIdList",
}


def sha256_stream(stream):
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def remote_digest(key):
    if not key.startswith(PREFIX) or ".." in key.split("/"):
        raise ValueError("Unexpected result object path; refusing to follow it.")
    url = OSS_ORIGIN + urllib.parse.quote(key, safe="/")
    with urllib.request.urlopen(url, timeout=60) as response:
        return sha256_stream(response)


def preflight(row, client):
    today = datetime.datetime.fromtimestamp(
        (time.time() * 1000 + client.clock_offset) / 1000,
        datetime.timezone(datetime.timedelta(hours=8)),
    ).date().isoformat()
    start, end = row.get("SCZPKSSJ_"), row.get("SCZPJZSJ_")
    if not start or not end or not (start[:10] <= today <= end[:10]):
        raise ValueError("Outside the record's submission period.")
    if row.get("JFZT_") not in {"已缴费", "无需缴费"}:
        raise ValueError("The record does not meet the frontend payment condition.")
    if row.get("TJKG_ZPDAWD_") != "开启":
        raise ValueError("The result ZIP field is not enabled for this record.")


def upload(client, file, key, expected_hash):
    try:
        import oss2
    except ImportError:
        raise RuntimeError("Upload requires: python -m pip install oss2") from None
    credentials = client.request(
        "/fileInfo/generateFileT", model={"url": key, "time": int(time.time() * 1000)},
    )
    auth = oss2.StsAuth(
        credentials["accessKeyId"], credentials["accessKeySecret"],
        credentials["securityToken"],
    )
    bucket = oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)
    response = bucket.put_object_from_file(
        key, str(file), headers={"x-oss-forbid-overwrite": "true"},
    )
    if response.status != 200:
        raise RuntimeError("OSS did not confirm upload success.")
    if remote_digest(key) != expected_hash:
        raise RuntimeError("Uploaded object hash mismatch; business record was not changed.")


def validate_title(title):
    title = title.strip()
    if not title or len(title.encode("utf-16-le")) // 2 > 20:
        raise ValueError("Work title must contain 1-20 characters (frontend UTF-16 length).")
    if any(ord(char) < 32 for char in title):
        raise ValueError("Work title must be a single line.")
    return title


def submit(client, identity, row, file_path, title):
    title = validate_title(title)
    file = Path(file_path).resolve(strict=True)
    if file.suffix.lower() != ".zip":
        raise ValueError("A ZIP file is required.")
    with zipfile.ZipFile(file) as archive:
        if not archive.namelist() or archive.testzip():
            raise ValueError("Empty or corrupt ZIP.")
        entry_count = len(archive.namelist())
    with file.open("rb") as stream:
        digest = sha256_stream(stream)
    owner = identity.get("code")
    if not owner or row.get("CJRZH_") != owner:
        raise ValueError("Owner mismatch; no changes made.")
    report = {
        "record_id": row["id"], "team": row.get("TDMC_"), "problem": row.get("STMC_"),
        "field": RESULT_FIELD, "file": str(file), "bytes": file.stat().st_size,
        "zip_entries": entry_count, "sha256": digest,
        "submission_status": row.get("ZPTJQK_"),
        "last_modified": row.get("lastModifiedTime"),
        "server_file": row.get(RESULT_FIELD),
        "title": title, "entry": row.get("CSBH_"), "owner": owner,
        "receipt_version": 1, "mode": "submit",
    }
    existing = row.get(RESULT_FIELD)
    submitted_after = None
    same = bool(existing and remote_digest(existing) == digest)
    report["same_as_server"] = same
    if same and row.get("ZPTJQK_") == "已提交" and row.get("CSZPMC_") == title:
        report["outcome"] = "already_submitted_identical_file"
    else:
        preflight(row, client)
        if row.get("CSZPMC_") != title and row.get("TJKG_CSZPMC_") != "开启":
            raise ValueError("Work title editing is not enabled for this record.")
        meta = client.request("/createdTableMeta/findOne", params={"id": "JSBMB"})
        form = client.request("/createdMenu/findOne", params={"id": FORM_MENU})
        if meta.get("isProcessExist"):
            raise ValueError("Workflow changed; review the frontend before submitting.")
        action = next(
            x for x in form["actionConfig"]["pageFunctionConfigList"]
            if x["id"] == "rowModify"
        )
        if action.get("afterScriptId") != "CCUTONLINE_JSGLPT_syncJsbmbToZpdfb":
            raise ValueError("Submission hook changed; review the frontend.")
        # Preserve the prior record so an operator can inspect any uncertain outcome.
        operation = uuid.uuid4().hex
        save_json(f"before_{operation}.json", row)
        # Use a new key even for a title-only change, so its grading cannot match an old job.
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", file.name)
        key = PREFIX + str(uuid.uuid4()) + "_" + safe_name
        save_json(f"operation_{operation}.json", {
            "record_id": row["id"], "old_key": existing,
            "new_key": key, "sha256": digest, "stage": "prepared",
        })
        upload(client, file, key, digest)
        latest = get_record(client, row["id"], owner)
        if latest.get("version") != row.get("version") or latest.get(RESULT_FIELD) != existing:
            raise RuntimeError("Record changed during upload; no business update was sent.")
        data = {
            field["fieldName"]: row.get(field["fieldName"])
            for field in meta["dbStructureDefinitionList"]
            if field["fieldType"] in STORED_TYPES
        }
        data.update({key: row[key] for key in SYSTEM_FIELDS if key in row})
        data[RESULT_FIELD] = key
        data["CSZPMC_"] = title
        data["ZPTJQK_"] = "已提交"
        body = {
            "id": row["id"], "userRoleId": "XueSheng",
            "userGroupIdList": identity.get("groupIdList") or [], "data": data,
        }
        save_json(f"operation_{operation}.json", {
            "record_id": row["id"], "old_key": existing,
            "new_key": key, "sha256": digest, "stage": "sending_business_update",
        })
        # A timeout here is ambiguous. Do not retry a submission automatically.
        try:
            response = client.request(
                "/common/upInsert", model=body, body_name="dataModel",
                headers={"metaId": "JSBMB", "menuId": FORM_MENU},
            )
        except Exception as error:
            receipt = {
                **report, "outcome": "submission_unconfirmed", "server_file": key,
                "submitted_after": None,
            }
            receipt_path = save_json(f"receipt_{operation}.json", receipt)
            raise RuntimeError(
                "Business update was not confirmed. Do not resubmit automatically. "
                f"Query this receipt and inspect the website first: {receipt_path}"
            ) from error
        save_json(f"response_{operation}.json", response)
        # Persist a usable receipt before readback, which can also time out.
        provisional = {**report, "outcome": "submission_unconfirmed",
                       "server_file": key, "submitted_after": None}
        provisional_path = save_json(f"receipt_{operation}.json", provisional)
        try:
            saved = get_record(client, row["id"], owner)
        except Exception as error:
            raise RuntimeError(
                f"Readback failed. Do not resubmit; check this receipt: {provisional_path}"
            ) from error
        if (saved.get(RESULT_FIELD) != key or saved.get("ZPTJQK_") != "已提交"
                or saved.get("CSZPMC_") != title):
            raise RuntimeError(f"Update was not verified. Inspect the receipt: {provisional_path}")
        report.update(outcome="business_record_saved", server_file=key,
                      submission_status=saved.get("ZPTJQK_"),
                      last_modified=saved.get("lastModifiedTime"))
        row = saved
        submitted_after = saved.get("lastModifiedTime")
    report["submitted_after"] = submitted_after
    report["receipt"] = save_json(f"receipt_{uuid.uuid4().hex}.json", report)
    save_json("last_submission.json", report)
    return report
