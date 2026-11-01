"""`mockymock runner` without a toolchain: pack checks, suite steps run by a
fake mockymock, and the claim / run / report loop against a fake backend."""

from __future__ import annotations

import io
import json
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from mockymock.cli.main import main
from mockymock.runner import RunnerClientError, extract_pack, run_job, serve
from mockymock.runner.jobs import JobPackError, load_manifest, run_pack

FAKE_MOCKYMOCK = textwrap.dedent("""
    import json, sys
    from pathlib import Path
    args = sys.argv[1:]
    print("fake", " ".join(args))
    def after(flag):
        return args[args.index(flag) + 1] if flag in args else None
    if args[0] == "generate":
        Path(after("-o")).write_text("TESTSUITE 'generated'\\n")
    elif args[0] == "run":
        if after("--record-baseline"):
            Path(after("--record-baseline")).write_text(json.dumps(
                {"format": "mockymock-baseline", "version": 1,
                 "cases": [{"name": "c1"}]}))
        if after("--baseline-json"):
            same = "SAME" in Path(after("--baseline")).read_text()
            Path(after("--baseline-json")).write_text(json.dumps(
                {"matches": same, "counts": {"same": int(same), "differs": int(not same)}}))
            sys.exit(0 if same else 1)
    """)


@pytest.fixture
def fake_command(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_mockymock.py"
    script.write_text(FAKE_MOCKYMOCK)
    return [sys.executable, str(script)]


def _manifest(kind: str = "baseline", **suite: object) -> dict:
    entry = {
        "entry": "PAYMAIN",
        "program": "src/PAYMAIN.cbl",
        "cut": "tests/PAYMAIN.cut",
        "generate": "mockymock generate src/PAYMAIN.cbl --real src/PAYCALC.cbl",
        "baseline": None,
    }
    entry.update(suite)
    return {
        "version": 1,
        "kind": kind,
        "load_module": "PAYMAIN",
        "copybook_path": "copybooks",
        "suites": [entry],
    }


def _zip(files: dict[str, str], root: str = "PAYMAIN-integration-tests") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for path, text in files.items():
            archive.writestr(f"{root}/{path}" if root else path, text)
    return out.getvalue()


def _pack_files(manifest: dict, **extra: str) -> dict[str, str]:
    files = {
        "oracle.json": json.dumps(manifest),
        "src/PAYMAIN.cbl": "PROGRAM",
        "src/PAYCALC.cbl": "PROGRAM",
        "copybooks/.keep": "",
    }
    files.update(extra)
    return files


def test_extract_pack_finds_the_manifest_under_the_root(tmp_path: Path):
    pack = extract_pack(_zip(_pack_files(_manifest())), tmp_path)
    assert pack.name == "PAYMAIN-integration-tests"
    assert (pack / "src" / "PAYMAIN.cbl").is_file()


@pytest.mark.parametrize("name", ["../evil.txt", "/abs/evil.txt", "a/../../evil.txt"])
def test_extract_pack_refuses_entries_leaving_the_folder(tmp_path: Path, name: str):
    content = _zip({"oracle.json": "{}", name: "x"}, root="")
    with pytest.raises(JobPackError, match="escapes"):
        extract_pack(content, tmp_path / "work")


def test_extract_pack_refuses_symbolic_links(tmp_path: Path):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("oracle.json", "{}")
        link = zipfile.ZipInfo("link")
        link.external_attr = (0o120777) << 16
        archive.writestr(link, "/etc/passwd")
    with pytest.raises(JobPackError, match="symbolic link"):
        extract_pack(out.getvalue(), tmp_path)


def test_extract_pack_needs_a_zip_with_a_manifest(tmp_path: Path):
    with pytest.raises(JobPackError, match="not a zip"):
        extract_pack(b"nope", tmp_path)
    with pytest.raises(JobPackError, match="no oracle.json"):
        extract_pack(_zip({"README.md": "x"}), tmp_path)


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ({"version": 2, "kind": "baseline", "suites": [{}]}, "version"),
        ({"version": 1, "kind": "explode", "suites": [{}]}, "kind"),
        ({"version": 1, "kind": "baseline", "suites": []}, "no suites"),
        ({"version": 1, "kind": "baseline", "suites": ["x"]}, "objects"),
        ([], "not an object"),
    ],
)
def test_load_manifest_rejects_bad_manifests(tmp_path: Path, manifest, message):
    (tmp_path / "oracle.json").write_text(json.dumps(manifest))
    with pytest.raises(JobPackError, match=message):
        load_manifest(tmp_path)


