"""A small stand-in for the Converter Studio API, served through ``httpx.MockTransport``."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE = "https://api.test/api"
KEY = "cvs_live_test_key_0123456789"


@dataclass
class Job:
    id: str
    to: str
    name: str
    size: int
    statuses: deque[str]
    credits: int
    max_credits: int | None
    output: bytes
    options: dict[str, Any]
    error: dict[str, Any] | None = None

    def view(self) -> dict[str, Any]:
        status = self.statuses[0]
        done = status == "done"
        stem = self.name.rsplit(".", 1)[0]
        return {
            "id": self.id,
            "status": status,
            "from": self.name.rsplit(".", 1)[-1].lower(),
            "to": self.to,
            "inputName": self.name,
            "inputSize": self.size,
            "credits": self.credits,
            "maxCredits": self.max_credits,
            "progress": 1 if done else None,
            "outputName": f"{stem}.{self.to}",
            "outputSize": len(self.output) if done else None,
            "downloadUrl": f"{BASE}/jobs/{self.id}/download?token=tok_{self.id}" if done else None,
            "expiresAt": "2026-11-23T07:00:00.000Z",
            "error": self.error if status == "failed" else None,
            "next": "Done." if done else "Check again.",
        }


@dataclass
class FakeAPI:
    """Answers like the API. ``outputs`` holds each target format's result bytes; a file whose
    name holds ``broken`` fails like a damaged file does."""

    statuses: list[str] = field(default_factory=lambda: ["done"])
    outputs: dict[str, bytes] = field(default_factory=dict)
    credits: int = 1
    account_credits: int = 1099
    requests: list[httpx.Request] = field(default_factory=list)
    uploads: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, Job] = field(default_factory=dict)
    queue: dict[str, deque[httpx.Response | Exception]] = field(default_factory=dict)
    idempotency: dict[str, tuple[str, str]] = field(default_factory=dict)
    counter: int = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def push(self, path: str, *answers: httpx.Response | Exception) -> None:
        self.queue.setdefault(path, deque()).extend(answers)

    def of(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]

    def created(self) -> list[dict[str, Any]]:
        """The bodies of the conversions created."""
        return [json.loads(r.content) for r in self.of("POST", "/api/v1/conversions")]

    def _next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter:08d}"

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        self.requests.append(request)
        queued = self.queue.get(request.url.path)
        if queued:
            answer = queued.popleft()
            if isinstance(answer, Exception):
                raise answer
            return answer
        return self._route(request, body)

    def _route(self, request: httpx.Request, body: bytes) -> httpx.Response:
        path = request.url.path.removeprefix("/api")
        method = request.method
        if not path.startswith(("/v1/uploads/", "/jobs/")) and not self._authorized(request):
            return error(401, "invalidApiKey", "This API key does not work.")
        if method == "GET" and path == "/v1/account":
            return _json(
                200,
                {
                    "email": "dev@example.com",
                    "plan": "pro",
                    "allApps": True,
                    "credits": self.account_credits,
                    "allowance": {"used": 1, "limit": 1100, "per": "month"},
                    "packs": 0,
                    "renewsAt": "2026-12-22T01:16:48.716Z",
                    "maxFileBytes": 1073741824,
                    "maxMediaSeconds": 7200,
                    "wallet": None,
                },
            )
        if method == "POST" and path == "/v1/uploads":
            data = json.loads(body)
            upload_id = self._next_id("up")
            self.uploads[upload_id] = {"name": data["fileName"], "data": b""}
            return _json(
                201,
                {
                    "id": upload_id,
                    "uploadUrl": f"{BASE}/v1/uploads/{upload_id}?token=tok_{upload_id}",
                    "method": "PUT",
                    "maxBytes": 1073741824,
                    "partBytes": 95 * 1024 * 1024,
                    "expiresAt": "2026-11-23T02:00:00.000Z",
                },
            )
        if method == "PUT" and path.startswith("/v1/uploads/"):
            upload = self.uploads.get(path.rsplit("/", 1)[-1])
            if upload is None:
                return error(404, "notFound", "We couldn't find that conversion.")
            upload["data"] = body
            return _json(200, {"status": "ready"})
        if method == "POST" and path == "/v1/conversions":
            return self._create(request, json.loads(body))
        if path.startswith("/v1/conversions/"):
            parts = path.split("/")
            job = self.jobs.get(parts[3])
            if job is None:
                return error(404, "notFound", "We couldn't find that conversion.")
            if method == "POST" and parts[-1] == "confirm":
                job.statuses = deque(["done"])
                return _json(200, job.view())
            view = job.view()
            if len(job.statuses) > 1:
                job.statuses.popleft()
            return _json(200, view)
        if method == "GET" and path.startswith("/jobs/"):
            job = self.jobs.get(path.split("/")[2])
            if job is None or request.url.params.get("token") != f"tok_{job.id}":
                return _json(404, {"error": "notFound"})
            return httpx.Response(200, content=job.output)
        return _json(404, {"error": "notFound"})

    def _authorized(self, request: httpx.Request) -> bool:
        return bool(request.headers.get("authorization") == f"Bearer {KEY}")

    def _create(self, request: httpx.Request, data: dict[str, Any]) -> httpx.Response:
        key = request.headers.get("idempotency-key")
        fingerprint = json.dumps(data, sort_keys=True)
        if key is not None and key in self.idempotency:
            job_id, seen = self.idempotency[key]
            if seen != fingerprint:
                return error(409, "idempotencyKeyReused", "This Idempotency-Key was already used.")
            return _json(200, self.jobs[job_id].view(), {"Idempotent-Replayed": "true"})
        upload = self.uploads.pop(data["uploadId"], None)
        if upload is None:
            return error(404, "notFound", "We couldn't find that conversion.")
        to = data["to"]
        max_credits = data.get("maxCredits", 20)
        statuses = deque(["quoted"] if self.credits > max_credits else self.statuses)
        failure = None
        if "broken" in upload["name"]:
            statuses = deque(["failed"])
            failure = {
                "code": "conversionFailed",
                "message": "This file could not be converted. The credits were given back.",
            }
        job = Job(
            id=data["uploadId"],
            to=to,
            name=upload["name"],
            size=len(upload["data"]),
            statuses=statuses,
            credits=self.credits,
            max_credits=max_credits,
            output=self.outputs.get(to, f"RESULT {to}".encode()),
            options=data.get("options", {}),
            error=failure,
        )
        self.jobs[job.id] = job
        if key is not None:
            self.idempotency[key] = (job.id, fingerprint)
        view = job.view()
        view["status"] = "queued" if view["status"] == "done" else view["status"]
        return _json(201, view)


def _json(status: int, body: object, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def error(status: int, code: str, message: str, **params: object) -> httpx.Response:
    body: dict[str, Any] = {"code": code, "message": message}
    if params:
        body["params"] = params
    return _json(status, {"error": body})
