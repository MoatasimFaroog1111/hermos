(function () {
  "use strict";

  const AVATAR_ENTRY = "/dashboard-plugins/hermes-avatar/dist/avatar-v4.js";
  const PATCH_FLAG = "__HERMES_FEMALE_VOICE_PATCHED__";
  const CALL_UX_FLAG = "__HERMES_VOICE_CALL_UX__";

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

  function refreshVoiceCallButton() {
    const composer = document.querySelector(".dh2-chat .dh2-composer__actions");
    const button = composer?.querySelector(".dh2-icon:first-child");
    if (!button) return;

    const live = button.classList.contains("is-live");
    button.classList.add("dh2-call");
    button.setAttribute("aria-label", live ? "End voice call" : "Start voice call");
    button.setAttribute("title", live ? "End voice call" : "Start voice call");

    const label = live ? "END CALL" : "VOICE CALL";
    if (button.textContent !== label) button.textContent = label;
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

  function loadAvatarEntry() {
    if (document.querySelector(`script[src^="${AVATAR_ENTRY}"]`)) return;
    const script = document.createElement("script");
    script.src = AVATAR_ENTRY;
    script.async = true;
    script.onload = refreshVoiceCallButton;
    script.onerror = () => console.error("[hermes-avatar] unable to load avatar runtime");
    document.body.appendChild(script);
  }

  installFemaleVoicePatch();
  installVoiceCallUX();

  if ("speechSynthesis" in window) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener?.("voiceschanged", () => {
      window.speechSynthesis.getVoices();
    });
  }

  loadAvatarEntry();
})();
