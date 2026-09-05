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

  function NumberField({ label, value, onChange, min, max, step }) {
    return h(
      "label",
      { className: "ab-label" },
      label,
      h("input", {
        className: "ab-input",
        type: "number",
        min,
        max,
        step,
        value,
        onChange: event => onChange(event.target.value),
      }),
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
        h(
          "div",
          null,
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
        : h(
            "p",
            { className: "ab-help" },
            "Configure ODOO_URL, ODOO_DB (or ODOO_DATABASE), ODOO_USERNAME and ODOO_API_KEY in Railway Variables. Credentials never enter this browser page.",
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
    const [companyId, setCompanyId] = useState("");
    const [includeSilver, setIncludeSilver] = useState(false);
    const [downloadAttachments, setDownloadAttachments] = useState(false);
    const [maxAttachmentMb, setMaxAttachmentMb] = useState(25);

    const [hydrateEvaluationSources, setHydrateEvaluationSources] = useState(false);
    const [evaluationHoldoutFraction, setEvaluationHoldoutFraction] = useState(0.20);
    const [evaluationMinHoldout, setEvaluationMinHoldout] = useState(100);
    const [evaluationMinContentCoverage, setEvaluationMinContentCoverage] = useState(0.90);

    const [baselineMaxCases, setBaselineMaxCases] = useState(10);
    const [baselineTopK, setBaselineTopK] = useState(3);
    const [baselineMinCoverage, setBaselineMinCoverage] = useState(0.90);

    const refreshStatus = useCallback(async () => {
      setStatusLoading(true);
      try {
        const data = await SDK.fetchJSON(`${API_ROOT}/status`);
        setStatus(data);
        const companies = Array.isArray(data?.companies) ? data.companies : [];
        setCompanyId(current => {
          if (companies.length === 1) return String(companies[0].id);
          return companies.some(company => String(company.id) === String(current))
            ? String(current)
            : "";
        });
      } catch (err) {
        setStatus({
          ok: false,
          configured: true,
          connected: false,
          companies: [],
          company_selection_required: false,
          message: err instanceof Error ? err.message : String(err),
        });
        setCompanyId("");
      } finally {
        setStatusLoading(false);
      }
    }, []);

    useEffect(() => {
      refreshStatus();
    }, [refreshStatus]);

    const run = useCallback(async action => {
      setRunning(action);
      setError("");
      setResult(null);
      try {
        const init = { method: "POST" };
        let payload = null;

        if (action === "audit" || action === "readiness") {
          payload = { max_moves: Number(maxMoves) || 1000 };
          const selectedCompanyId = Number(companyId);
          if (Number.isInteger(selectedCompanyId) && selectedCompanyId > 0) {
            payload.company_id = selectedCompanyId;
          }
          if (action === "readiness") {
            payload.include_silver = Boolean(includeSilver);
            payload.download_attachments = Boolean(downloadAttachments);
            payload.max_attachment_mb = Math.min(100, Math.max(1, Number(maxAttachmentMb) || 25));
          }
        } else if (action === "evaluation/prepare") {
          payload = {
            hydrate_source_content: Boolean(hydrateEvaluationSources),
            max_attachment_mb: Math.min(100, Math.max(1, Number(maxAttachmentMb) || 25)),
            holdout_fraction: Math.min(0.40, Math.max(0.10, Number(evaluationHoldoutFraction) || 0.20)),
            min_holdout: Math.min(1000, Math.max(20, Number(evaluationMinHoldout) || 100)),
            min_source_content_coverage: Math.min(1.0, Math.max(0.50, Number(evaluationMinContentCoverage) || 0.90)),
          };
        } else if (action === "evaluation/baseline") {
          payload = {
            max_cases: Math.min(500, Math.max(1, Number(baselineMaxCases) || 10)),
            top_k: Math.min(10, Math.max(1, Number(baselineTopK) || 3)),
            min_consumable_coverage: Math.min(1.0, Math.max(0.50, Number(baselineMinCoverage) || 0.90)),
          };
        }

        if (payload) {
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
    }, [
      baselineMaxCases,
      baselineMinCoverage,
      baselineTopK,
      companyId,
      downloadAttachments,
      evaluationHoldoutFraction,
      evaluationMinContentCoverage,
      evaluationMinHoldout,
      hydrateEvaluationSources,
      includeSilver,
      maxAttachmentMb,
      maxMoves,
    ]);

    const audit = result?.action === "audit" ? result.data : null;
    const discovery = result?.action === "discover" ? result.data : null;
    const readiness = result?.action === "readiness" ? result.data : null;
    const evaluation = result?.action === "evaluation/prepare" ? result.data : null;
    const baseline = result?.action === "evaluation/baseline" ? result.data : null;
    const companies = Array.isArray(status?.companies) ? status.companies : [];
    const companySelectionRequired = Boolean(status?.company_selection_required);
    const auditScopeMissing = companySelectionRequired && !companyId;

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
          "Evidence-first learning from your real Odoo accounting history. Prove source quality, reserve leakage-safe holdout evidence, benchmark the configured Hermes model, and only then decide whether training is justified.",
        ),
        h(
          "div",
          { className: "ab-safety" },
          h("span", null, "READ ONLY ODOO"),
          h("span", null, "ONE COMPANY PER DATASET"),
          h("span", null, "NO AUTO-POST"),
          h("span", null, "NO TARGET LEAKAGE"),
          h("span", null, "DETERMINISTIC SCORING"),
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
          h("p", null, "Grade one company's historical examples as Gold, Silver or Rejected and measure evidence coverage before any model training."),
          status?.connected
            ? h(
                "label",
                { className: "ab-label" },
                "Odoo company scope",
                h(
                  "select",
                  {
                    className: "ab-input",
                    value: companyId,
                    disabled: companies.length <= 1 || Boolean(running),
                    onChange: event => setCompanyId(event.target.value),
                  },
                  companies.length > 1 ? h("option", { value: "" }, "Select one company") : null,
                  ...companies.map(company =>
                    h("option", { key: company.id, value: String(company.id) }, `${company.name} (#${company.id})`),
                  ),
                ),
                companySelectionRequired
                  ? h("span", { className: "ab-help" }, "Required: histories from different Odoo companies are never mixed into one audit population.")
                  : h("span", { className: "ab-help" }, "Single accessible company selected automatically."),
              )
            : null,
          h(NumberField, {
            label: "Posted entries to sample",
            value: maxMoves,
            onChange: setMaxMoves,
            min: 1,
            max: 5000,
            step: 100,
          }),
          h(
            "button",
            {
              className: "ab-button",
              disabled: Boolean(running) || !status?.connected || auditScopeMissing,
              onClick: () => run("audit"),
            },
            running === "audit" ? "Auditing…" : auditScopeMissing ? "Select company to audit" : "Audit posted journals",
          ),
        ),

        h(
          "article",
          { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 3 // SHORTEST LAUNCH PATH"),
          h("h2", null, "Build Golden Dataset + launch gate"),
          h("p", null, "Run connection, schema discovery, single-company historical audit and Gold dataset export as one bounded read-only operation."),
          h(
            "label",
            { className: "ab-label" },
            h("input", {
              type: "checkbox",
              checked: includeSilver,
              disabled: Boolean(running),
              onChange: event => setIncludeSilver(event.target.checked),
            }),
            " Include Silver examples (review required)",
          ),
          h(
            "label",
            { className: "ab-label" },
            h("input", {
              type: "checkbox",
              checked: downloadAttachments,
              disabled: Boolean(running),
              onChange: event => setDownloadAttachments(event.target.checked),
            }),
            " Download attachment bytes into the private Railway volume",
          ),
          downloadAttachments
            ? h(NumberField, {
                label: "Maximum size per attachment (MiB)",
                value: maxAttachmentMb,
                onChange: setMaxAttachmentMb,
                min: 1,
                max: 100,
                step: 1,
              })
            : null,
          h("p", { className: "ab-help" }, "Recommended first run: Gold only, attachment metadata only. Source bytes are hydrated after the data audit passes."),
          h(
            "button",
            {
              className: "ab-button",
              disabled: Boolean(running) || !status?.connected || auditScopeMissing,
              onClick: () => run("readiness"),
            },
            running === "readiness" ? "Running launch gate…" : auditScopeMissing ? "Select company first" : "Run launch readiness",
          ),
        ),

        h(
          "article",
          { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 4 // MODEL EVALUATION GATE"),
          h("h2", null, "Prepare leakage-safe evaluation evidence"),
          h("p", null, "Use the newest Gold dataset, reserve the newest accounting history as a temporal holdout, remove exact attachment duplicates, and keep model inputs physically separate from historical ground truth."),
          h(
            "label",
            { className: "ab-label" },
            h("input", {
              type: "checkbox",
              checked: hydrateEvaluationSources,
              disabled: Boolean(running),
              onChange: event => setHydrateEvaluationSources(event.target.checked),
            }),
            " Hydrate safe Gold source documents from Odoo (PDF/images/Excel/Word/text only)",
          ),
          h(
            "div",
            { className: "ab-grid" },
            h(NumberField, {
              label: "Temporal holdout fraction",
              value: evaluationHoldoutFraction,
              onChange: setEvaluationHoldoutFraction,
              min: 0.10,
              max: 0.40,
              step: 0.05,
            }),
            h(NumberField, {
              label: "Minimum holdout cases",
              value: evaluationMinHoldout,
              onChange: setEvaluationMinHoldout,
              min: 20,
              max: 1000,
              step: 10,
            }),
          ),
          h(NumberField, {
            label: "Minimum source-content coverage",
            value: evaluationMinContentCoverage,
            onChange: setEvaluationMinContentCoverage,
            min: 0.50,
            max: 1.0,
            step: 0.05,
          }),
          h("p", { className: "ab-help" }, "Hydration is read-only against Odoo. The holdout target remains in a physically separate private file and is never supplied to the model."),
          h(
            "button",
            {
              className: "ab-button",
              disabled: Boolean(running) || !status?.connected,
              onClick: () => run("evaluation/prepare"),
            },
            running === "evaluation/prepare" ? "Preparing evaluation evidence…" : "Prepare model evaluation gate",
          ),
        ),

        h(
          "article",
          { className: "ab-card" },
          h("div", { className: "ab-eyebrow" }, "STEP 5 // BASELINE MODEL EVALUATION"),
          h("h2", null, "Benchmark Hermes before any training"),
          h(
            "p",
            null,
            "Run the currently configured Hermes inference model against a bounded sample of the temporal holdout. Source images use Hermes vision; retrieval uses only the older reference pool; deterministic code grades the answer afterward.",
          ),
          h(
            "div",
            { className: "ab-grid" },
            h(NumberField, {
              label: "Cases to evaluate (start with 10)",
              value: baselineMaxCases,
              onChange: setBaselineMaxCases,
              min: 1,
              max: 500,
              step: 1,
            }),
            h(NumberField, {
              label: "Historical analogues per case",
              value: baselineTopK,
              onChange: setBaselineTopK,
              min: 1,
              max: 10,
              step: 1,
            }),
          ),
          h(NumberField, {
            label: "Minimum model-consumable source coverage",
            value: baselineMinCoverage,
            onChange: setBaselineMinCoverage,
            min: 0.50,
            max: 1.0,
            step: 0.05,
          }),
          h(
            "p",
            { className: "ab-message" },
            "Cost notice: this button sends selected private source evidence to your configured Hermes inference/vision provider and may consume paid API credits. Nothing runs automatically. Start with 10 cases.",
          ),
          h(
            "p",
            { className: "ab-help" },
            "Safety: no tools, no memory, no context files, no Odoo writes, no training, no auto-post. Unsupported evidence remains in the scoring denominator so the benchmark cannot cherry-pick easy cases.",
          ),
          h(
            "button",
            {
              className: "ab-button",
              disabled: Boolean(running),
              onClick: () => run("evaluation/baseline"),
            },
            running === "evaluation/baseline"
              ? "Running baseline — this may take several minutes…"
              : `Run baseline smoke (${Math.max(1, Number(baselineMaxCases) || 10)} cases)`,
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
              h(Metric, { label: "Company", value: audit.selected_company?.name }),
              h(Metric, { label: "Company ID", value: audit.selected_company?.id }),
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

      readiness
        ? h(
            "section",
            { className: `ab-card ${readiness.ok ? "ok" : "ab-error"}` },
            h("div", { className: "ab-eyebrow" }, "LAUNCH READINESS RESULT"),
            h("h2", null, readiness.stage || "Launch readiness"),
            h(
              "div",
              { className: "ab-metrics" },
              h(Metric, { label: "Company", value: readiness.selected_company?.name }),
              h(Metric, { label: "Sampled posted entries", value: readiness.audit?.selection?.sampled_posted_moves }),
              h(Metric, { label: "Gold rate", value: readiness.audit?.quality?.gold_rate }),
              h(Metric, { label: "Attachment coverage", value: readiness.audit?.quality?.attachment_coverage }),
              h(Metric, { label: "Exported pairs", value: readiness.golden_dataset?.exported_pairs }),
              h(Metric, { label: "Skipped pairs", value: readiness.golden_dataset?.skipped_pairs }),
              h(Metric, { label: "Dataset type", value: readiness.golden_dataset?.dataset_kind }),
              h(Metric, { label: "Next gate", value: readiness.next_gate }),
              h(Metric, { label: "Private report", value: readiness.report_file }),
            ),
            h("h3", null, "Deterministic gates"),
            h(JsonBlock, { value: readiness.gates }),
            h("h3", null, "Golden Dataset summary"),
            h(JsonBlock, { value: readiness.golden_dataset }),
          )
        : null,

      evaluation
        ? h(
            "section",
            { className: `ab-card ${evaluation.ok ? "ok" : "ab-error"}` },
            h("div", { className: "ab-eyebrow" }, "MODEL EVALUATION READINESS"),
            h("h2", null, evaluation.stage || "Evaluation preparation"),
            h(
              "div",
              { className: "ab-metrics" },
              h(Metric, { label: "Gold pairs", value: evaluation.gold_pairs }),
              h(Metric, { label: "Reference pool", value: evaluation.reference_pool_cases }),
              h(Metric, { label: "Temporal holdout", value: evaluation.holdout_cases }),
              h(Metric, { label: "Source content coverage", value: evaluation.gates?.source_content_coverage?.value }),
              h(Metric, { label: "Duplicate exclusions", value: evaluation.duplicate_checksum_exclusions }),
              h(Metric, { label: "Next action", value: evaluation.next_action }),
              h(Metric, { label: "Private report", value: evaluation.report_file }),
            ),
            h("h3", null, "Evaluation gates"),
            h(JsonBlock, { value: evaluation.gates }),
            h("h3", null, "Leakage controls"),
            h(JsonBlock, { value: evaluation.leakage_controls }),
            h("h3", null, "Source hydration"),
            h(JsonBlock, { value: evaluation.hydration }),
          )
        : null,

      baseline
        ? h(
            "section",
            { className: `ab-card ${baseline.ok ? "ok" : "ab-error"}` },
            h("div", { className: "ab-eyebrow" }, "BASELINE MODEL RESULT"),
            h("h2", null, baseline.stage || "Baseline evaluation"),
            h(
              "div",
              { className: "ab-metrics" },
              h(Metric, { label: "Provider", value: baseline.model?.provider }),
              h(Metric, { label: "Model", value: baseline.model?.model }),
              h(Metric, { label: "Vision provider", value: baseline.model?.vision_provider }),
              h(Metric, { label: "Vision model", value: baseline.model?.vision_model }),
              h(Metric, { label: "Selected cases", value: baseline.selected_cases }),
              h(Metric, { label: "Holdout total", value: baseline.total_holdout_cases }),
              h(Metric, { label: "Reference pool", value: baseline.reference_pool_cases }),
              h(Metric, { label: "Consumable coverage", value: baseline.source_evidence?.consumable_coverage }),
              h(Metric, { label: "Predictions returned", value: baseline.inference?.prediction_successes }),
              h(Metric, { label: "Strict pass rate", value: baseline.scores?.strict_pass_rate }),
              h(Metric, { label: "Next action", value: baseline.next_action }),
              h(Metric, { label: "Private report", value: baseline.report_file }),
            ),
            h("h3", null, "Critical accounting metric rates"),
            h(JsonBlock, { value: baseline.scores?.critical_rates }),
            h("h3", null, "Secondary metric rates"),
            h(JsonBlock, { value: baseline.scores?.secondary_rates }),
            h("h3", null, "Source modality coverage"),
            h(JsonBlock, { value: baseline.source_evidence }),
            h("h3", null, "Leakage controls"),
            h(JsonBlock, { value: baseline.leakage_controls }),
            h("h3", null, "Safety"),
            h(JsonBlock, { value: baseline.safety }),
            h(
              "p",
              { className: "ab-help" },
              baseline.stage === "BASELINE_SMOKE_COMPLETE"
                ? "Smoke benchmark completed. Review the deterministic rates before increasing to the full temporal holdout. Training remains disabled."
                : baseline.stage === "BASELINE_FULL_COMPLETE"
                  ? "Full baseline completed. Human model-evaluation review is mandatory before any training decision."
                  : "The baseline gate is blocked. Fix model configuration or source modality coverage rather than accepting a partial benchmark.",
            ),
          )
        : null,

      h(
        "footer",
        { className: "ab-footer" },
        "Production rule: Evidence → Deterministic Rules → AI Reasoning → Validation → Human Review. Model training and Odoo auto-post remain disabled until their own explicit gates pass.",
      ),
    );
  }

  REGISTRY.register("accounting_brain", AccountingBrainPage);
})();
