(function () {
  "use strict";

  const ENTRY_SCRIPT_URL = document.currentScript?.src || "";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const REGISTRY = window.__HERMES_PLUGINS__;

  if (!SDK || !REGISTRY) {
    console.error("[hermes-avatar] Hermes plugin SDK/registry is unavailable.");
    return;
  }

  const h = SDK.React.createElement;

  function DigitalHumanBootstrapPage() {
    return h(
      "main",
      {
        className: "dh2-page",
        role: "status",
        "aria-live": "polite",
        "aria-busy": "true",
      },
      h(
        "div",
        { className: "dh2-header" },
        h(
          "div",
          null,
          h("div", { className: "dh2-kicker" }, "HERMES // DIGITAL HUMAN"),
          h("h1", null, "Digital Human"),
          h("p", null, "Loading avatar, voice and behavior runtime..."),
        ),
      ),
    );
  }

  // Hermes validates registration in the first microtask after this entry
  // script finishes loading. Register a lightweight bootstrap synchronously;
  // avatar-v4.js replaces it with the full DigitalHumanPage once ready.
  REGISTRY.register("hermes-avatar", DigitalHumanBootstrapPage);

  function normalizeBasePath(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    const withLead = raw.startsWith("/") ? raw : `/${raw}`;
    return withLead.replace(/\/+$/, "");
  }

  function pluginAssetUrl(fileName) {
    if (ENTRY_SCRIPT_URL) {
      try {
        return new URL(fileName, ENTRY_SCRIPT_URL).toString();
      } catch {
        // Fall through to the server-injected dashboard base path.
      }
    }

    const basePath = normalizeBasePath(window.__HERMES_BASE_PATH__);
    return `${basePath}/dashboard-plugins/hermes-avatar/dist/${fileName}`;
  }

  const runtimeSrc = pluginAssetUrl("female-voice-entry.js");
  const existing = Array.from(document.scripts).find(script => script.src === runtimeSrc);
  if (existing) return;

  const script = document.createElement("script");
  script.src = runtimeSrc;
  script.async = true;
  script.setAttribute("data-hermes-avatar-runtime", "1");
  script.onerror = error => {
    console.error("[hermes-avatar] unable to load Digital Human runtime", error);
  };
  document.body.appendChild(script);
})();
