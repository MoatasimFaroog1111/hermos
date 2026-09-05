from pathlib import Path

from plugins.accounting_brain.dashboard import plugin_api_v2


def test_dashboard_baseline_uses_existing_runner_and_stays_safe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    fake_llm = object()

    monkeypatch.setattr(plugin_api_v2, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(plugin_api_v2, "build_host_llm", lambda: fake_llm)

    def fake_run(datasets_root, llm, *, timeout_seconds, max_tokens):
        captured.update(
            {
                "datasets_root": datasets_root,
                "llm": llm,
                "timeout_seconds": timeout_seconds,
                "max_tokens": max_tokens,
            }
        )
        return {
            "ok": False,
            "stage": "BLOCKED_BY_PRODUCTION_GATE",
            "cases": 104,
            "providers": ["fake"],
            "models": ["fake-model"],
            "usage": {"total_tokens": 123, "cost_usd": 0.01},
            "score_report": {
                "aggregate": {"strict_pass_rate": 0.5},
                "production_gate": {"ok": False},
            },
            "safety": {
                "ground_truth_visible_to_model": False,
                "odoo_mutations": False,
                "auto_post": False,
                "human_review_required": True,
            },
        }

    monkeypatch.setattr(plugin_api_v2, "run_baseline_evaluation", fake_run)

    request = plugin_api_v2.BaselineEvaluationRequest(
        timeout_seconds=90,
        max_tokens=1024,
    )
    report = plugin_api_v2._run_baseline_sync(request)

    assert captured == {
        "datasets_root": tmp_path / "accounting_brain" / "datasets",
        "llm": fake_llm,
        "timeout_seconds": 90.0,
        "max_tokens": 1024,
    }
    assert report["cases"] == 104
    assert report["dashboard_execution"] == {
        "background_task": True,
        "training_performed": False,
        "odoo_mutations": False,
        "auto_post": False,
    }


def test_persisted_dashboard_state_is_private_and_secret_free(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(plugin_api_v2, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        plugin_api_v2,
        "_BASELINE_STATE",
        {
            "status": "completed",
            "started_at": "20260905T100000000000Z",
            "finished_at": "20260905T100500000000Z",
            "result": {
                "cases": 104,
                "safety": {
                    "odoo_mutations": False,
                    "auto_post": False,
                },
            },
            "error": None,
        },
    )

    path = plugin_api_v2._persist_state()
    text = path.read_text(encoding="utf-8")

    assert path.parent == tmp_path / "accounting_brain" / "reports"
    assert "ODOO_API_KEY" not in text
    assert '"odoo_mutations": false' in text
    assert '"auto_post": false' in text
    assert path.stat().st_mode & 0o777 == 0o600
