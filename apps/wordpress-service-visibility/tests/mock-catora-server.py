#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = "runtime-secret"
SOURCE_ID = "11111111-1111-4111-8111-111111111111"
REPORT_ID = "22222222-2222-4222-8222-222222222222"
SNAPSHOT_RE = re.compile(
    rf"^/api/v1/service-visibility/sources/{SOURCE_ID}/snapshots(?:/([0-9a-f-]+)(?:/batches/(\d+)|/complete)?)?$"
)

state: dict[str, Any] = {
    "snapshot_id": None,
    "declared_pages": 0,
    "accepted_batches": [],
    "accepted_pages": 0,
    "records": [],
    "failed_sequence_one": False,
    "verified_requests": 0,
    "completed": False,
}


def response_payload() -> dict[str, Any]:
    return {
        "source_id": SOURCE_ID,
        "snapshot_id": state["snapshot_id"],
        "status": "complete" if state["completed"] else "receiving",
        "accepted_batches": len(state["accepted_batches"]),
        "accepted_pages": state["accepted_pages"],
        "ingestion_job_id": None,
        "report_id": REPORT_ID if state["completed"] else None,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "CatoraRuntimeMock/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(format % args, flush=True)

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _verify(self, body: bytes) -> bool:
        timestamp = self.headers.get("X-Catora-Timestamp", "")
        body_hash = hashlib.sha256(body).hexdigest()
        if self.headers.get("X-Catora-Content-Sha256") != body_hash:
            return False
        idempotency_key = self.headers.get("X-Catora-Idempotency-Key", "")
        canonical = "\n".join((self.command, self.path, timestamp, body_hash, idempotency_key))
        expected = base64.urlsafe_b64encode(
            hmac.new(TOKEN.encode(), canonical.encode(), hashlib.sha256).digest()
        ).decode().rstrip("=")
        supplied = self.headers.get("X-Catora-Signature", "")
        valid = hmac.compare_digest(expected, supplied)
        if valid:
            state["verified_requests"] += 1
        return valid

    def do_GET(self) -> None:
        if self.path == "/__state":
            self._json(200, state)
            return
        if self.path.endswith("/drafts"):
            body = self._body()
            if not self._verify(body):
                self._json(401, {"detail": "invalid signature"})
                return
            self._json(200, [])
            return
        self._json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        body = self._body()
        if not self._verify(body):
            self._json(401, {"detail": "invalid signature"})
            return
        match = SNAPSHOT_RE.match(self.path)
        if match is None:
            self._json(404, {"detail": "not found"})
            return
        snapshot_id, _sequence = match.groups()
        payload = json.loads(body or b"{}")
        if snapshot_id is None:
            requested = payload["snapshot_id"]
            if state["snapshot_id"] not in (None, requested):
                self._json(409, {"detail": "another snapshot is active"})
                return
            state["snapshot_id"] = requested
            state["declared_pages"] = payload["page_count"]
            self._json(200, response_payload())
            return
        if self.path.endswith("/complete"):
            if snapshot_id != state["snapshot_id"]:
                self._json(404, {"detail": "snapshot not found"})
                return
            if payload["batch_count"] != len(state["accepted_batches"]):
                self._json(409, {"detail": "batch count mismatch"})
                return
            if payload["page_count"] != state["accepted_pages"]:
                self._json(409, {"detail": "page count mismatch"})
                return
            state["completed"] = True
            self._json(202, response_payload())
            return
        self._json(404, {"detail": "not found"})

    def do_PUT(self) -> None:
        body = self._body()
        if not self._verify(body):
            self._json(401, {"detail": "invalid signature"})
            return
        match = SNAPSHOT_RE.match(self.path)
        if match is None:
            self._json(404, {"detail": "not found"})
            return
        snapshot_id, sequence_text = match.groups()
        if snapshot_id != state["snapshot_id"] or sequence_text is None:
            self._json(404, {"detail": "snapshot not found"})
            return
        sequence = int(sequence_text)
        payload = json.loads(body)
        if sequence == 1 and not state["failed_sequence_one"]:
            state["failed_sequence_one"] = True
            self._json(503, {"detail": "intentional one-time interruption"})
            return
        if sequence < len(state["accepted_batches"]):
            self._json(200, response_payload())
            return
        if sequence != len(state["accepted_batches"]):
            self._json(409, {"detail": "out of order"})
            return
        records = payload["records"]
        state["accepted_batches"].append(sequence)
        state["accepted_pages"] += len(records)
        state["records"].extend(records)
        self._json(200, response_payload())


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8787), Handler).serve_forever()
