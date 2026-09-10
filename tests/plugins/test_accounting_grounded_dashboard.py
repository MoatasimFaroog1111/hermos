from pathlib import Path

from plugins.accounting_brain.dashboard import plugin_api_v2


def test_dashboard_grounded_uses_trusted_runner_and_stays_safe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    fake_llm = object()

    monkeypatch.setattr(plugin_api_v2, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(plugin_api_v2, "build_host_llm", lambda: fake_llm)

    def fake_run(
        datasets_root,
        llm,
        *,
        top_k,
        timeout_seconds,
        max_tokens,
        progress_callback=None,
    ):
        captured.update(
            {
                "datasets_root": datasets_root,
                "llm": llm,
                "top_k": top_k,
                "timeout_seconds": timeout_seconds,
                "max_tokens": max_tokens,
                "progress_callback": progress_callback,
            }
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "case_completed",
                    "total_cases": 104,
                    "completed_cases": 1,
                    "current_case": "case-1",
                    "repairs_attempted": 0,
                    "elapsed_seconds": 1.0,
                }
            )
        return {
            "ok": False,
            "stage": "BLOCKED_BY_PRODUCTION_GATE",
            "cases": 104,
            "production_gate": {"ok": False},
            "safety": {
                "holdout_ground_truth_visible_to_model": False,
                "historical_amounts_visible_to_model": False,
                "odoo_mutations": False,
                "auto_post": False,
                "human_review_required": True,
            },
        }

    monkeypatch.setattr(plugin_api_v2, "run_grounded_evaluation", fake_run)

    request = plugin_api_v2.GroundedEvaluationRequest(
        top_k=5,
        timeout_seconds=90,
        max_tokens=1024,
    )
    report = plugin_api_v2._run_grounded_sync(request)

    assert captured["datasets_root"] == tmp_path / "accounting_brain" / "datasets"
    assert captured["llm"] is fake_llm
    assert captured["top_k"] == 5
    assert captured["timeout_seconds"] == 90.0
    assert captured["max_tokens"] == 1024
    assert captured["progress_callback"] is plugin_api_v2._record_grounded_progress
    assert plugin_api_v2._GROUNDED_STATE["progress"]["phase"] == "case_completed"
    assert plugin_api_v2._GROUNDED_STATE["progress"]["completed_cases"] == 1
    assert report["cases"] == 104
    assert report["dashboard_execution"] == {
        "background_task": True,
        "training_performed": False,
        "odoo_mutations": False,
        "auto_post": False,
        "official_production_gate": True,
    }


def test_persisted_grounded_state_is_private_and_keeps_safety_flags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(plugin_api_v2, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(
        plugin_api_v2,
        "_GROUNDED_STATE",
        {
            "status": "completed",
            "started_at": "20260910T120000000000Z",
            "finished_at": "20260910T130000000000Z",
            "result": {
                "stage": "BLOCKED_BY_PRODUCTION_GATE",
                "cases": 104,
            },
            "error": None,
            "progress": {
                "phase": "completed",
                "total_cases": 104,
                "completed_cases": 104,
                "current_case": None,
                "repairs_attempted": 0,
            },
        },
    )

    path = plugin_api_v2._persist_grounded_state()
    text = path.read_text(encoding="utf-8")

    assert path.parent == tmp_path / "accounting_brain" / "reports"
    assert path.name.startswith("grounded-model-evaluation-")
    assert "ODOO_API_KEY" not in text
    assert '"historical_amounts_visible_to_model": false' in text
    assert '"odoo_mutations": false' in text
    assert '"auto_post": false' in text
    assert '"completed_cases": 104' in text
    assert path.stat().st_mode & 0o777 == 0o600
