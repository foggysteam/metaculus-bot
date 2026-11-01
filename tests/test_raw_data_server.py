"""
Checks for raw_data_server.py: what it refuses, how it reads files, and that the protocol works
and keys do not reach it. Uses no model calls.

Usage: uv run python tests/test_raw_data_server.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import raw_data_server as s  # noqa: E402


def test_refuses_anything_not_public() -> None:
    for url in (
        "file:///etc/passwd",
        "ftp://example.com/x.csv",
        "http://localhost:8000/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
        "https://user:secret@example.com/",
        "https://example.com:8443/",
        "https://www.metaculus.com/questions/46281/",
        "https://metaculus.com/api/comments/",
    ):
        assert s.refusal(url), f"should refuse {url}"
    assert s.refusal("https://example.com/data.csv") is None


def test_redirect_to_private_address_is_refused() -> None:
    class Redirect:
        is_redirect, is_permanent_redirect = True, False
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    real_get, real_refusal = s.requests.get, s.refusal
    s.requests.get = lambda *a, **k: Redirect()
    try:
        s.download("https://example.com/start")
    except ValueError as e:
        assert "169.254.169.254" in str(e)
    else:
        raise AssertionError("followed a redirect to a private address")
    finally:
        s.requests.get, s.refusal = real_get, real_refusal


def test_csv_default_view_keeps_header_and_newest_rows() -> None:
    body = "\n".join(["date,value"] + [f"2026-{i:04d},{i}" for i in range(500)]).encode()
    lines, _ = s.to_lines("https://x.org/a.csv", "text/csv", body, False)
    chosen, _ = s.select(lines, None, None, 80)
    assert chosen[0] == (1, "date,value") and chosen[-1][1] == "2026-0499,499" and len(chosen) == 80


def test_contains_and_start_line() -> None:
    lines = [f"row {i}" for i in range(1, 101)]
    assert [n for n, _ in s.select(lines, "row 99|row 100", None, 80)[0]] == [99, 100]
    assert [n for n, _ in s.select(lines, None, -3, 80)[0]] == [98, 99, 100]
    assert [n for n, _ in s.select(lines, None, 5, 2)[0]] == [5, 6]


def test_json_is_one_record_per_line() -> None:
    body = json.dumps({"updated": "2026-10-27", "rows": [{"d": i} for i in range(10)]}).encode()
    lines, _ = s.to_lines("https://x.org/a.json", "application/json", body, False)
    assert lines[0] == 'updated: "2026-10-27"' and lines[1] == "rows: list of 10 items" and lines[-1] == '{"d": 9}'


def test_html_gives_text_and_data_links() -> None:
    body = b'<html><script>var a="/data/national.json"</script><style>x{}</style><body><p>Hello</p><a href="f.csv">x</a></body></html>'
    lines, notes = s.to_lines("https://x.org/page/", "text/html", body, False)
    assert "Hello" in lines and "var a" not in " ".join(lines)
    assert "https://x.org/data/national.json" in notes[0] and "https://x.org/page/f.csv" in notes[0]


def test_binary_is_declined() -> None:
    lines, notes = s.to_lines("https://x.org/a.pdf", "application/pdf", b"%PDF-1.7 ...", False)
    assert not lines and "binary" in notes[0]


def test_output_never_exceeds_the_limit() -> None:
    real = s.download
    s.download = lambda url: (url, 200, "text/csv", ("x" * 300 + "\n").encode() * 400, False)
    try:
        assert len(s.fetch_raw("https://example.com/a.csv", max_lines=400)) < s.MAX_OUTPUT_CHARS + 200
    finally:
        s.download = real


def test_protocol_and_no_keys_in_the_environment() -> None:
    env = dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN="SECRET-A", METACULUS_TOKEN="SECRET-B", ASKNEWS_API_KEY="SECRET-C")
    # Replaces the fetch with a dump of the server's own environment, after scrub_environment has run.
    code = (
        "import os, raw_data_server as s\n"
        "s.fetch_raw = lambda **k: ' '.join(f'{a}={b}' for a, b in os.environ.items())\n"
        "s.main()\n"
    )
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "fetch_raw", "arguments": {"url": "https://example.com"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "something_else", "arguments": {}}},
    ]
    done = subprocess.run(
        [sys.executable, "-c", code],
        input="\n".join(json.dumps(m) for m in messages).encode(),
        capture_output=True,
        env=env,
        cwd=ROOT,
        timeout=60,
    )
    replies = {r["id"]: r for r in map(json.loads, done.stdout.decode().splitlines())}
    assert replies[1]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[2]["result"]["tools"][0]["name"] == "fetch_raw"
    dumped = replies[3]["result"]["content"][0]["text"]
    assert "SECRET" not in dumped and "PATH" in dumped.upper(), dumped[:200]
    assert "error" in replies[4]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")
