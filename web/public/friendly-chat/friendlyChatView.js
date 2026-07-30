import { ConnectionState } from "./contracts.js";

const QUICK_PROMPTS = [
  "لخّص لي ما تستطيع فعله",
  "افحص المشروع الحالي واقترح التحسينات",
  "أنشئ خطة عمل واضحة للمهمة التالية",
];

/** Presentation layer. It knows DOM only and delegates every use case. */
export class FriendlyChatView {
  #host;
  #service;
  #root;
  #elements = {};
  #unsubscribe = null;
  #latestAssistantId = null;
  #voiceEnabled = false;
  #recognition = null;

  constructor({ host, service }) {
    this.#host = host;
    this.#service = service;
    this.#root = document.createElement("section");
    this.#root.id = "hermes-friendly-chat";
    this.#root.setAttribute("dir", "rtl");
    this.#root.innerHTML = template();
  }

  mount() {
    const wrapper = this.#host.parentElement;
    if (!wrapper) throw new Error("لم يتم العثور على حاوية محادثة Hermes");

    wrapper.prepend(this.#root);
    wrapper.classList.add("friendly-chat-active");
    this.#cacheElements();
    this.#bindActions(wrapper);
    this.#unsubscribe = this.#service.subscribe((state) => this.render(state));
  }

  dispose() {
    this.#unsubscribe?.();
    this.#recognition?.abort?.();
    this.#root.remove();
  }

  render(state) {
    const status = connectionPresentation(state.connection);
    this.#elements.statusText.textContent = status.text;
    this.#elements.statusDot.dataset.state = status.state;
    this.#elements.activity.textContent = state.activity || "جاهز لاستقبال رسالتك";
    this.#elements.error.hidden = !state.error;
    this.#elements.errorText.textContent = state.error || "";
    this.#elements.reconnect.hidden = state.connection === ConnectionState.OPEN;
    this.#elements.send.disabled = state.busy || !state.sessionId;
    this.#elements.stop.hidden = !state.busy;
    this.#elements.newChat.disabled = state.connection !== ConnectionState.OPEN;
    this.#elements.suggestions.hidden = state.messages.length > 0;
    this.#renderMessages(state.messages);

    const lastAssistant = [...state.messages].reverse().find((item) => item.role === "assistant");
    if (
      this.#voiceEnabled &&
      lastAssistant &&
      !lastAssistant.streaming &&
      lastAssistant.content &&
      lastAssistant.id !== this.#latestAssistantId
    ) {
      this.#latestAssistantId = lastAssistant.id;
      speakArabic(lastAssistant.content);
    }
  }

  #cacheElements() {
    const byRole = (role) => this.#root.querySelector(`[data-role="${role}"]`);
    this.#elements = {
      shell: byRole("shell"),
      returnButton: byRole("return-simple"),
      messages: byRole("messages"),
      suggestions: byRole("suggestions"),
      composer: byRole("composer"),
      send: byRole("send"),
      stop: byRole("stop"),
      newChat: byRole("new-chat"),
      advanced: byRole("advanced"),
      mic: byRole("mic"),
      voice: byRole("voice"),
      activity: byRole("activity"),
      statusText: byRole("status-text"),
      statusDot: byRole("status-dot"),
      error: byRole("error"),
      errorText: byRole("error-text"),
      reconnect: byRole("reconnect"),
    };
  }

  #bindActions(wrapper) {
    const sendCurrent = async () => {
      const text = this.#elements.composer.value;
      if (!(await this.#service.send(text))) return;
      this.#elements.composer.value = "";
      resizeComposer(this.#elements.composer);
    };

    this.#elements.send.addEventListener("click", sendCurrent);
    this.#elements.composer.addEventListener("input", () =>
      resizeComposer(this.#elements.composer),
    );
    this.#elements.composer.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        void sendCurrent();
      }
    });
    this.#elements.newChat.addEventListener("click", () => this.#service.newConversation());
    this.#elements.stop.addEventListener("click", () => this.#service.interrupt());
    this.#elements.reconnect.addEventListener("click", () => this.#service.reconnect());

    this.#elements.advanced.addEventListener("click", () => {
      wrapper.classList.remove("friendly-chat-active");
      wrapper.classList.add("friendly-chat-advanced");
      this.#root.dataset.mode = "advanced";
    });
    this.#elements.returnButton.addEventListener("click", () => {
      wrapper.classList.remove("friendly-chat-advanced");
      wrapper.classList.add("friendly-chat-active");
      this.#root.dataset.mode = "simple";
      window.setTimeout(() => this.#elements.composer.focus(), 0);
    });

    this.#elements.voice.addEventListener("click", () => {
      this.#voiceEnabled = !this.#voiceEnabled;
      this.#elements.voice.dataset.enabled = String(this.#voiceEnabled);
      this.#elements.voice.setAttribute("aria-pressed", String(this.#voiceEnabled));
      this.#elements.voice.title = this.#voiceEnabled
        ? "إيقاف قراءة الردود صوتيًا"
        : "قراءة الردود صوتيًا";
      if (!this.#voiceEnabled) window.speechSynthesis?.cancel?.();
    });

    this.#elements.mic.addEventListener("click", () => this.#toggleMicrophone(sendCurrent));

    for (const button of this.#root.querySelectorAll("[data-prompt]")) {
      button.addEventListener("click", () => {
        this.#elements.composer.value = button.dataset.prompt || "";
        resizeComposer(this.#elements.composer);
        this.#elements.composer.focus();
      });
    }
  }

  #renderMessages(messages) {
    const html = messages
      .map((item) => {
        const direction = containsArabic(item.content) ? "rtl" : "ltr";
        const body = renderText(item.content || (item.streaming ? "…" : ""));
        return `
          <article class="hf-message hf-${item.role}" dir="${direction}">
            <div class="hf-avatar" aria-hidden="true">${item.role === "user" ? "أنت" : item.role === "notice" ? "!" : "H"}</div>
            <div class="hf-bubble">
              <div class="hf-message-label">${item.role === "user" ? "أنت" : item.role === "notice" ? "تنبيه" : "Hermes"}</div>
              <div class="hf-message-body">${body}</div>
              ${item.streaming ? '<span class="hf-streaming" aria-label="جارٍ الكتابة"><i></i><i></i><i></i></span>' : ""}
            </div>
          </article>`;
      })
      .join("");

    this.#elements.messages.innerHTML = html;
    window.requestAnimationFrame(() => {
      this.#elements.messages.scrollTop = this.#elements.messages.scrollHeight;
    });
  }

  #toggleMicrophone(sendCurrent) {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      this.#elements.error.hidden = false;
      this.#elements.errorText.textContent =
        "التعرف الصوتي غير مدعوم في هذا المتصفح. استخدم Chrome أو Edge.";
      return;
    }

    if (this.#recognition) {
      this.#recognition.abort();
      this.#recognition = null;
      this.#elements.mic.dataset.listening = "false";
      return;
    }

    const recognition = new Recognition();
    this.#recognition = recognition;
    recognition.lang = "ar-SA";
    recognition.interimResults = true;
    recognition.continuous = false;

    recognition.onstart = () => {
      this.#elements.mic.dataset.listening = "true";
      this.#elements.activity.textContent = "أستمع إليك…";
    };
    recognition.onresult = (event) => {
      let transcript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        transcript += event.results[index]?.[0]?.transcript || "";
      }
      this.#elements.composer.value = transcript.trim();
      resizeComposer(this.#elements.composer);
    };
    recognition.onerror = (event) => {
      this.#elements.error.hidden = false;
      this.#elements.errorText.textContent = `تعذر التعرف على الصوت: ${event.error || "خطأ غير معروف"}`;
    };
    recognition.onend = () => {
      this.#recognition = null;
      this.#elements.mic.dataset.listening = "false";
      if (this.#elements.composer.value.trim()) void sendCurrent();
    };
    recognition.start();
  }
}

