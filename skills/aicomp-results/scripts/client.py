"""HTTP client matching the competition site's frontend request format."""

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import getpass
import sys
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE = "https://jluat-smart-app-api.yuntu.cn"
AES_KEY = b"627638be2ca61a24bda4e463"
RC4_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCC22NoHUKe+YPJsyr3yDqiV0YNbw08TK4"
    "YRj8jMq9TISkB+R23FNb7JDfOWBGSrBd72Z4XWvM2YrEHv5pum1HtY568iS51i5aGKGkgI"
    "ix3YVRN2wAx5AgaWoOmXoCuuxYFH6ckcGARto9j4btSj/BTstd41lv7r6vVQ5gu3L6o6QIDAQAB"
).encode()
UPLOAD_MENU = "639980063d903c241eb85102"
FORM_MENU = "JSGL_ACTION_FORM_JSBMB_JTZP_WRITE"
RESULT_FIELD = "ZPDAWD_"


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def encrypt(value):
    padder = padding.PKCS7(128).padder()
    raw = padder.update(compact(value).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(AES_KEY), modes.ECB()).encryptor()
    return base64.b64encode(encryptor.update(raw) + encryptor.finalize()).decode()


def decrypt_response(value):
    if not isinstance(value, str):
        return value
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + RC4_KEY[i % len(RC4_KEY)]) % 256
        state[i], state[j] = state[j], state[i]
    i = j = 0
    result = bytearray()
    for byte in base64.b64decode(value):
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        result.append(byte ^ state[(state[i] + state[j]) % 256])
    return json.loads(result.decode())


class Client:
    def __init__(self, auth=None):
        self.auth = auth or os.environ["AICOMP_AUTH"]
        self.clock_offset = 0

    def request(self, path, *, model=None, body_name="model", headers=None, params=None):
        query = dict(params or {})
        signing_query = dict(query)
        request_headers = {
            "auth": self.auth,
            "appid": "JSGLPT",
            "roleid": "XueSheng",
            "Origin": "https://reg.aicomp.cn",
            "Referer": f"https://reg.aicomp.cn/app/JSGLPT/{UPLOAD_MENU}",
        }
        request_headers.update(headers or {})
        data = None
        if model is not None:
            envelope = dict(query)
            envelope["body"] = {body_name: model}
            encrypted = encrypt(envelope)
            data = compact({"s": encrypted}).encode()
            signing_query["s"] = encrypted
            request_headers["Content-Type"] = "application/json"
        nonce = str(uuid.uuid4())
        timestamp = str(int(time.time() * 1000 + self.clock_offset))
        prefix = "".join(f"{key}{signing_query[key]}" for key in sorted(signing_query))
        digest = hashlib.md5(f"{prefix}_{timestamp}_{nonce}".encode()).hexdigest()
        request_headers.update(ytn=nonce, ytt=timestamp, yts=digest)
        url = BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, data=data, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                server_time = response.headers.get("X-Server-Time")
                if server_time:
                    self.clock_offset = int(server_time) - time.time() * 1000
                return decrypt_response(json.load(response))
        except urllib.error.HTTPError as error:
            # Never include request headers or credentials in errors.
            if error.code in {401, 403}:
                raise RuntimeError(
                    f"{path}: HTTP {error.code}. Ask the user for a fresh auth token "
                    "from the correct account; do not retry automatically."
                ) from None
            raise RuntimeError(
                f"{path}: HTTP {error.code}. Request failed; no automatic retry."
            ) from None


def state_directory():
    configured = os.environ.get("AICOMP_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "state"))
    return base / "aicomp-results"


def save_json(name, value):
    if Path(name).name != name:
        raise ValueError("State filename must not contain directories.")
    destination = state_directory() / name
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, destination)
    return str(destination)


def authenticate(auth_stdin=False):
    if auth_stdin:
        token = sys.stdin.readline().strip()
    else:
        token = os.environ.get("AICOMP_AUTH", "").strip()
        if not token:
            if not sys.stdin.isatty():
                raise ValueError("Provide AICOMP_AUTH for this process or use --auth-stdin.")
            token = getpass.getpass("Paste the user's auth token (hidden): ").strip()
    if not token or not token.isascii() or any(char.isspace() for char in token):
        raise ValueError("A nonempty auth header value without whitespace is required.")
    client = Client(token)
    identity = client.request("/createdUser/refreshOne")
    if not isinstance(identity, dict) or not identity.get("code"):
        raise ValueError("Could not identify the account. Ask the user for a fresh auth token.")
    return client, identity


def resolve_record(client, owner, record_id=None):
    if record_id:
        return get_record(client, record_id, owner)
    result = client.request(
        "/common/findByQuery",
        model={
            "pageNo": 0, "pageSize": 100, "queryType": "All",
            "whereGroup": {"whereElementList": [[
                {"fieldName": "CJRZH_", "whereOp": "is", "value": owner, "location": "JSBMB"},
            ]]},
        },
        headers={"metaId": "JSBMB", "menuId": UPLOAD_MENU},
    )
    records = {row["id"]: row for row in result.get("content", [])}
    if any(row.get("CJRZH_") != owner for row in records.values()):
        raise ValueError("Owner mismatch.")
    if len(records) == 1 and result.get("last", True):
        return next(iter(records.values()))
    choices = [{"record_id": row["id"], "team": row.get("TDMC_"),
                "problem": row.get("STMC_")} for row in records.values()]
    raise ValueError("Choose --record-id for the intended entry: " + compact(choices))


def get_record(client, record_id, owner):
    """Read exactly one registration owned by the authenticated account."""
    result = client.request(
        "/common/findByQuery",
        model={
            "pageNo": 0, "pageSize": 10, "queryType": "All",
            "whereGroup": {"whereElementList": [[
                {"fieldName": "id", "whereOp": "is", "value": record_id, "location": "JSBMB"},
                {"fieldName": "CJRZH_", "whereOp": "is", "value": owner, "location": "JSBMB"},
            ]]},
        },
        headers={"metaId": "JSBMB", "menuId": UPLOAD_MENU},
    )
    records = {row["id"]: row for row in result.get("content", [])}
    if set(records) != {record_id}:
        raise ValueError("The requested record was not found under the authenticated owner.")
    row = records[record_id]
    if row.get("CJRZH_") != owner:
        raise ValueError("Owner mismatch.")
    return row
