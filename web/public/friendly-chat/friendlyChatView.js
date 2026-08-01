import { ConnectionState } from "./contracts.js";
import { SkyScene } from "./skyScene.js";

const QUICK_PROMPTS = [
  {
    title: "افحص المشروع",
    text: "افحص المشروع الحالي وحدد أهم المشكلات والتحسينات المقترحة.",
  },
  {
    title: "أنشئ خطة",
    text: "أنشئ خطة عمل واضحة ومنظمة للمهمة التي سأرسلها لك.",
  },
  {
    title: "ساعدني في البرمجة",
    text: "ساعدني في كتابة كود نظيف مع شرح الخطوات والملفات التي ستتغير.",
  },
  {
    title: "اشرح قدراتك",
    text: "اشرح لي باختصار ما الذي تستطيع تنفيذه داخل هذا المشروع.",
  },
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
  #skyScene = null;
  #responseDismissed = false;
  #messageCount = 0;

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
    this.#skyScene = new SkyScene(this.#elements.skyCanvas);
    this.#skyScene.start();
    this.#unsubscribe = this.#service.subscribe((state) => this.render(state));
  }

  dispose() {
    this.#unsubscribe?.();
    this.#recognition?.abort?.();
    this.#skyScene?.dispose();
    this.#root.remove();
  }

  render(state) {
    const status = connectionPresentation(state.connection);
    const conversationTitle = getConversationTitle(state.messages);
    const hasMessages = state.messages.length > 0;

    if (state.messages.length > this.#messageCount) this.#responseDismissed = false;
    this.#messageCount = state.messages.length;

    this.#root.dataset.hasMessages = String(hasMessages);
    this.#elements.statusText.textContent = status.text;
    this.#elements.statusDot.dataset.state = status.state;
    this.#elements.activity.textContent = state.activity || "جاهز";
    this.#elements.error.hidden = !state.error;
    this.#elements.errorText.textContent = state.error || "";
    this.#elements.reconnect.hidden = state.connection === ConnectionState.OPEN;
    this.#elements.send.disabled = state.busy || !state.sessionId;
    this.#elements.stop.hidden = !state.busy;
    this.#elements.newChat.disabled = state.connection !== ConnectionState.OPEN;
    this.#elements.suggestions.hidden = hasMessages;
    this.#elements.messagesPanel.hidden = !hasMessages || this.#responseDismissed;
    this.#elements.conversationTitle.textContent = conversationTitle;
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
      returnButton: byRole("return-simple"),
      skyCanvas: byRole("sky-canvas"),
      messagesPanel: byRole("messages-panel"),
      messages: byRole("messages"),
      responseClose: byRole("response-close"),
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
      conversationTitle: byRole("conversation-title"),
    };
  }

  #bindActions(wrapper) {
    const focusComposer = () => window.setTimeout(() => this.#elements.composer.focus(), 0);

    const startNewConversation = async () => {
      this.#responseDismissed = false;
      await this.#service.newConversation();
      focusComposer();
    };

    const sendCurrent = async () => {
      const text = this.#elements.composer.value;
      this.#responseDismissed = false;
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

    this.#elements.newChat.addEventListener("click", startNewConversation);
    this.#elements.stop.addEventListener("click", () => this.#service.interrupt());
    this.#elements.reconnect.addEventListener("click", () => this.#service.reconnect());
    this.#elements.responseClose.addEventListener("click", () => {
      this.#responseDismissed = true;
      this.#elements.messagesPanel.hidden = true;
      focusComposer();
    });

    this.#elements.advanced.addEventListener("click", () => {
      wrapper.classList.remove("friendly-chat-active");
      wrapper.classList.add("friendly-chat-advanced");
      this.#root.dataset.mode = "advanced";
    });
    this.#elements.returnButton.addEventListener("click", () => {
      wrapper.classList.remove("friendly-chat-advanced");
      wrapper.classList.add("friendly-chat-active");
      this.#root.dataset.mode = "simple";
      focusComposer();
    });

    this.#elements.voice.addEventListener("click", () => {
      this.#voiceEnabled = !this.#voiceEnabled;
      this.#elements.voice.dataset.enabled = String(this.#voiceEnabled);
      this.#elements.voice.setAttribute("aria-pressed", String(this.#voiceEnabled));
      this.#elements.voice.title = this.#voiceEnabled
        ? "إيقاف قراءة الردود"
        : "قراءة الردود صوتيًا";
      if (!this.#voiceEnabled) window.speechSynthesis?.cancel?.();
    });

    this.#elements.mic.addEventListener("click", () => this.#toggleMicrophone(sendCurrent));

    for (const button of this.#root.querySelectorAll("[data-prompt]")) {
      button.addEventListener("click", () => {
        this.#elements.composer.value = button.dataset.prompt || "";
        resizeComposer(this.#elements.composer);
        focusComposer();
      });
    }
  }

  #renderMessages(messages) {
    this.#elements.messages.innerHTML = messages
      .map((item) => {
        const direction = containsArabic(item.content) ? "rtl" : "ltr";
        const body = renderText(item.content || (item.streaming ? "…" : ""));
        const label = item.role === "user" ? "أنت" : item.role === "notice" ? "تنبيه" : "Hermes";
        return `
          <article class="hf-message hf-${item.role}" dir="${direction}">
            <div class="hf-message-label">${label}</div>
            <div class="hf-message-body">${body}</div>
            ${item.streaming ? '<span class="hf-streaming" aria-label="جارٍ الكتابة"><i></i><i></i><i></i></span>' : ""}
          </article>`;
      })
      .join("");

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
    ({ title, text }) => `
      <button type="button" class="hf-suggestion" data-prompt="${escapeAttribute(text)}">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(text)}</span>
      </button>`,
  ).join("");

  return `
    <button type="button" class="hf-return" data-role="return-simple">العودة إلى المحادثة</button>
    <div class="hf-shell">
      <canvas class="hf-sky-canvas" data-role="sky-canvas" aria-hidden="true"></canvas>
      <div class="hf-sky-haze" aria-hidden="true"></div>

      <header class="hf-topbar">
        <div class="hf-brand" aria-label="Hermes">
          <span class="hf-brand-diamond">◇</span>
          <div>
            <strong>Hermes</strong>
            <small data-role="conversation-title">محادثة جديدة</small>
          </div>
        </div>
        <div class="hf-top-actions">
          <div class="hf-connection" title="حالة الاتصال">
            <span class="hf-status-dot" data-role="status-dot"></span>
            <span data-role="status-text">جارٍ الاتصال…</span>
          </div>
          <button type="button" class="hf-icon-button" data-role="voice" data-enabled="false" aria-pressed="false" title="قراءة الردود صوتيًا">◉</button>
          <button type="button" class="hf-icon-button" data-role="advanced" title="الوضع المتقدم">⌘</button>
          <button type="button" class="hf-new-chat" data-role="new-chat">＋ محادثة جديدة</button>
        </div>
      </header>

      <main class="hf-stage">
        <section class="hf-empty" data-role="suggestions">
          <div class="hf-hero-mark">◇</div>
          <p class="hf-eyebrow">وكيلك الذكي المتصل بالمشروع</p>
          <h1>كيف يمكنني مساعدتك؟</h1>
          <p class="hf-hero-copy">اكتب طلبك بصورة طبيعية، وسيعمل Hermes على تنفيذه عبر الجلسة الآمنة والأدوات المتاحة.</p>
          <div class="hf-suggestions">${prompts}</div>
        </section>

        <section class="hf-response-panel" data-role="messages-panel" hidden>
          <header class="hf-response-header">
            <div>
              <strong>استجابة Hermes</strong>
              <span data-role="activity">جارٍ التجهيز…</span>
            </div>
            <button type="button" class="hf-response-close" data-role="response-close" aria-label="إغلاق الاستجابة">×</button>
          </header>
          <div class="hf-messages" data-role="messages" aria-live="polite"></div>
        </section>
      </main>

      <div class="hf-error" data-role="error" hidden>
        <span data-role="error-text"></span>
        <button type="button" data-role="reconnect">إعادة الاتصال</button>
      </div>

      <footer class="hf-footer">
        <div class="hf-composer-shell">
          <div class="hf-composer-wrap">
            <textarea data-role="composer" rows="1" maxlength="20000" placeholder="اكتب رسالتك هنا..." aria-label="رسالتك إلى Hermes"></textarea>
            <div class="hf-composer-actions">
              <button type="button" class="hf-tool-button hf-mic" data-role="mic" data-listening="false" title="استخدام الميكروفون">◉</button>
              <button type="button" class="hf-stop" data-role="stop" hidden title="إيقاف التنفيذ">■</button>
              <button type="button" class="hf-send" data-role="send" aria-label="إرسال الرسالة">↑</button>
            </div>
          </div>
          <div class="hf-footer-meta">
            <span class="hf-activity-mobile" data-role="activity-copy">متصل بخدمة Hermes</span>
            <span>راجع النتائج المهمة قبل اعتمادها.</span>
          </div>
        </div>
      </footer>
    </div>`;
}

function connectionPresentation(state) {
  switch (state) {
    case ConnectionState.OPEN:
      return { state: "open", text: "متصل" };
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

function getConversationTitle(messages) {
  const firstUserMessage = messages.find((item) => item.role === "user" && item.content?.trim());
  if (!firstUserMessage) return "محادثة جديدة";
  const title = firstUserMessage.content.replace(/\s+/g, " ").trim();
  return title.length > 34 ? `${title.slice(0, 34)}…` : title;
}

function resizeComposer(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
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