function template() {
  const prompts = QUICK_PROMPTS.map(
    (prompt) => `<button type="button" class="hf-suggestion" data-prompt="${escapeAttribute(prompt)}">${escapeHtml(prompt)}</button>`,
  ).join("");

  return `
    <button type="button" class="hf-return" data-role="return-simple" aria-label="العودة للوضع المبسط">✨ الوضع المبسط</button>
    <div class="hf-shell" data-role="shell">
      <header class="hf-header">
        <div class="hf-brand">
          <div class="hf-logo" aria-hidden="true">☤</div>
          <div>
            <h1>Hermes</h1>
            <div class="hf-status"><span class="hf-status-dot" data-role="status-dot"></span><span data-role="status-text">جارٍ الاتصال…</span></div>
          </div>
        </div>
        <div class="hf-header-actions">
          <button type="button" class="hf-icon-button" data-role="voice" data-enabled="false" aria-pressed="false" title="قراءة الردود صوتيًا">🔊</button>
          <button type="button" class="hf-secondary-button" data-role="new-chat">＋ محادثة جديدة</button>
          <button type="button" class="hf-secondary-button" data-role="advanced">⌘ الوضع المتقدم</button>
        </div>
      </header>

      <main class="hf-conversation">
        <div class="hf-messages" data-role="messages" aria-live="polite"></div>
        <section class="hf-empty" data-role="suggestions">
          <div class="hf-orb">✦</div>
          <h2>كيف أستطيع مساعدتك؟</h2>
          <p>تحدث مع وكيلك مباشرة، اطلب منه تنفيذ المهام، تحليل الملفات أو العمل على مشاريعك.</p>
          <div class="hf-suggestions">${prompts}</div>
        </section>
      </main>

      <div class="hf-error" data-role="error" hidden>
        <span data-role="error-text"></span>
        <button type="button" data-role="reconnect">إعادة الاتصال</button>
      </div>

      <footer class="hf-footer">
        <div class="hf-activity"><span class="hf-pulse"></span><span data-role="activity">جارٍ التجهيز…</span></div>
        <div class="hf-composer-wrap">
          <button type="button" class="hf-icon-button hf-mic" data-role="mic" data-listening="false" title="إرسال رسالة صوتية">🎙️</button>
          <textarea data-role="composer" rows="1" maxlength="20000" placeholder="اكتب رسالتك إلى Hermes…" aria-label="رسالتك إلى Hermes"></textarea>
          <button type="button" class="hf-stop" data-role="stop" hidden title="إيقاف التنفيذ">■</button>
          <button type="button" class="hf-send" data-role="send" aria-label="إرسال الرسالة">➤</button>
        </div>
        <div class="hf-hint">Enter للإرسال · Shift + Enter لسطر جديد</div>
      </footer>
    </div>`;
}

function connectionPresentation(state) {
  switch (state) {
    case ConnectionState.OPEN:
      return { state: "open", text: "متصل وجاهز" };
    case ConnectionState.CONNECTING:
      return { state: "connecting", text: "جارٍ الاتصال" };
    case ConnectionState.ERROR:
      return { state: "error", text: "فشل الاتصال" };
    case ConnectionState.CLOSED:
      return { state: "closed", text: "غير متصل" };
    default:
      return { state: "idle", text: "قيد التجهيز" };
  }
}

function resizeComposer(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
}

function renderText(value) {
  return escapeHtml(String(value || ""))
    .replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

function containsArabic(value) {
  return /[\u0600-\u06FF]/.test(String(value || ""));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function speakArabic(rawText) {
  if (!("speechSynthesis" in window)) return;
  const text = String(rawText || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[`*_>#\[\]()]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text.slice(0, 4000));
  utterance.lang = containsArabic(text) ? "ar-SA" : "en-US";
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}
