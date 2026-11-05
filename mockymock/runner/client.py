"""HTTP client of the LegacyLens runner API (standard library only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

#: Header the backend authenticates the runner with.
TOKEN_HEADER = "X-Runner-Token"
#: Path of the runner API under the backend's base URL.
API_PREFIX = "/api/v1/runner"


class RunnerClientError(Exception):
    """The backend refused a request or could not be reached."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RunnerClient:
    """Claims jobs, downloads packs and reports results."""

    def __init__(self, base_url: str, token: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, bytes]:
        if not path.startswith("/"):
            # The token goes with every request: never follow a URL the
            # backend hands back to another host.
            raise RunnerClientError(f"refusing a request outside the backend: {path}")
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header(TOKEN_HEADER, self.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            raise RunnerClientError(
                f"{method} {url}: HTTP {exc.code} {body}", status=exc.code
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise RunnerClientError(f"{method} {url}: {exc}") from exc

    def claim(self, runner_name: str) -> dict[str, Any] | None:
        """The next queued job (now running for this runner), or None."""
        status, body = self._request(
            "POST", f"{API_PREFIX}/jobs/claim", {"runner": runner_name}
        )
        if status == 204 or not body.strip():
            return None
        job = _json(body, "claim")
        if not isinstance(job, dict) or not job.get("id"):
            raise RunnerClientError(
                f"claim answered something that is not a job: {body[:200]!r}"
            )
        return job

    def download_pack(self, job: dict[str, Any]) -> bytes:
        """The zip of ``job``."""
        path = str(job.get("pack_url") or f"{API_PREFIX}/jobs/{job['id']}/pack")
        _, body = self._request("GET", path)
        return body

    def report(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Post the outcome of ``job_id``; the backend's job summary."""
        _, body = self._request("POST", f"{API_PREFIX}/jobs/{job_id}/result", payload)
        result = _json(body, "report") if body.strip() else {}
        return result if isinstance(result, dict) else {}


def _json(body: bytes, what: str) -> Any:
    """`body` as JSON. A body that is not (a proxy's HTML page answered
    with 200) is a RunnerClientError, which `serve` retries: as a bare
    ValueError it stopped the runner (2026-11-05)."""
    try:
        return json.loads(body)
    except ValueError as exc:
        raise RunnerClientError(
            f"{what} answered something that is not JSON: {body[:200]!r}"
        ) from exc
