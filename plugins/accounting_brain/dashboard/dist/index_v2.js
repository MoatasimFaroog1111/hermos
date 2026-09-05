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
    const companies = Array.isArray(status?.companies) ? status.companies : [];
    const tone = connected ? "ok" : configured ? "warn" : "muted";
    const title = connected
      ? "Odoo connected — read only"
      : configured
        ? "Odoo configured, connection failed"
        : "Odoo secrets not configured";
    const scope = !connected
      ? "—"
      : status?.company_selection_required
        ? "Select one company"
        : companies[0]?.name || "Unavailable";

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
            h(Metric, { label: "Accessible companies", value: companies.length }),
            h(Metric, { label: "Audit scope", value: scope }),
            h(Metric, { label: "Secrets exposed", value: status.secrets_exposed ? "YES" : "NO" }),
          )
        : h("p", { className: "ab-help" }, "Configure Odoo credentials only in Railway Variables; credentials never enter this browser page."),
    );
  }

  function AccountingBrainPage() {
    const [status, setStatus] = useState(null);
    const [statusLoading, setStatusLoading] = useState(true);
    const [running, setRunning] = useState("");
    const [result, setResult] = useState(null);
    const [error, setError] = useState("");
    const [maxMoves, setMaxMoves] = useState(1000);
    const [companyId, setCompanyId] = useState("");
    const [includeSilver, setIncludeSilver] = useState(false);
    const [downloadAttachments, setDownloadAttachments] = useState(false);
    const [maxAttachmentMb, setMaxAttachmentMb] = useState(25);
    const [hydrateEvaluationSources, setHydrateEvaluationSources] = useState(false);
    const [evaluationHoldoutFraction, setEvaluationHoldoutFraction] = useState(0.20);
    const [evaluationMinHoldout, setEvaluationMinHoldout] = useState(100);
    const [evaluationMinContentCoverage, setEvaluationMinContentCoverage] = useState(0.90);
    const [baselineTimeout, setBaselineTimeout] = useState(120);
    const [baselineMaxTokens, setBaselineMaxTokens] = useState(1800);
    const [baseline, setBaseline] = useState(null);

    const refreshStatus = useCallback(async () => {
      setStatusLoading(true);
      try {
        const data = await SDK.fetchJSON(`${API_ROOT}/status`);
        setStatus(data);
        const companies = Array.isArray(data?.companies) ? data.companies : [];
        setCompanyId(current => {
          if (companies.length === 1) return String(companies[0].id);
          return companies.some(company => String(company.id) === String(current)) ? String(current) : "";
        });
      } catch (err) {
        setStatus({ ok: false, configured: true, connected: false, companies: [], message: err instanceof Error ? err.message : String(err) });
        setCompanyId("");
      } finally {
        setStatusLoading(false);
      }
    }, []);

    const refreshBaseline = useCallback(async () => {
      try {
        const data = await SDK.fetchJSON(`${API_ROOT}/evaluation/baseline`);
        setBaseline(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, []);

    useEffect(() => { refreshStatus(); refreshBaseline(); }, [refreshStatus, refreshBaseline]);

    useEffect(() => {
      if (baseline?.status !== "running") return undefined;
      const timer = window.setInterval(refreshBaseline, 5000);
      return () => window.clearInterval(timer);
    }, [baseline?.status, refreshBaseline]);

    const run = useCallback(async (action) => {
      setRunning(action);
      setError("");
      setResult(null);
      try {
        const init = { method: "POST" };
        if (action === "audit" || action === "readiness") {
          const payload = { max_moves: Number(maxMoves) || 1000 };
          const selectedCompanyId = Number(companyId);
          if (Number.isInteger(selectedCompanyId) && selectedCompanyId > 0) payload.company_id = selectedCompanyId;
          if (action === "readiness") {
            payload.include_silver = Boolean(includeSilver);
            payload.download_attachments = Boolean(downloadAttachments);
            payload.max_attachment_mb = Math.min(100, Math.max(1, Number(maxAttachmentMb) || 25));
          }
          init.headers = { "Content-Type": "application/json" };
          init.body = JSON.stringify(payload);
        } else if (action === "evaluation/prepare") {
          const payload = {
            hydrate_source_content: Boolean(hydrateEvaluationSources),
            max_attachment_mb: Math.min(100, Math.max(1, Number(maxAttachmentMb) || 25)),
            holdout_fraction: Math.min(0.40, Math.max(0.10, Number(evaluationHoldoutFraction) || 0.20)),
            min_holdout: Math.min(1000, Math.max(20, Number(evaluationMinHoldout) || 100)),
            min_source_content_coverage: Math.min(1.0, Math.max(0.50, Number(evaluationMinContentCoverage) || 0.90)),
          };
          init.headers = { "Content-Type": "application/json" };
          init.body = JSON.stringify(payload);
        }
        const data = await SDK.fetchJSON(`${API_ROOT}/${action}`, init);
        setResult({ action, data });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setRunning("");
      }
    }, [companyId, downloadAttachments, evaluationHoldoutFraction, evaluationMinContentCoverage, evaluationMinHoldout, hydrateEvaluationSources, includeSilver, maxAttachmentMb, maxMoves]);

    const startBaseline = useCallback(async () => {
      setError("");
      try {
        const data = await SDK.fetchJSON(`${API_ROOT}/evaluation/baseline`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            timeout_seconds: Math.min(300, Math.max(15, Number(baselineTimeout) || 120)),
            max_tokens: Math.min(4096, Math.max(256, Number(baselineMaxTokens) || 1800)),
          }),
        });
        setBaseline(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, [baselineTimeout, baselineMaxTokens]);

    const audit = result?.action === "audit" ? result.data : null;
    const discovery = result?.action === "discover" ? result.data : null;
    const readiness = result?.action === "readiness" ? result.data : null;
    const evaluation = result?.action === "evaluation/prepare" ? result.data : null;
    const companies = Array.isArray(status?.companies) ? status.companies : [];
    const companySelectionRequired = Boolean(status?.company_selection_required);
    const auditScopeMissing = companySelectionRequired && !companyId;
    const baselineResult = baseline?.result;
    const score = baselineResult?.score_report;
    const aggregate = score?.aggregate;
    const productionGate = score?.production_gate;

    return h(
      "main",
      { className: "ab-page" },
      h("header", { className: "ab-hero" },
        h("div", { className: "ab-eyebrow" }, "HERMES // ACCOUNTING BRAIN"),
        h("h1", null, "Accounting Brain"),
        h("p", null, "Evidence-first learning from your real Odoo accounting history. Prove data quality, isolate a leakage-safe holdout, then evaluate the active model before any production accounting workflow."),
        h("div", { className: "ab-safety" },
          h("span", null, "READ ONLY"), h("span", null, "ONE COMPANY PER DATASET"), h("span", null, "NO AUTO-POST"), h("span", null, "NO TRAINING"), h("span", null, "DETERMINISTIC QUALITY GATES")),
      ),

      h(StatusCard, { status, loading: statusLoading, onRefresh: refreshStatus }),

      h("section", { className: "ab-grid" },
        h("article", { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 1"), h("h2", null, "Discover actual Odoo schema"),
          h("p", null, "Inspect the accounting models and fields that really exist in this Odoo instance."),
          h("button", { className: "ab-button", disabled: Boolean(running) || !status?.connected, onClick: () => run("discover") }, running === "discover" ? "Discovering…" : "Run schema discovery")),

        h("article", { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 2"), h("h2", null, "Audit historical posted journals"),
          h("p", null, "Grade one company's history as Gold, Silver or Rejected before any model work."),
          status?.connected ? h("label", { className: "ab-label" }, "Odoo company scope",
            h("select", { className: "ab-input", value: companyId, disabled: companies.length <= 1 || Boolean(running), onChange: event => setCompanyId(event.target.value) },
              companies.length > 1 ? h("option", { value: "" }, "Select one company") : null,
              ...companies.map(company => h("option", { key: company.id, value: String(company.id) }, `${company.name} (#${company.id})`))),
            companySelectionRequired ? h("span", { className: "ab-help" }, "Required: histories from different Odoo companies are never mixed.") : null) : null,
          h("label", { className: "ab-label" }, "Posted entries to sample", h("input", { className: "ab-input", type: "number", min: 1, max: 5000, step: 100, value: maxMoves, onChange: event => setMaxMoves(event.target.value) })),
          h("button", { className: "ab-button", disabled: Boolean(running) || !status?.connected || auditScopeMissing, onClick: () => run("audit") }, running === "audit" ? "Auditing…" : auditScopeMissing ? "Select company to audit" : "Audit posted journals")),

        h("article", { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 3 // SHORTEST LAUNCH PATH"), h("h2", null, "Build Golden Dataset + launch gate"),
          h("p", null, "Build a bounded private Golden Dataset from one company. This does not train a model or post to Odoo."),
          h("label", { className: "ab-label" }, h("input", { type: "checkbox", checked: includeSilver, disabled: Boolean(running), onChange: event => setIncludeSilver(event.target.checked) }), " Include Silver examples (review required)"),
          h("label", { className: "ab-label" }, h("input", { type: "checkbox", checked: downloadAttachments, disabled: Boolean(running), onChange: event => setDownloadAttachments(event.target.checked) }), " Download attachment bytes into the private Railway volume"),
          h("button", { className: "ab-button", disabled: Boolean(running) || !status?.connected || auditScopeMissing, onClick: () => run("readiness") }, running === "readiness" ? "Running launch gate…" : "Run launch readiness")),

        h("article", { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 4 // MODEL EVALUATION GATE"), h("h2", null, "Prepare leakage-safe evaluation evidence"),
          h("p", null, "Reserve the newest accounting history as temporal holdout, remove exact attachment duplicates, and separate source inputs from ground truth."),
          h("label", { className: "ab-label" }, h("input", { type: "checkbox", checked: hydrateEvaluationSources, disabled: Boolean(running), onChange: event => setHydrateEvaluationSources(event.target.checked) }), " Hydrate safe Gold source documents from Odoo"),
          h("label", { className: "ab-label" }, "Temporal holdout fraction", h("input", { className: "ab-input", type: "number", min: 0.10, max: 0.40, step: 0.05, value: evaluationHoldoutFraction, onChange: event => setEvaluationHoldoutFraction(event.target.value) })),
          h("label", { className: "ab-label" }, "Minimum holdout cases", h("input", { className: "ab-input", type: "number", min: 20, max: 1000, step: 10, value: evaluationMinHoldout, onChange: event => setEvaluationMinHoldout(event.target.value) })),
          h("label", { className: "ab-label" }, "Minimum source-content coverage", h("input", { className: "ab-input", type: "number", min: 0.50, max: 1.0, step: 0.05, value: evaluationMinContentCoverage, onChange: event => setEvaluationMinContentCoverage(event.target.value) })),
          h("button", { className: "ab-button", disabled: Boolean(running) || !status?.connected, onClick: () => run("evaluation/prepare") }, running === "evaluation/prepare" ? "Preparing evaluation evidence…" : "Prepare model evaluation gate")),

        h("article", { className: `ab-card ${baseline?.status === "failed" ? "ab-error" : baseline?.status === "completed" ? "ok" : ""}` },
          h("div", { className: "ab-eyebrow" }, "STEP 5 // BASELINE MODEL EVALUATION"),
          h("h2", null, "Run the active Hermes model on the fixed holdout"),
          h("p", null, "The model receives source documents only. Historical ground truth stays physically separate and is opened only afterward by deterministic scoring."),
          h("label", { className: "ab-label" }, "Per-case timeout (seconds)", h("input", { className: "ab-input", type: "number", min: 15, max: 300, value: baselineTimeout, disabled: baseline?.status === "running", onChange: event => setBaselineTimeout(event.target.value) })),
          h("label", { className: "ab-label" }, "Maximum output tokens per case", h("input", { className: "ab-input", type: "number", min: 256, max: 4096, step: 128, value: baselineMaxTokens, disabled: baseline?.status === "running", onChange: event => setBaselineMaxTokens(event.target.value) })),
          h("button", { className: "ab-button", disabled: baseline?.status === "running", onClick: startBaseline }, baseline?.status === "running" ? "Baseline evaluation running…" : "Run Baseline Model Evaluation"),
          h("button", { className: "ab-button secondary", disabled: baseline?.status === "running", onClick: refreshBaseline }, "Refresh baseline status"),
          h("p", { className: "ab-help" }, "This task runs in the dashboard process so it can safely access the same private Railway volume. Odoo writes, model training and auto-post remain disabled."),
          baseline ? h("div", { className: "ab-metrics" },
            h(Metric, { label: "Status", value: baseline.status }),
            h(Metric, { label: "Cases", value: baselineResult?.cases }),
            h(Metric, { label: "Provider", value: baselineResult?.providers?.join(", ") }),
            h(Metric, { label: "Model", value: baselineResult?.models?.join(", ") }),
            h(Metric, { label: "Total tokens", value: baselineResult?.usage?.total_tokens }),
            h(Metric, { label: "Cost USD", value: baselineResult?.usage?.cost_usd }),
            h(Metric, { label: "Strict pass rate", value: aggregate?.strict_pass_rate }),
            h(Metric, { label: "Production gate", value: productionGate?.stage }),
            h(Metric, { label: "Private report", value: baselineResult?.report_file })) : null),
      ),

      error ? h("section", { className: "ab-card ab-error", role: "alert" }, h("h2", null, "Operation failed"), h("p", null, error)) : null,
      baseline?.error ? h("section", { className: "ab-card ab-error", role: "alert" }, h("h2", null, "Baseline failed safely"), h("p", null, baseline.error)) : null,

      discovery ? h("section", { className: "ab-card" }, h("div", { className: "ab-eyebrow" }, "DISCOVERY RESULT"), h("h2", null, "Live Odoo schema map"), h("div", { className: "ab-metrics" }, h(Metric, { label: "Models requested", value: discovery.models_requested }), h(Metric, { label: "Available", value: discovery.models_available }), h(Metric, { label: "Private report", value: discovery.report_file })), h(JsonBlock, { value: discovery.available_models })) : null,
      audit ? h("section", { className: "ab-card" }, h("div", { className: "ab-eyebrow" }, "AUDIT RESULT"), h("h2", null, "Training-data readiness"), h("div", { className: "ab-metrics" }, h(Metric, { label: "Company", value: audit.selected_company?.name }), h(Metric, { label: "Gold rate", value: audit.quality?.gold_rate }), h(Metric, { label: "Attachment coverage", value: audit.quality?.attachment_coverage }), h(Metric, { label: "Private report", value: audit.report_file })), h(JsonBlock, { value: audit.quality })) : null,
      readiness ? h("section", { className: `ab-card ${readiness.ok ? "ok" : "ab-error"}` }, h("div", { className: "ab-eyebrow" }, "LAUNCH READINESS RESULT"), h("h2", null, readiness.stage), h("div", { className: "ab-metrics" }, h(Metric, { label: "Company", value: readiness.selected_company?.name }), h(Metric, { label: "Exported pairs", value: readiness.golden_dataset?.exported_pairs }), h(Metric, { label: "Next gate", value: readiness.next_gate }), h(Metric, { label: "Private report", value: readiness.report_file })), h(JsonBlock, { value: readiness.gates })) : null,
      evaluation ? h("section", { className: `ab-card ${evaluation.ok ? "ok" : "ab-error"}` }, h("div", { className: "ab-eyebrow" }, "MODEL EVALUATION READINESS"), h("h2", null, evaluation.stage), h("div", { className: "ab-metrics" }, h(Metric, { label: "Gold pairs", value: evaluation.gold_pairs }), h(Metric, { label: "Reference pool", value: evaluation.reference_pool_cases }), h(Metric, { label: "Temporal holdout", value: evaluation.holdout_cases }), h(Metric, { label: "Source content coverage", value: evaluation.gates?.source_content_coverage?.value }), h(Metric, { label: "Next action", value: evaluation.next_action }), h(Metric, { label: "Private report", value: evaluation.report_file })), h(JsonBlock, { value: evaluation.gates })) : null,

      baseline?.status === "completed" ? h("section", { className: `ab-card ${productionGate?.ok ? "ok" : "ab-error"}` },
        h("div", { className: "ab-eyebrow" }, "BASELINE MODEL EVALUATION RESULT"),
        h("h2", null, productionGate?.stage || score?.stage || "Baseline scored"),
        h("div", { className: "ab-metrics" },
          h(Metric, { label: "Cases completed", value: score?.evaluation_cases }),
          h(Metric, { label: "Strict pass rate", value: aggregate?.strict_pass_rate }),
          h(Metric, { label: "Production ready", value: productionGate?.ok ? "YES — DRAFT ONLY" : "NO" }),
          h(Metric, { label: "Auto-post", value: "OFF" }),
          h(Metric, { label: "Human review", value: "REQUIRED" })),
        h("h3", null, "Critical accounting rates"), h(JsonBlock, { value: aggregate?.critical_rates }),
        h("h3", null, "Secondary accounting rates"), h(JsonBlock, { value: aggregate?.secondary_rates }),
        h("h3", null, "Production gate"), h(JsonBlock, { value: productionGate }),
        h("h3", null, "Safety"), h(JsonBlock, { value: baseline?.safety })) : null,

      h("footer", { className: "ab-footer" }, "Production rule: Evidence → Deterministic Rules → AI Reasoning → Validation → Human Review. Model training and Odoo auto-post stay disabled until their own explicit gates pass."),
    );
  }

  REGISTRY.register("accounting_brain", AccountingBrainPage);
})();
