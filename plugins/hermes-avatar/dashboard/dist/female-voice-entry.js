(function () {
  "use strict";

  const PATCH_FLAG = "__HERMES_FEMALE_VOICE_PATCHED__";

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
      .sort((left, right) => right.score - left.score)[0]?.voice || null;
  }

  function installFemaleVoicePatch() {
    if (!("speechSynthesis" in window) || window[PATCH_FLAG]) return;

    const synth = window.speechSynthesis;
    const nativeSpeak = synth.speak.bind(synth);

    try {
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
      window[PATCH_FLAG] = true;
    } catch (error) {
      console.warn("[hermes-avatar] browser does not allow speechSynthesis patching", error);
      return;
    }

    synth.getVoices();
    synth.addEventListener?.("voiceschanged", () => {
      synth.getVoices();
    });
  }

  // This sidecar owns only voice selection. Voice-call state, buttons, chat,
  // avatar loading and behavior loading remain owned by their React/runtime
  // composition layers. In particular, there is deliberately no DOM polling,
  // MutationObserver, querySelector loop, or document-wide mutation handler.
  installFemaleVoicePatch();
})();
