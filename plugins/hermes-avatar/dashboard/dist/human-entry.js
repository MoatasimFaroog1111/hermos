(function () {
  "use strict";

  const BEHAVIOR_ENTRY = "/dashboard-plugins/hermes-avatar/dist/human-behavior-engine.js";
  const VOICE_ENTRY = "/dashboard-plugins/hermes-avatar/dist/female-voice-entry.js";
  const LOAD_FLAG = "__HERMES_HUMAN_ENTRY_LOADED__";

  if (window[LOAD_FLAG]) return;
  window[LOAD_FLAG] = true;

  function hasScript(path) {
    return Boolean(document.querySelector(`script[src^="${path}"]`));
  }

  function loadScript(path) {
    if (hasScript(path)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = path;
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`Unable to load ${path}`));
      document.body.appendChild(script);
    });
  }

  async function boot() {
    try {
      await loadScript(BEHAVIOR_ENTRY);
    } catch (error) {
      console.warn("[hermes-avatar] human behavior engine unavailable; continuing with base motion", error);
    }

    try {
      await loadScript(VOICE_ENTRY);
    } catch (error) {
      console.error("[hermes-avatar] unable to load voice/avatar entry", error);
    }
  }

  boot();
})();
