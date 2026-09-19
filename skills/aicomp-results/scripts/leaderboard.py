"""Read all public scores from an AIC leaderboard detail URL."""

import argparse
import csv
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

API = "https://jluat-smart-app-api.yuntu.cn/third/jsphb"
DEFAULT_FIELDS = [
    "XH_", "CSBH_", "TDMC_", "FS_", "ZPZHTJSJ_", "DFSJ_",
    "DQJD_", "STMC_", "SDSTBH_", "JSMC_",
]


def parse_detail_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "reg.aicomp.cn":
        raise ValueError("Use a reg.aicomp.cn leaderboard detail URL.")
    if parsed.path != "/special/phb/detail":
        raise ValueError("The URL must be /special/phb/detail.")
    query = parse_qs(parsed.query)
    required = ("id", "rwId", "stbh")
    missing = [name for name in required if not query.get(name, [""])[0]]
    if missing:
        raise ValueError("Leaderboard URL is missing: " + ", ".join(missing))
    return {name: query[name][0] for name in required}


def _post(payload, timeout=45):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    request = Request(API, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not result.get("success") or result.get("code") != 0:
        raise RuntimeError(result.get("msg") or "Leaderboard request failed.")
    return result


def get_stages(board_id, stbh):
    data = _post({"type": "JSJD", "bdId": board_id, "stbh": stbh}).get("data") or {}
    names = [name for name in str(data.get("JDMC_") or "").split(",") if name]
    publication = next(iter(data.get("jsbdList") or []), {})
    return {
        "board_id": board_id, "stbh": stbh, "task_id": data.get("RWID_"),
        "problem": data.get("STMC_"), "competition": data.get("JSMC_"),
        "update_mode": publication.get("GXFS_", data.get("GXFS_")),
        "published_at": publication.get("ZXFBSJ_"),
        "stages": names,
    }


def fetch_scores(task_id, stbh, stage, *, page_size=1000):
    if not task_id or not stbh or not stage:
        raise ValueError("task ID, stbh and stage are required.")
    page = 0
    rows = []
    total = None
    seen = set()
    while True:
        result = _post({
            "pageNo": page, "pageSize": page_size, "type": "JSDF",
            "rwId": task_id, "stbh": stbh, "jd": stage,
        })
        batch = result.get("data") or []
        if not isinstance(batch, list):
            raise RuntimeError("Unexpected leaderboard data.")
        current_total = result.get("total")
        if not isinstance(current_total, int) or isinstance(current_total, bool) or current_total < 0:
            raise RuntimeError("Missing valid leaderboard total; completeness cannot be verified.")
        if total is not None and current_total != total:
            raise RuntimeError("Leaderboard changed during retrieval; retry the read.")
        total = current_total
        for row in batch:
            if not isinstance(row, dict):
                raise RuntimeError("Unexpected leaderboard row.")
            entry = row.get("CSBH_")
            if not entry or entry in seen:
                raise RuntimeError("Missing or repeated entry; refusing to report a complete leaderboard.")
            if row.get("SDSTBH_") != stbh or row.get("DQJD_") != stage:
                raise RuntimeError("Leaderboard returned a different problem or stage.")
            seen.add(entry)
            rows.append(row)
        if len(rows) == total:
            break
        if not batch or len(rows) > total:
            raise RuntimeError("Leaderboard row count does not match the reported total.")
        page += 1
        if page >= 100:
            raise RuntimeError("Too many leaderboard pages.")
    return rows, total if isinstance(total, int) else len(rows)


def normalize(rows):
    return [{field: row.get(field) for field in DEFAULT_FIELDS} for row in rows]


def write_output(rows, destination=None, fmt="json"):
    if destination:
        path = Path(destination).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "csv":
            with path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=DEFAULT_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
        else:
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="The full /special/phb/detail URL.")
    source.add_argument("--board-id", help="Leaderboard detail ID.")
    parser.add_argument("--rw-id", help="Task ID when --board-id is used.")
    parser.add_argument("--stbh", help="Problem/track ID when --board-id is used.")
    parser.add_argument("--stage", help="Stage name, e.g. 初赛. Defaults to the first stage.")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--output", help="Write all rows to this local file.")
    args = parser.parse_args(argv)
    if args.url:
        values = parse_detail_url(args.url)
    elif args.rw_id and args.stbh:
        values = {"id": args.board_id, "rwId": args.rw_id, "stbh": args.stbh}
    else:
        parser.error("--board-id requires --rw-id and --stbh.")
    info = get_stages(values["id"], values["stbh"])
    stage = args.stage or (info["stages"][0] if info["stages"] else None)
    if not stage:
        raise ValueError("No stage was published for this leaderboard.")
    if stage not in info["stages"]:
        raise ValueError("Choose a published stage: " + ", ".join(info["stages"]))
    if info["task_id"] and info["task_id"] != values["rwId"]:
        raise ValueError("Task ID does not match the selected leaderboard.")
    rows, total = fetch_scores(values["rwId"], values["stbh"], stage)
    output = normalize(rows)
    write_output(output, args.output, args.format)
    result = {
        "outcome": "leaderboard_loaded", "board_id": values["id"],
        "rw_id": values["rwId"], "stbh": values["stbh"], "stage": stage,
        "problem": info["problem"], "competition": info["competition"],
        "update_mode": info["update_mode"], "published_at": info["published_at"],
        "total": total, "returned": len(output), "rows": output,
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
