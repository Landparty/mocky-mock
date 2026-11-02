"""Drive the LegacyLens change-impact oracle end to end over this sample.

Uploads src/ to a backend, records a baseline of every load module through
`mockymock runner`, then uploads each folder of edits/ in turn and prints
the verdict of every module. Before rounds 3, 4 and 5 the previous round is
accepted (a new baseline is recorded), so each round is compared on its own.

    RUNNER_TOKEN=... python examples/oraclemix/e2e.py --url http://localhost:9999

Needs a backend with RUNNER_TOKEN set, `httpx`, and mockymock with a
GnuCOBOL toolchain on PATH (the runner compiles and runs the suites).
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx

HERE = Path(__file__).parent
ORG = "00000000-0000-0000-0000-000000000001"
ROUNDS = [
    "1-noop",
    "2-behaviour",
    "3-copybook-layout",
    "4-copybook-comment",
    "5-commarea-result",
]
ACCEPT_BEFORE = {"3-copybook-layout", "4-copybook-comment", "5-commarea-result"}


def zipped(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(folder.iterdir()):
            if path.is_file():
                archive.write(path, path.name)
    return buffer.getvalue()


class Backend:
    def __init__(self, url: str) -> None:
        self.api = url.rstrip("/") + "/api/v1"
        self.http = httpx.Client(timeout=120)

    def create_app(self, name: str) -> str:
        r = self.http.post(
            f"{self.api}/applications", json={"name": name, "organization_id": ORG}
        )
        r.raise_for_status()
        return r.json()["id"]

    def upload(self, app_id: str, folder: Path) -> None:
        r = self.http.post(
            f"{self.api}/applications/{app_id}/uploads",
            files={"file": ("src.zip", zipped(folder), "application/zip")},
        )
        r.raise_for_status()
        upload_id = r.json()["upload_id"]
        self.http.post(
            f"{self.api}/applications/{app_id}/uploads/{upload_id}/confirm",
            json={"auto_create_load_modules": True, "overwrite_existing": True},
        ).raise_for_status()
        for _ in range(300):
            status = self.http.get(f"{self.api}/uploads/{upload_id}").json()["status"]
            if status not in (
                "queued",
                "pending",
                "uploading",
                "extracting",
                "parsing",
                "processing",
            ):
                return
            time.sleep(1)

    def modules(self) -> list[dict]:
        r = self.http.get(f"{self.api}/load-modules", params={"page_size": 100})
        return sorted(r.json()["items"], key=lambda m: m["name"])

    def oracle(self, module_id: str) -> dict:
        return self.http.get(f"{self.api}/load-modules/{module_id}/oracle").json()

    def record_baselines(self, runner: list[str]) -> None:
        for module in self.modules():
            self.http.post(f"{self.api}/load-modules/{module['id']}/oracle/baseline")
        subprocess.run(runner, check=True, capture_output=True)


def latest(backend: Backend, module: dict) -> str:
    job = (backend.oracle(module["id"]).get("jobs") or [None])[0]
    if job is None or job["kind"] != "compare":
        return "-"
    parts = [str(job["verdict"])]
    for suite in (job.get("result") or {}).get("suites", []):
        detail = suite.get("error") or ""
        if suite.get("cases"):
            detail = (suite["cases"][0].get("differences") or [""])[0]
        parts.append(
            f"{suite['entry']}={suite['verdict']}"
            + (f" ({detail[:80]})" if detail else "")
        )
    return "  ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:9999")
    parser.add_argument("--app", default="oraclemix")
    args = parser.parse_args()
    runner = ["mockymock", "runner", "--url", args.url, "--once"]
    backend = Backend(args.url)
    app_id = backend.create_app(args.app)
    backend.upload(app_id, HERE / "src")
    backend.record_baselines(runner)
    print("baseline")
    for module in backend.modules():
        summary = backend.oracle(module["id"])
        suites = (summary.get("baseline") or {}).get("suites") or []
        job = summary["jobs"][0]
        errors = [
            s["entry"] for s in job["result"]["suites"] if s["verdict"] == "error"
        ]
        print(
            f"  {module['name']:9s}",
            [(s["entry"], s["cases"], s["events"]) for s in suites],
            f"not recorded: {errors}" if errors else "",
        )
    for name in ROUNDS:
        if name in ACCEPT_BEFORE:
            backend.record_baselines(runner)
        backend.upload(app_id, HERE / "edits" / name)
        subprocess.run(runner, check=True, capture_output=True)
        print(name)
        for module in backend.modules():
            print(f"  {module['name']:9s} {latest(backend, module)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
