(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const REGISTRY = window.__HERMES_PLUGINS__;

  if (!SDK || !REGISTRY) {
    console.error("[accounting_brain] Hermes plugin SDK/registry is unavailable.");
    return;
  }

  const h = SDK.React.createElement;
  const { useCallback, useEffect, useState } = SDK.hooks;
  const API_ROOT = "/api/plugins/accounting_brain";

  function JsonBlock({ value }) {
    if (!value) return null;
    return h("pre", { className: "ab-json" }, JSON.stringify(value, null, 2));
  }

  function Metric({ label, value }) {
    return h(
      "div",
      { className: "ab-metric" },
      h("span", { className: "ab-metric-label" }, label),
      h("strong", { className: "ab-metric-value" }, String(value ?? "—")),
    );
  }

  function StatusCard({ status, loading, onRefresh }) {
    const connected = Boolean(status?.connected);
    const configured = Boolean(status?.configured);
    const tone = connected ? "ok" : configured ? "warn" : "muted";
    const title = connected
      ? "Odoo connected — read only"
      : configured
        ? "Odoo configured, connection failed"
        : "Odoo secrets not configured";

    return h(
      "section",
      { className: `ab-card ab-status ${tone}` },
      h(
        "div",
        { className: "ab-card-head" },
        h("div", null,
          h("div", { className: "ab-eyebrow" }, "DATA SOURCE"),
          h("h2", null, title),
        ),
        h(
          "button",
          { className: "ab-button secondary", disabled: loading, onClick: onRefresh },
          loading ? "Checking…" : "Test connection",
        ),
      ),
      status?.message ? h("p", { className: "ab-message" }, status.message) : null,
      connected
        ? h(
            "div",
            { className: "ab-metrics" },
            h(Metric, { label: "Mode", value: status.mode }),
            h(Metric, { label: "Odoo", value: status.server_version }),
            h(Metric, { label: "User ID", value: status.authenticated_user_id }),
            h(Metric, { label: "Secrets exposed", value: status.secrets_exposed ? "YES" : "NO" }),
          )
        : h(
            "p",
            { className: "ab-help" },
            "Configure ODOO_URL, ODOO_DB, ODOO_USERNAME and ODOO_API_KEY in Railway Variables. Credentials never enter this browser page.",
          ),
    );
  }

  function AccountingBrainPage() {
    const [status, setStatus] = useState(null);
    const [statusLoading, setStatusLoading] = useState(true);
    const [running, setRunning] = useState("");
    const [result, setResult] = useState(null);
    const [error, setError] = useState("");
    const [maxMoves, setMaxMoves] = useState(1000);

    const refreshStatus = useCallback(async () => {
      setStatusLoading(true);
      try {
        const data = await SDK.fetchJSON(`${API_ROOT}/status`);
        setStatus(data);
      } catch (err) {
        setStatus({
          ok: false,
          configured: true,
          connected: false,
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setStatusLoading(false);
      }
    }, []);

    useEffect(() => {
      refreshStatus();
    }, [refreshStatus]);

    const run = useCallback(async (action) => {
      setRunning(action);
      setError("");
      setResult(null);
      try {
        const init = { method: "POST" };
        if (action === "audit") {
          init.headers = { "Content-Type": "application/json" };
          init.body = JSON.stringify({ max_moves: Number(maxMoves) || 1000 });
        }
        const data = await SDK.fetchJSON(`${API_ROOT}/${action}`, init);
        setResult({ action, data });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setRunning("");
      }
    }, [maxMoves]);

    const audit = result?.action === "audit" ? result.data : null;
    const discovery = result?.action === "discover" ? result.data : null;

    return h(
      "main",
      { className: "ab-page" },
      h(
        "header",
        { className: "ab-hero" },
        h("div", { className: "ab-eyebrow" }, "HERMES // ACCOUNTING BRAIN"),
        h("h1", null, "Accounting Brain"),
        h(
          "p",
          null,
          "Evidence-first learning from your real Odoo accounting history. Phase 1 is strictly read-only: discover the live schema, measure data quality, then decide how to train the accountant.",
        ),
        h(
          "div",
          { className: "ab-safety" },
          h("span", null, "READ ONLY"),
          h("span", null, "NO AUTO-POST"),
          h("span", null, "NO SECRETS IN GITHUB"),
          h("span", null, "DETERMINISTIC QUALITY GATES"),
        ),
      ),

      h(StatusCard, { status, loading: statusLoading, onRefresh: refreshStatus }),

      h(
        "section",
        { className: "ab-grid" },
        h(
          "article",
          { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 1"),
          h("h2", null, "Discover actual Odoo schema"),
          h("p", null, "Inspect the accounting models and fields that really exist in this Odoo instance instead of assuming a version-specific schema."),
          h(
            "button",
            {
              className: "ab-button",
              disabled: Boolean(running) || !status?.connected,
              onClick: () => run("discover"),
            },
            running === "discover" ? "Discovering…" : "Run schema discovery",
          ),
        ),
        h(
          "article",
          { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 2"),
          h("h2", null, "Audit historical posted journals"),
          h("p", null, "Grade historical examples as Gold, Silver or Rejected and measure attachment, partner, tax and analytic coverage before any model training."),
          h(
            "label",
            { className: "ab-label" },
            "Posted entries to sample",
            h("input", {
              className: "ab-input",
              type: "number",
              min: 1,
              max: 5000,
              step: 100,
              value: maxMoves,
              onChange: (event) => setMaxMoves(event.target.value),
            }),
          ),
          h(
            "button",
            {
              className: "ab-button",
              disabled: Boolean(running) || !status?.connected,
              onClick: () => run("audit"),
            },
            running === "audit" ? "Auditing…" : "Audit posted journals",
          ),
        ),
      ),

      error
        ? h("section", { className: "ab-card ab-error", role: "alert" }, h("h2", null, "Operation failed"), h("p", null, error))
        : null,

      discovery
        ? h(
            "section",
            { className: "ab-card" },
            h("div", { className: "ab-eyebrow" }, "DISCOVERY RESULT"),
            h("h2", null, "Live Odoo schema map"),
            h(
              "div",
              { className: "ab-metrics" },
              h(Metric, { label: "Models requested", value: discovery.models_requested }),
              h(Metric, { label: "Available", value: discovery.models_available }),
              h(Metric, { label: "Unavailable", value: discovery.models_unavailable }),
              h(Metric, { label: "Private report", value: discovery.report_file }),
            ),
            h(JsonBlock, { value: discovery.available_models }),
          )
        : null,

      audit
        ? h(
            "section",
            { className: "ab-card" },
            h("div", { className: "ab-eyebrow" }, "AUDIT RESULT"),
            h("h2", null, "Training-data readiness"),
            h(
              "div",
              { className: "ab-metrics" },
              h(Metric, { label: "Sampled posted entries", value: audit.selection?.sampled_posted_moves }),
              h(Metric, { label: "Total posted entries", value: audit.selection?.total_matching_posted_moves }),
              h(Metric, { label: "Gold rate", value: audit.quality?.gold_rate }),
              h(Metric, { label: "Attachment coverage", value: audit.quality?.attachment_coverage }),
              h(Metric, { label: "Partner coverage", value: audit.quality?.partner_coverage }),
              h(Metric, { label: "Tax evidence", value: audit.quality?.tax_evidence_coverage }),
              h(Metric, { label: "Analytic coverage", value: audit.quality?.analytic_distribution_coverage }),
              h(Metric, { label: "Private report", value: audit.report_file }),
            ),
            h("h3", null, "Gold / Silver / Rejected"),
            h(JsonBlock, { value: audit.quality?.grades }),
            h("h3", null, "Journal & document taxonomy"),
            h(JsonBlock, { value: audit.taxonomy }),
          )
        : null,

      h(
        "footer",
        { className: "ab-footer" },
        "Training is intentionally disabled in this phase. We choose OCR / document model / base LLM only after the real Odoo audit tells us what the data supports.",
      ),
    );
  }

  REGISTRY.register("accounting_brain", AccountingBrainPage);
})();