def test_baseline_job_generates_the_cut_and_reports_the_baseline(
    tmp_path: Path, fake_command
):
    pack = extract_pack(_zip(_pack_files(_manifest())), tmp_path)
    payload = run_pack(pack, command=fake_command)
    (suite,) = payload["suites"]
    assert suite["entry"] == "PAYMAIN"
    assert suite["cut_path"] == "tests/PAYMAIN.cut"
    assert suite["cut_text"] == "TESTSUITE 'generated'\n"
    assert suite["baseline"]["cases"] == [{"name": "c1"}]
    assert suite["exit_code"] == 0
    assert "--real src/PAYCALC.cbl" in suite["log"]
    assert "error" not in suite


def test_baseline_job_keeps_an_existing_cut(tmp_path: Path, fake_command):
    files = _pack_files(_manifest(), **{"tests/PAYMAIN.cut": "TESTSUITE 'mine'\n"})
    pack = extract_pack(_zip(files), tmp_path)
    (suite,) = run_pack(pack, command=fake_command)["suites"]
    assert suite["cut_text"] == "TESTSUITE 'mine'\n"
    assert "generate" not in suite["log"]


@pytest.mark.parametrize("marker", ["SAME", "DIFF"])
def test_compare_job_reports_the_comparison(tmp_path: Path, fake_command, marker):
    manifest = _manifest("compare", baseline="baselines/PAYMAIN.json")
    files = _pack_files(
        manifest,
        **{"tests/PAYMAIN.cut": "TESTSUITE\n", "baselines/PAYMAIN.json": marker},
    )
    pack = extract_pack(_zip(files), tmp_path)
    (suite,) = run_pack(pack, command=fake_command)["suites"]
    assert suite["comparison"]["matches"] is (marker == "SAME")
    assert suite["exit_code"] == (0 if marker == "SAME" else 1)


def test_compare_suite_without_a_baseline_is_an_error(tmp_path: Path, fake_command):
    files = _pack_files(_manifest("compare"), **{"tests/PAYMAIN.cut": "TESTSUITE\n"})
    pack = extract_pack(_zip(files), tmp_path)
    (suite,) = run_pack(pack, command=fake_command)["suites"]
    assert suite["error"].startswith("no baseline")
    assert suite["exit_code"] is None


def test_compare_suite_without_its_frozen_cut_is_an_error(tmp_path: Path, fake_command):
    manifest = _manifest("compare", baseline="baselines/PAYMAIN.json")
    files = _pack_files(manifest, **{"baselines/PAYMAIN.json": "SAME"})
    pack = extract_pack(_zip(files), tmp_path)
    (suite,) = run_pack(pack, command=fake_command)["suites"]
    assert "cut is missing" in suite["error"]


@pytest.mark.parametrize(
    ("suite", "message"),
    [
        ({"program": "../outside.cbl"}, "leaves the pack"),
        ({"cut": "/tmp/x.cut"}, "leaves the pack"),
        ({"generate": "rm -rf /"}, "not a mockymock generate"),
        ({"generate": "mockymock generate src/P.cbl --output /x"}, "not allowed"),
        (
            {"generate": "mockymock generate src/P.cbl --real ../../x"},
            "leaves the pack",
        ),
        ({"generate": None}, "no generate command"),
    ],
)
def test_suite_paths_and_commands_are_checked(
    tmp_path: Path, fake_command, suite, message
):
    pack = extract_pack(_zip(_pack_files(_manifest(**suite))), tmp_path)
    (outcome,) = run_pack(pack, command=fake_command)["suites"]
    assert message in outcome["error"]


def test_a_run_that_writes_nothing_is_reported(tmp_path: Path):
    pack = extract_pack(
        _zip(_pack_files(_manifest(), **{"tests/PAYMAIN.cut": "T"})), tmp_path
    )
    (suite,) = run_pack(pack, command=[sys.executable, "-c", "pass"])["suites"]
    assert suite["error"] == "mockymock run produced no baseline"


def test_a_suite_that_hangs_times_out(tmp_path: Path):
    pack = extract_pack(
        _zip(_pack_files(_manifest(), **{"tests/PAYMAIN.cut": "T"})), tmp_path
    )
    hang = [sys.executable, "-c", "import time; time.sleep(30)"]
    (suite,) = run_pack(pack, command=hang, timeout=0.5)["suites"]
    assert suite["error"] == "mockymock run timed out"
    assert "timed out after" in suite["log"]


def test_run_job_reports_a_broken_pack_as_a_job_error(tmp_path: Path):
    payload = run_job(b"not a zip", work_dir=tmp_path)
    assert payload["suites"] == []
    assert "not a zip" in payload["error"]
    assert list(tmp_path.iterdir()) == []  # the work folder is removed


