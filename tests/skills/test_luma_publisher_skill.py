"""Offline safety checks for Luma publisher skill integration."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[2]


def _load(name, filename, monkeypatch):
    if filename == "publish_x.py":
        monkeypatch.setitem(sys.modules, "tweepy", types.SimpleNamespace(Forbidden=type("Forbidden", (Exception,), {}), Client=type("Client", (), {}), API=type("API", (), {})))
    spec = importlib.util.spec_from_file_location(name, ROOT / "luma_publisher" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_x_defaults_to_dry_run(monkeypatch, capsys):
    x = _load("test_luma_x", "publish_x.py", monkeypatch)
    monkeypatch.setattr(x, "load_x_clients", Mock(side_effect=AssertionError("network access")))
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("prompt")))
    monkeypatch.setattr(sys, "argv", ["publish_x.py"])
    x.main()
    assert "Dry Run" in capsys.readouterr().out


def test_tiktok_defaults_to_dry_run(monkeypatch, tmp_path, capsys):
    tik = _load("test_luma_tiktok", "publish_tiktok.py", monkeypatch)
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"dummy")
    monkeypatch.setattr(tik.requests, "post", Mock(side_effect=AssertionError("network access")))
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("prompt")))
    monkeypatch.setattr(sys, "argv", ["publish_tiktok.py", "--media", str(media)])
    tik.main()
    assert "Dry Run" in capsys.readouterr().out


def test_telegram_defaults_to_preview(monkeypatch, capsys):
    tg = _load("test_luma_channel", "channel_post.py", monkeypatch)
    monkeypatch.setattr(tg.requests, "post", Mock(side_effect=AssertionError("network access")))
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("prompt")))
    monkeypatch.setattr(sys, "argv", ["channel_post.py", "--text", "hello"])
    tg.main()
    assert "DRY_RUN" in capsys.readouterr().out


def test_telegram_declined_confirmation(monkeypatch):
    tg = _load("test_luma_channel_2", "channel_post.py", monkeypatch)
    monkeypatch.setattr("builtins.input", lambda *_: "NO")
    monkeypatch.setattr(tg.requests, "post", Mock(side_effect=AssertionError("network access")))
    assert tg.publish_channel("hello", publish=True) is False


def test_skill_metadata_and_requirements():
    skill = (ROOT / "skills/luma-publisher/SKILL.md").read_text()
    assert "name: luma-publisher" in skill
    assert "--publish" in skill
    assert len(next(x.split(": ", 1)[1] for x in skill.splitlines() if x.startswith("description:"))) <= 60
    req = (ROOT / "requirements.txt").read_text()
    assert all(s in req for s in ("requests==", "python-dotenv==", "tweepy=="))
