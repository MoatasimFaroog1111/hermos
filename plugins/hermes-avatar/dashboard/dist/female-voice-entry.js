(function () {
  "use strict";

  const ENTRY_SCRIPT_URL = document.currentScript?.src || "";
  const PATCH_FLAG = "__HERMES_FEMALE_VOICE_PATCHED__";
  const CALL_UX_FLAG = "__HERMES_VOICE_CALL_UX__";
  const CALL_AUTO_REPLY_FLAG = "__HERMES_VOICE_CALL_AUTO_REPLY__";
  const AVATAR_READY_FLAG = "__HERMES_AVATAR_ENTRY_LOADED__";

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
        // Fall through to the injected dashboard base path.
      }
    }

    const basePath = normalizeBasePath(window.__HERMES_BASE_PATH__);
    return `${basePath}/dashboard-plugins/hermes-avatar/dist/${fileName}`;
  }

  const AVATAR_ENTRY = pluginAssetUrl("avatar-v4.js");
  const HUMAN_BEHAVIOR_ENTRY = pluginAssetUrl("human-behavior-engine.js");
  const RENDERER_ENTRY = pluginAssetUrl("three-avatar-renderer.js");
  const REALISTIC_STYLE = pluginAssetUrl("realistic.css");

  // Legacy root-path examples retained for smoke-test/documentation compatibility:
  // /dashboard-plugins/hermes-avatar/dist/avatar-v4.js
  // /dashboard-plugins/hermes-avatar/dist/human-behavior-engine.js

  function normalize(value) {
    return String(value || "").trim().toLowerCase();
  }

  function isArabicText(text) {
    return /[\u0600-\u06ff]/.test(String(text || ""));
  }

  function voiceScore(voice, arabic) {
    if (!voice) return -Infinity;
    const name = normalize(voice.name);
    const lang = normalize(voice.lang);
    const targetPrefix = arabic ? "ar" : "en";
    let score = 0;

    if (lang.startsWith(targetPrefix)) score += 100;
    else if (arabic && /arabic|العربية/.test(name)) score += 70;
    else if (!arabic && /english/.test(name)) score += 45;
    else score -= 120;

    if (/natural|neural|online|premium|enhanced|studio|wavenet/.test(name)) score += 55;
    if (/google|microsoft|apple/.test(name)) score += 22;
    if (voice.localService === false) score += 8;

    if (/female|woman|zira|samantha|victoria|karen|moira|tessa|ava|aria|jenny|emma|sara|sarah|layla|leila|laila|salma|amira|noura|noora|maryam|mariam|hoda|huda|zeina|zaina|جنى|ليلى|سلمى|أميرة|اميرة|نورة|مريم/.test(name)) {
      score += 75;
    }

    if (/male|man|david|mark|daniel|george|james|hamed|majed|tarik|tariq|omar|ahmed|mohamed|محمد|حامد|ماجد|عمر|طارق/.test(name)) {
      score -= 85;
    }

    if (voice.default) score += 6;
    return score;
  }

  function chooseFemaleVoice(text) {
    if (!("speechSynthesis" in window)) return null;
    const arabic = isArabicText(text);
    const voices = window.speechSynthesis.getVoices() || [];
    if (!voices.length) return null;

    return voices
      .map(voice => ({ voice, score: voiceScore(voice, arabic) }))
      .sort((a, b) => b.score - a.score)[0]?.voice || null;
  }

  function installFemaleVoicePatch() {
    if (!("speechSynthesis" in window) || window[PATCH_FLAG]) return;
    window[PATCH_FLAG] = true;

    const synth = window.speechSynthesis;
    const nativeSpeak = synth.speak.bind(synth);

    synth.speak = function hermesFemaleSpeak(utterance) {
      try {
        const text = utterance?.text || "";
        const selected = chooseFemaleVoice(text);
        const arabic = isArabicText(text);

        if (selected) {
          utterance.voice = selected;
          utterance.lang = selected.lang || (arabic ? "ar-SA" : "en-US");
        } else if (!utterance.lang) {
          utterance.lang = arabic ? "ar-SA" : "en-US";
        }

        utterance.rate = arabic ? 0.94 : 0.97;
        utterance.pitch = 1.04;
        utterance.volume = 1;
      } catch (error) {
        console.warn("[hermes-avatar] female voice selection failed", error);
      }
      return nativeSpeak(utterance);
    };
  }

  function getComposerControls() {
    const composer = document.querySelector(".dh2-chat .dh2-composer__actions");
    if (!composer) return { composer: null, callButton: null, voiceButton: null };
    const iconButtons = Array.from(composer.querySelectorAll(".dh2-icon"));
    return {
      composer,
      callButton: iconButtons[0] || null,
      voiceButton: iconButtons[1] || null,
    };
  }

  function refreshVoiceCallButton() {
    const { callButton } = getComposerControls();
    if (!callButton) return;

    const live = callButton.classList.contains("is-live");
    callButton.classList.add("dh2-call");
    callButton.setAttribute("aria-label", live ? "End voice call" : "Start voice call with automatic spoken reply");
    callButton.setAttribute("title", live ? "End voice call" : "Start voice call — Hermes replies by voice automatically");

    const label = live ? "END CALL" : "VOICE CALL";
    if (callButton.textContent !== label) callButton.textContent = label;
  }

  function voiceOutputIsMuted(voiceButton) {
    if (!voiceButton) return false;
    return normalize(voiceButton.textContent) === "mute"
      || voiceButton.getAttribute("aria-pressed") === "false";
  }

  function installAutomaticVoiceReplyForCalls() {
    if (window[CALL_AUTO_REPLY_FLAG]) return;
    window[CALL_AUTO_REPLY_FLAG] = true;

    document.addEventListener("click", event => {
      const { callButton, voiceButton } = getComposerControls();
      if (!callButton || event.target !== callButton) return;
      if (callButton.dataset.hermesVoiceReplay === "1") {
        delete callButton.dataset.hermesVoiceReplay;
        return;
      }

      if (callButton.classList.contains("is-live")) return;

      if (voiceOutputIsMuted(voiceButton)) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        voiceButton.click();
        window.setTimeout(() => {
          const latest = getComposerControls().callButton;
          if (!latest || latest.disabled) return;
          latest.dataset.hermesVoiceReplay = "1";
          latest.click();
        }, 0);
      }
    }, true);
  }

  function installVoiceCallUX() {
    if (window[CALL_UX_FLAG]) return;
    window[CALL_UX_FLAG] = true;

    const observer = new MutationObserver(() => refreshVoiceCallButton());
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "disabled"],
    });
    refreshVoiceCallButton();
  }

  function ensureStylesheet(href) {
    const exists = Array.from(document.styleSheets || []).some(sheet => sheet.href === href)
      || Boolean(document.querySelector(`link[href="${href}"]`));
    if (exists) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.setAttribute("data-hermes-avatar-base-style", "1");
    document.head.appendChild(link);
  }

  function findScript(src) {
    return Array.from(document.scripts).find(script => script.src === src) || null;
  }

  function appendScript(src, ready, onLoad, onError) {
    if (ready()) {
      onLoad();
      return;
    }

    const existing = findScript(src);
    if (existing) {
      if (existing.dataset.hermesLoaded === "1") {
        if (ready()) onLoad();
        else onError(new Error(`Loaded script did not expose its runtime: ${src}`));
        return;
      }
      existing.addEventListener("load", onLoad, { once: true });
      existing.addEventListener("error", onError, { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => {
      script.dataset.hermesLoaded = "1";
      onLoad();
    };
    script.onerror = event => {
      script.dataset.hermesLoaded = "0";
      onError(event);
    };
    document.body.appendChild(script);
  }

  function loadAvatarEntry() {
    const startAvatar = () => {
      appendScript(
        AVATAR_ENTRY,
        () => Boolean(window[AVATAR_READY_FLAG]),
        () => {
          window[AVATAR_READY_FLAG] = true;
          refreshVoiceCallButton();
        },
        error => console.error("[hermes-avatar] unable to load avatar runtime", error),
      );
    };

    const startRenderer = () => {
      appendScript(
        RENDERER_ENTRY,
        () => Boolean(window.__HERMES_AVATAR_RENDERER__?.ThreeAvatarRenderer),
        startAvatar,
        error => {
          console.warn("[hermes-avatar] renderer preload failed; avatar runtime will retry", error);
          startAvatar();
        },
      );
    };

    ensureStylesheet(REALISTIC_STYLE);

    appendScript(
      HUMAN_BEHAVIOR_ENTRY,
      () => Boolean(window.__HERMES_HUMAN_BEHAVIOR__),
      startRenderer,
      error => {
        console.warn("[hermes-avatar] human behavior engine unavailable; continuing with base motion", error);
        startRenderer();
      },
    );
  }

  installFemaleVoicePatch();
  installVoiceCallUX();
  installAutomaticVoiceReplyForCalls();

  if ("speechSynthesis" in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener?.("voiceschanged", () => {
      window.speechSynthesis.getVoices();
    });
  }

  loadAvatarEntry();
})();
