(function () {
  "use strict";

  const ENTRY_SCRIPT_URL = document.currentScript?.src || "";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const REGISTRY = window.__HERMES_PLUGINS__;
  const SCRIPT_TIMEOUT_MS = 12000;
  const AVATAR_READY_FLAG = "__HERMES_AVATAR_ENTRY_LOADED__";

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
  // Keep that contract synchronous. The full avatar page is loaded directly by
  // this composition root so optional voice/behavior preloads can never leave
  // the user trapped on the bootstrap screen.
  REGISTRY.register("hermes-avatar", DigitalHumanBootstrapPage);

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
      let settled = false;
      let timer = null;

      const finish = () => {
        if (settled) return;
        settled = true;
        if (timer !== null) window.clearTimeout(timer);
        resolve();
      };

      const fail = error => {
        if (settled) return;
        settled = true;
        if (timer !== null) window.clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(`Unable to load ${src}`));
      };

      timer = window.setTimeout(() => {
        fail(new Error(`Timed out loading ${src} after ${SCRIPT_TIMEOUT_MS} ms`));
      }, SCRIPT_TIMEOUT_MS);

      const existing = Array.from(document.scripts).find(script => script.src === src);
      if (existing?.dataset?.hermesLoaded === "1"
        || existing?.readyState === "loaded"
        || existing?.readyState === "complete") {
        finish();
        return;
      }
      if (existing) {
        existing.addEventListener("load", finish, { once: true });
        existing.addEventListener("error", fail, { once: true });
        return;
      }

      const script = document.createElement("script");
      script.src = src;
      script.async = false;
      script.onload = () => {
        script.dataset.hermesLoaded = "1";
        finish();
      };
      script.onerror = () => {
        script.dataset.hermesLoaded = "0";
        fail(new Error(`Unable to load ${src}`));
      };
      document.body.appendChild(script);
    });
  }

  const policyEntry = assetUrl("deterministic-avatar-policy.js");
  const voiceEntry = assetUrl("female-voice-entry.js");
  const avatarEntry = assetUrl("avatar-v4.js");

  loadScript(policyEntry)
    .catch(error => {
      // Deterministic policy is optional at bootstrap time. The avatar must
      // remain usable even if this enhancement fails to load.
      console.error("[hermes-avatar] deterministic animation policy failed", error);
    })
    .then(() => loadScript(voiceEntry).catch(error => {
      // Voice is also fail-open. Text/avatar interaction must not be blocked by
      // browser voice support or a transient sidecar loading failure.
      console.error("[hermes-avatar] female voice runtime failed", error);
    }))
    .then(() => loadScript(avatarEntry))
    .then(() => {
      // female-voice-entry uses this flag to avoid a second avatar bootstrap.
      window[AVATAR_READY_FLAG] = true;
    })
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
