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
        "header",
        { className: "dh2-header" },
        h(
          "div",
          null,
          h("div", { className: "dh2-kicker" }, "HERMES // DIGITAL HUMAN"),
          h("h1", null, "Digital Human"),
          h("p", null, "Loading deterministic avatar, voice and behavior runtime..."),
        ),
      ),
    );
  }

  // The host validates registration immediately after the entry script loads.
  // Keep that contract synchronous; the base entry will replace this bootstrap
  // page after the policy layer has been installed.
  REGISTRY.register("hermes-avatar", DigitalHumanBootstrapPage);

  function isDigitalHumanPath(pathname) {
    return String(pathname || "").replace(/\/+$/, "").endsWith("/digital-human");
  }

  function installNavigationFallback() {
    // React Router owns normal navigation. This watchdog is intentionally
    // passive: it only performs a same-origin hard navigation when a click on
    // the Digital Human sidebar link failed to change the browser path. That
    // makes the plugin recover from stale/mismatched SPA route tables without
    // interfering with healthy client-side navigation.
    document.addEventListener("click", event => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const element = event.target instanceof Element ? event.target : null;
      const anchor = element?.closest?.("a[href]");
      if (!anchor) return;

      let targetUrl;
      try {
        targetUrl = new URL(anchor.href, window.location.href);
      } catch {
        return;
      }
      if (targetUrl.origin !== window.location.origin) return;
      if (!isDigitalHumanPath(targetUrl.pathname)) return;

      window.setTimeout(() => {
        if (!isDigitalHumanPath(window.location.pathname)) {
          console.warn("[hermes-avatar] SPA navigation did not open Digital Human; using same-origin fallback navigation.");
          window.location.assign(targetUrl.toString());
        }
      }, 250);
    });
  }

  installNavigationFallback();

  function assetUrl(fileName) {
    if (ENTRY_SCRIPT_URL) {
      try {
        const entry = new URL(ENTRY_SCRIPT_URL, window.location.href);
        const resolved = new URL(fileName, entry);
        // Keep the host-provided manifest-version/cache-epoch query on every
        // nested runtime asset so the entry and its dependencies are atomic.
        if (entry.search) resolved.search = entry.search;
        return resolved.toString();
      } catch {
        // Fall through to the dashboard base path.
      }
    }
    const raw = String(window.__HERMES_BASE_PATH__ || "").trim();
    const base = raw ? `/${raw.replace(/^\/+|\/+$/g, "")}` : "";
    return `${base}/dashboard-plugins/hermes-avatar/dist/${fileName}`;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = Array.from(document.scripts).find(script => script.src === src);
      if (existing?.dataset?.hermesLoaded === "1") {
        resolve();
        return;
      }
      if (existing) {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener("error", () => reject(new Error(`Unable to load ${src}`)), { once: true });
        return;
      }

      const script = document.createElement("script");
      script.src = src;
      script.async = false;
      script.onload = () => {
        script.dataset.hermesLoaded = "1";
        resolve();
      };
      script.onerror = () => reject(new Error(`Unable to load ${src}`));
      document.body.appendChild(script);
    });
  }

  const policyEntry = assetUrl("deterministic-avatar-policy.js");
  const baseEntry = assetUrl("female-voice-entry.js");

  loadScript(policyEntry)
    .catch(error => {
      // The policy layer is fail-open so the existing Digital Human remains
      // usable. The error is visible in diagnostics and never silently changes
      // animation selection behavior.
      console.error("[hermes-avatar] deterministic animation policy failed", error);
    })
    .then(() => loadScript(baseEntry))
    .catch(error => {
      console.error("[hermes-avatar] base Digital Human entry failed", error);
      const message = error instanceof Error ? error.message : String(error || "Unknown error");
      function DigitalHumanEntryErrorPage() {
        return h(
          "main",
          { className: "dh2-page", role: "alert", "aria-live": "assertive" },
          h(
            "header",
            { className: "dh2-header" },
            h("div", null,
              h("div", { className: "dh2-kicker" }, "HERMES // DIGITAL HUMAN"),
              h("h1", null, "Digital Human"),
              h("p", null, "The Digital Human entry runtime could not be started."),
              h("p", { className: "dh2-error" }, message),
              h("button", {
                type: "button",
                className: "dh2-button",
                onClick: () => window.location.reload(),
              }, "RETRY DIGITAL HUMAN"),
            ),
          ),
        );
      }
      REGISTRY.register("hermes-avatar", DigitalHumanEntryErrorPage);
    });
})();