class FakeClient:
    def __init__(self, jobs: list[dict], packs: dict[str, bytes]) -> None:
        self.jobs = jobs
        self.packs = packs
        self.reports: list[tuple[str, dict]] = []
        self.names: list[str] = []

    def claim(self, runner_name: str):
        self.names.append(runner_name)
        return self.jobs.pop(0) if self.jobs else None

    def download_pack(self, job: dict) -> bytes:
        if job["id"] not in self.packs:
            raise RunnerClientError("HTTP 404", status=404)
        return self.packs[job["id"]]

    def report(self, job_id: str, payload: dict) -> dict:
        self.reports.append((job_id, payload))
        return {"status": "succeeded"}


def test_serve_once_runs_every_queued_job(tmp_path: Path, fake_command):
    client = FakeClient(
        [{"id": "j1", "kind": "baseline"}, {"id": "j2", "kind": "baseline"}],
        {"j1": _zip(_pack_files(_manifest()))},
    )
    lines: list[str] = []
    ran = serve(
        client,  # type: ignore[arg-type]
        runner_name="r1",
        once=True,
        command=fake_command,
        work_dir=tmp_path,
        log=lines.append,
    )
    assert ran == 2
    assert client.names == ["r1", "r1", "r1"]
    (first, first_payload), (second, second_payload) = client.reports
    assert first == "j1" and first_payload["suites"][0]["baseline"]
    assert second == "j2" and "cannot download" in second_payload["error"]
    assert any("job j1 succeeded" in line for line in lines)


def test_serve_retries_an_unreachable_backend_but_not_a_bad_token():
    class Flaky(FakeClient):
        def __init__(self, errors: list[RunnerClientError]) -> None:
            super().__init__([], {})
            self.errors = errors

        def claim(self, runner_name: str):
            if self.errors:
                raise self.errors.pop(0)
            raise KeyboardInterrupt

    sleeps: list[float] = []
    client = Flaky([RunnerClientError("down")])
    with pytest.raises(KeyboardInterrupt):
        serve(client, poll_interval=3, log=lambda _: None, sleep=sleeps.append)  # type: ignore[arg-type]
    assert sleeps == [3]
    with pytest.raises(RunnerClientError):
        serve(Flaky([RunnerClientError("no", status=401)]), log=lambda _: None)  # type: ignore[arg-type]


def test_cli_needs_a_url_and_a_token(monkeypatch, capsys):
    monkeypatch.delenv("LEGACYLENS_URL", raising=False)
    monkeypatch.delenv("RUNNER_TOKEN", raising=False)
    assert main(["runner", "--once"]) == 2
    assert "no backend URL" in capsys.readouterr().out
    assert main(["runner", "--once", "--url", "http://localhost:1"]) == 2
    assert "RUNNER_TOKEN is not set" in capsys.readouterr().out


def test_cli_reports_an_unreachable_backend(monkeypatch, capsys):
    monkeypatch.setenv("RUNNER_TOKEN", "t")
    assert main(["runner", "--once", "--url", "http://127.0.0.1:9"]) == 1
    assert "mockymock runner:" in capsys.readouterr().out


def test_client_speaks_the_runner_api(tmp_path: Path, fake_command):
    """RunnerClient + serve against a real HTTP server shaped like the backend."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from mockymock.runner import RunnerClient

    pack = _zip(_pack_files(_manifest()))
    seen: dict[str, object] = {"claims": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence
            pass

        def _send(self, code: int, body: bytes = b"", kind: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.headers.get("X-Runner-Token") != "secret":
                return self._send(401, b'{"detail":"bad token"}')
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/v1/runner/jobs/claim":
                seen["claims"] = int(seen["claims"]) + 1  # type: ignore[call-overload]
                seen["runner"] = body["runner"]
                if seen["claims"] == 1:
                    job = {
                        "id": "j1",
                        "kind": "baseline",
                        "pack_url": "/api/v1/runner/jobs/j1/pack",
                    }
                    return self._send(200, json.dumps(job).encode())
                return self._send(204)
            seen["result"] = body
            return self._send(200, b'{"status": "succeeded"}')

        def do_GET(self):
            return self._send(200, pack, "application/zip")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        ran = serve(
            RunnerClient(url, "secret"),
            runner_name="r9",
            once=True,
            command=fake_command,
            work_dir=tmp_path,
            log=lambda _: None,
        )
        assert ran == 1
        assert seen["runner"] == "r9"
        result = seen["result"]
        assert result["suites"][0]["baseline"]["format"] == "mockymock-baseline"  # type: ignore[index]
        with pytest.raises(RunnerClientError) as caught:
            RunnerClient(url, "wrong").claim("r9")
        assert caught.value.status == 401
    finally:
        server.shutdown()


def test_client_never_sends_the_token_to_another_host():
    from mockymock.runner import RunnerClient

    client = RunnerClient("http://backend:9999", "secret")
    with pytest.raises(RunnerClientError, match="outside the backend"):
        client.download_pack({"id": "j1", "pack_url": "http://evil.example/pack"})
