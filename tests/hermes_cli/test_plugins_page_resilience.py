from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGINS_PAGE = _REPO_ROOT / "web" / "src" / "pages" / "PluginsPage.tsx"


def test_plugins_page_guards_dashboard_plugins_without_tabs():
    source = _PLUGINS_PAGE.read_text(encoding="utf-8")

    assert "m.tab?.path && !m.tab.hidden" in source
    assert "dashboardOnlyPlugins.map((m)" in source


def test_plugins_page_falls_back_to_dashboard_manifest_endpoint():
    source = _PLUGINS_PAGE.read_text(encoding="utf-8")

    assert "const manifests = await api.getPlugins();" in source
    assert "setFallbackDashboardPlugins(manifests);" in source
    assert "hub?.orphan_dashboard_plugins ?? fallbackDashboardPlugins" in source
    assert "Plugin Hub metadata failed to load; dashboard plugins are available in safe mode." in source
