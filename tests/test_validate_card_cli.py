from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "validate_card.py"


def _run(*args: str):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def test_cli_usage_and_missing_file():
    usage = _run()
    assert usage.returncode == 2
    assert "usage:" in usage.stderr
    missing = _run(str(ROOT / "cards" / "does-not-exist.json"))
    assert missing.returncode == 2
    assert "file not found" in missing.stderr


def test_cli_ok_for_sample_cards():
    for name in ("aidata.hermes.sample.json", "lab.inspector.sample.json", "lab.echo.sample.json"):
        res = _run(str(ROOT / "cards" / name))
        assert res.returncode == 0, res.stdout + res.stderr
        assert res.stdout.startswith("OK ")


def test_cli_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    res = _run(str(path))
    assert res.returncode == 1
    assert "invalid JSON" in res.stderr


def test_cli_rejects_structural_secret_and_write_class(tmp_path):
    card = json.loads((ROOT / "cards" / "lab.inspector.sample.json").read_text(encoding="utf-8"))
    broken = dict(card)
    del broken["name"]
    path = tmp_path / "missing-name.json"
    path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    missing = _run(str(path))
    assert missing.returncode == 1
    assert "FAIL" in missing.stdout
    assert "missing required field: name" in missing.stdout

    secret = json.loads(json.dumps(card))
    secret["api_token"] = "sk-this-is-long-enough-to-look-real"
    secret_path = tmp_path / "secret.json"
    secret_path.write_text(json.dumps(secret), encoding="utf-8")
    leaked = _run(str(secret_path))
    assert leaked.returncode == 1
    assert "forbidden property name" in leaked.stdout or "secret-like" in leaked.stdout

    write_card = json.loads(json.dumps(card))
    write_card["skills"][0]["x-sunny"]["side_effects"] = "write"
    write_card["skills"][0]["x-sunny"]["data_class"] = "internal"
    write_path = tmp_path / "write-unrestricted.json"
    write_path.write_text(json.dumps(write_card, ensure_ascii=False), encoding="utf-8")
    write = _run(str(write_path))
    assert write.returncode == 1
    assert "data_class=restricted" in write.stdout
