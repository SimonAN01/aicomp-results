"""Two request-only commands: submit a ZIP and query its score."""

import argparse
import json
from pathlib import Path
import sys

from client import authenticate, compact, resolve_record, save_json
from check_score import object_key, score_exit_code, timestamp, validate_poll_options, wait_for_score
from submit_result import submit, validate_title
from leaderboard import main as leaderboard_main


def receipt_source(client, owner, path):
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    if receipt.get("receipt_version") != 1 or receipt.get("owner") != owner:
        raise ValueError("Receipt belongs to a different account or has an unsupported format.")
    source = resolve_record(client, owner, receipt["record_id"])
    if source.get("CSBH_") != receipt.get("entry"):
        raise ValueError("Receipt competition entry no longer matches the registration.")
    # Keep the receipt's ZIP even when a newer file has since been submitted.
    source = dict(source, ZPDAWD_=object_key(receipt["server_file"]))
    if receipt.get("submitted_after"):
        timestamp(receipt["submitted_after"])
    return receipt, source


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "leaderboard":
        return leaderboard_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    send = commands.add_parser("submit", help="Submit work title and ZIP; writes a local receipt.")
    send.add_argument("--title", required=True, help="Work title, 1-20 characters.")
    send.add_argument("--file", required=True, help="Path to the result ZIP.")
    send.add_argument("--record-id", help="Required only when the account has multiple entries.")
    query = commands.add_parser("score", help="Read the current submission or a saved receipt.")
    target = query.add_mutually_exclusive_group()
    target.add_argument("--receipt", help="Receipt path returned by submit (recommended).")
    target.add_argument("--record-id", help="Read the entry's current submitted file.")
    query.add_argument("--wait", action="store_true", help="Poll for completion.")
    query.add_argument("--timeout", type=float, default=600, help="Polling time budget in seconds.")
    query.add_argument("--interval", type=float, default=15, help="Polling interval, 1-60 seconds.")
    for command in (send, query):
        command.add_argument("--auth-stdin", action="store_true", help="Read the user-supplied auth token from stdin.")
    args = parser.parse_args(argv)
    if args.command == "submit":
        args.title = validate_title(args.title)
        if not Path(args.file).is_file() or Path(args.file).suffix.lower() != ".zip":
            raise ValueError("Provide an existing ZIP file.")
    else:
        validate_poll_options(args.timeout, args.interval)
    client, identity = authenticate(args.auth_stdin)
    owner = identity["code"]
    if args.command == "submit":
        source = resolve_record(client, owner, args.record_id)
        report = submit(client, identity, source, args.file, args.title)
        print(compact(report))
        return 0
    receipt = None
    if args.receipt:
        receipt, source = receipt_source(client, owner, args.receipt)
    else:
        source = resolve_record(client, owner, args.record_id)
    report = wait_for_score(
        client, source, owner, timeout=args.timeout if args.wait else 0, interval=args.interval,
        after=receipt.get("submitted_after") if receipt else None,
        score_id=receipt.get("score_record_id") if receipt else None,
    )
    if receipt and report.get("score_record_id"):
        # Append the exact grading id to a new receipt in the private state directory.
        # Never overwrite an arbitrary caller-supplied file.
        import uuid
        pinned = dict(receipt, score_record_id=report["score_record_id"])
        report["receipt"] = save_json(f"receipt_{uuid.uuid4().hex}.json", pinned)
    print(compact(report))
    return score_exit_code(report)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted. No automatic retry.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(compact({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
