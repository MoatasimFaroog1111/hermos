(() => {
  "use strict";

  const ID = "hermes-voice-chat";
  const LANG = "ar-SA";
  const NativeWebSocket = window.WebSocket;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  const state = {
    enabled: false,
    listening: false,
    waiting: false,
    speaking: false,
    pty: null,
    recognition: null,
    transcript: "",
    answer: "",
    restartTimer: 0,
  };

  function trackSocket(ws, rawUrl) {
    const url = String(rawUrl || "");
    if (url.includes("/api/pty")) {
      ws.addEventListener("open", () => {
        state.pty = ws;
        if (state.enabled) scheduleListen(250);
      });
      ws.addEventListener("close", () => {
        if (state.pty === ws) state.pty = null;
        if (state.enabled) status("disconnected", "انقطع اتصال المحادثة");
      });
    } else if (url.includes("/api/events")) {
      ws.addEventListener("message", handleEvent);
    }
  }

  function VoiceWebSocket(url, protocols) {
    const ws = protocols === undefined
      ? new NativeWebSocket(url)
      : new NativeWebSocket(url, protocols);
    trackSocket(ws, url);
    return ws;
  }
  VoiceWebSocket.prototype = NativeWebSocket.prototype;
  Object.setPrototypeOf(VoiceWebSocket, NativeWebSocket);
  window.WebSocket = VoiceWebSocket;

  function handleEvent(event) {
    if (typeof event.data !== "string") return;
    let frame;
    try { frame = JSON.parse(event.data); } catch { return; }
    if (frame?.method !== "event") return;
    const type = frame.params?.type;
    const payload = frame.params?.payload || {};

    if (type === "message.start") {
      state.answer = "";
      state.waiting = true;
      if (state.enabled) status("thinking", "يفكر في ردك…");
    } else if (type === "message.delta" && typeof payload.text === "string") {
      state.answer += payload.text;
    } else if (type === "message.complete") {
      const text = [payload.text, payload.rendered, state.answer]
        .find((value) => typeof value === "string" && value.trim()) || "";
      state.answer = "";
      state.waiting = false;
      if (!state.enabled) return;
      if (text.trim()) void speak(text);
      else scheduleListen(400);
    } else if (state.enabled && [
      "tool.start", "tool.progress", "reasoning.delta", "thinking.delta", "moa.aggregating"
    ].includes(type)) {
      status("thinking", "يعمل على الإجابة…");
    }
  }

  function mount() {
    const host = document.querySelector(".hermes-chat-xterm-host");
    if (!host?.parentElement) return;
    if (!document.getElementById(`${ID}-style`)) {
      const style = document.createElement("style");
      style.id = `${ID}-style`;
      style.textContent = `
        #${ID}{direction:rtl;display:flex;align-items:center;justify-content:space-between;gap:.45rem;margin:0 0 .5rem;padding:.38rem .45rem;border:1px solid rgba(240,230,210,.25);border-radius:.6rem;background:rgba(8,18,17,.95);color:#f0e6d2;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 4px 18px #0005}
        #${ID} .hv-actions{display:flex;align-items:center;gap:.4rem;flex-shrink:0}
        #${ID} button{appearance:none;min-height:2.15rem;border:1px solid rgba(240,230,210,.3);border-radius:.5rem;background:#ffffff0e;color:inherit;padding:.35rem .6rem;font:inherit;cursor:pointer;-webkit-tap-highlight-color:transparent}
        #${ID} button:active{transform:translateY(1px)}
        #${ID} .hv-main{display:inline-flex;align-items:center;gap:.4rem;font-weight:700;white-space:nowrap}
        #${ID} .hv-stop{display:none} #${ID}[data-enabled="true"] .hv-stop{display:inline-flex}
        #${ID} .hv-status{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:.78rem;color:#f0e6d2c7}
        #${ID}[data-state="listening"]{border-color:#5eead4aa} #${ID}[data-state="listening"] .hv-icon{animation:hvPulse 1.1s infinite}
        #${ID}[data-state="speaking"]{border-color:#facc1599} #${ID}[data-state="error"],#${ID}[data-state="disconnected"]{border-color:#f87171aa}
        @keyframes hvPulse{50%{transform:scale(1.2);opacity:.65}}
        @media(max-width:520px){#${ID}{padding:.32rem;gap:.3rem}#${ID} button{padding:.32rem .45rem}#${ID} .hv-status{font-size:.7rem}}
      `;
      document.head.appendChild(style);
    }

    let bar = document.getElementById(ID);
    if (!bar) {
      bar = document.createElement("div");
      bar.id = ID;
      bar.dataset.enabled = "false";
      bar.dataset.state = "off";
      bar.innerHTML = `
        <div class="hv-actions">
          <button type="button" class="hv-main" aria-label="بدء المحادثة الصوتية"><span class="hv-icon">🎙️</span><span class="hv-label">ابدأ الحوار الصوتي</span></button>
          <button type="button" class="hv-stop" aria-label="إيقاف المحادثة الصوتية">إيقاف</button>
        </div>
        <div class="hv-status">تحدث إليه واسمع الرد</div>`;
      bar.querySelector(".hv-main").addEventListener("click", mainAction);
      bar.querySelector(".hv-stop").addEventListener("click", stopVoice);
    }
    if (bar.parentElement !== host.parentElement) host.parentElement.insertBefore(bar, host);
  }

  function status(kind, text) {
    mount();
    const bar = document.getElementById(ID);
    if (!bar) return;
    bar.dataset.enabled = String(state.enabled);
    bar.dataset.state = kind;
    bar.querySelector(".hv-status").textContent = text;
    const label = bar.querySelector(".hv-label");
    const icon = bar.querySelector(".hv-icon");
    if (kind === "listening") { label.textContent = "أستمع إليك…"; icon.textContent = "🎙️"; }
    else if (kind === "thinking") { label.textContent = "يفكر…"; icon.textContent = "💭"; }
    else if (kind === "speaking") { label.textContent = "يتحدث — اضغط للمقاطعة"; icon.textContent = "🔊"; }
    else if (state.enabled) { label.textContent = "استئناف الاستماع"; icon.textContent = "🎙️"; }
    else { label.textContent = "ابدأ الحوار الصوتي"; icon.textContent = "🎙️"; }
  }

  function mainAction() {
    if (!state.enabled) void startVoice();
    else if (state.speaking) interruptAndListen();
    else if (!state.listening && !state.waiting) startListening();
    else stopVoice();
  }

  async function startVoice() {
    if (!Recognition) {
      status("error", "متصفحك لا يدعم التعرف الصوتي؛ استخدم Chrome أو Edge الحديث");
      return;
    }
    if (!state.pty || state.pty.readyState !== NativeWebSocket.OPEN) {
      status("disconnected", "انتظر اتصال المحادثة ثم حاول مجددًا");
      return;
    }
    state.enabled = true;
    state.waiting = false;
    cancelSpeech();
    status("idle", "سيطلب المتصفح إذن الميكروفون");
    startListening();
  }

  function stopVoice() {
    state.enabled = false;
    state.waiting = false;
    state.transcript = "";
    clearTimeout(state.restartTimer);
    stopListening();
    cancelSpeech();
    status("off", "تحدث إليه واسمع الرد");
  }

  function getRecognition() {
    if (state.recognition) return state.recognition;
    const recognition = new Recognition();
    recognition.lang = LANG;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      state.listening = true;
      state.transcript = "";
      status("listening", "تكلم الآن؛ سأتوقف تلقائيًا عند انتهاء كلامك");
    };
    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result?.[0]?.transcript || "";
        if (result.isFinal) state.transcript += `${text} `;
        else interim += text;
      }
      const preview = (state.transcript || interim).trim();
      if (preview) status("listening", `سمعت: ${shorten(preview, 72)}`);
    };
    recognition.onerror = (event) => {
      state.listening = false;
      if (event.error === "aborted") return;
      if (["not-allowed", "service-not-allowed"].includes(event.error)) {
        state.enabled = false;
        status("error", "اسمح للموقع باستخدام الميكروفون ثم حاول مجددًا");
      } else if (event.error === "no-speech") {
        status("idle", "لم أسمع كلامًا؛ سأحاول مرة أخرى");
        scheduleListen(700);
      } else {
        status("error", `تعذر التعرف على الصوت: ${event.error || "خطأ غير معروف"}`);
        scheduleListen(1200);
      }
    };
    recognition.onend = () => {
      state.listening = false;
      const text = state.transcript.trim();
      state.transcript = "";
      if (!state.enabled) return;
      if (text) sendPrompt(text);
      else if (!state.waiting && !state.speaking) scheduleListen(500);
    };
    state.recognition = recognition;
    return recognition;
  }

  function startListening() {
    if (!state.enabled || state.waiting || state.speaking || state.listening) return;
    if (!state.pty || state.pty.readyState !== NativeWebSocket.OPEN) {
      status("disconnected", "اتصال المحادثة غير جاهز");
      return;
    }
    try { getRecognition().start(); }
    catch (error) {
      if (error?.name !== "InvalidStateError") status("error", "تعذر تشغيل الميكروفون");
    }
  }

  function stopListening() {
    if (!state.recognition || !state.listening) return;
    try { state.recognition.abort(); } catch { /* best effort */ }
    state.listening = false;
  }

  function scheduleListen(delay) {
    clearTimeout(state.restartTimer);
    state.restartTimer = window.setTimeout(() => {
      if (state.enabled && !state.waiting && !state.speaking) startListening();
    }, delay);
  }

  function sendPrompt(text) {
    const prompt = text.trim();
    const ws = state.pty;
    if (!prompt || !ws || ws.readyState !== NativeWebSocket.OPEN) {
      status("disconnected", "تعذر إرسال كلامك لأن المحادثة غير متصلة");
      return;
    }
    state.answer = "";
    state.waiting = true;
    status("thinking", `أرسلت: ${shorten(prompt, 72)}`);
    ws.send(prompt);
    window.setTimeout(() => {
      if (ws.readyState === NativeWebSocket.OPEN) ws.send("\r");
    }, 100);
  }

  async function speak(raw) {
    const text = clean(raw);
    if (!text) { scheduleListen(350); return; }
    stopListening();
    state.speaking = true;
    status("speaking", "أقرأ لك الرد الآن؛ اضغط الزر لمقاطعتي");
    await speakChunks(text);
    state.speaking = false;
    if (state.enabled) {
      status("idle", "انتهى الرد؛ سأستمع إليك مجددًا");
      scheduleListen(400);
    }
  }

  function speakChunks(text) {
    return new Promise((resolve) => {
      if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
        status("error", "هذا الجهاز لا يدعم تشغيل الرد الصوتي");
        resolve();
        return;
      }
      const synth = window.speechSynthesis;
      synth.cancel();
      const parts = split(text, 220);
      let index = 0;
      const next = () => {
        if (!state.enabled || !state.speaking || index >= parts.length) { resolve(); return; }
        const utterance = new SpeechSynthesisUtterance(parts[index++]);
        utterance.lang = LANG;
        utterance.rate = .94;
        utterance.pitch = 1;
        const voice = chooseVoice(synth.getVoices());
        if (voice) utterance.voice = voice;
        utterance.onend = next;
        utterance.onerror = next;
        synth.speak(utterance);
      };
      next();
    });
  }

  function chooseVoice(voices) {
    const arabic = voices.filter((voice) => /^ar(?:-|$)/i.test(voice.lang || ""));
    return arabic.find((voice) => /ar-sa|saudi|natural|premium|google|microsoft/i.test(`${voice.lang} ${voice.name}`)) || arabic[0] || null;
  }

  function interruptAndListen() {
    cancelSpeech();
    state.waiting = false;
    if (state.enabled) startListening();
  }

  function cancelSpeech() {
    state.speaking = false;
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  function clean(text) {
    return String(text || "")
      .replace(/```[\s\S]*?```/g, " يوجد مقطع برمجي. ")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/https?:\/\/\S+/g, "")
      .replace(/^\s{0,3}#{1,6}\s+/gm, "")
      .replace(/^\s*[-*+>]\s*/gm, "")
      .replace(/[|*_~]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 8000);
  }

  function split(text, max) {
    const sentences = text.match(/[^.!?؟؛。]+[.!?؟؛。]?/g) || [text];
    const out = [];
    let current = "";
    for (const sentence of sentences) {
      const next = `${current} ${sentence}`.trim();
      if (next.length <= max) current = next;
      else {
        if (current) out.push(current);
        if (sentence.length <= max) current = sentence.trim();
        else {
          for (let i = 0; i < sentence.length; i += max) out.push(sentence.slice(i, i + max).trim());
          current = "";
        }
      }
    }
    if (current) out.push(current);
    return out.filter(Boolean);
  }

  function shorten(text, max) {
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  }

  new MutationObserver(mount).observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, { once: true });
  else mount();
})();
