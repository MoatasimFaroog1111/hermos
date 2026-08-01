import { ConnectionState } from "./contracts.js";

const QUICK_PROMPTS = [
  {
    title: "اشرح قدراتك",
    text: "اشرح لي باختصار ما الذي تستطيع تنفيذه داخل هذا المشروع.",
  },
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
    const conversationTitle = getConversationTitle(state.messages);

    this.#elements.statusText.textContent = status.text;
    this.#elements.statusDot.dataset.state = status.state;
    this.#elements.activity.textContent = state.activity || "جاهز";
    this.#elements.error.hidden = !state.error;
    this.#elements.errorText.textContent = state.error || "";
    this.#elements.reconnect.hidden = state.connection === ConnectionState.OPEN;
    this.#elements.send.disabled = state.busy || !state.sessionId;
    this.#elements.stop.hidden = !state.busy;
    this.#elements.newChat.disabled = state.connection !== ConnectionState.OPEN;
    this.#elements.mobileNewChat.disabled = state.connection !== ConnectionState.OPEN;
    this.#elements.suggestions.hidden = state.messages.length > 0;
    this.#elements.conversationTitle.textContent = conversationTitle;
    this.#elements.sidebarConversation.textContent = conversationTitle;
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
      sidebar: byRole("sidebar"),
      sidebarBackdrop: byRole("sidebar-backdrop"),
      menu: byRole("menu"),
      messages: byRole("messages"),
      suggestions: byRole("suggestions"),
      composer: byRole("composer"),
      send: byRole("send"),
      stop: byRole("stop"),
      newChat: byRole("new-chat"),
      mobileNewChat: byRole("mobile-new-chat"),
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
      sidebarConversation: byRole("sidebar-conversation"),
    };
  }

  #bindActions(wrapper) {
    const closeSidebar = () => this.#root.removeAttribute("data-sidebar-open");
    const toggleSidebar = () => {
      if (this.#root.hasAttribute("data-sidebar-open")) closeSidebar();
      else this.#root.setAttribute("data-sidebar-open", "true");
    };

    const focusComposer = () => window.setTimeout(() => this.#elements.composer.focus(), 0);

    const startNewConversation = async () => {
      closeSidebar();
      await this.#service.newConversation();
      focusComposer();
    };

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

    this.#elements.newChat.addEventListener("click", startNewConversation);
    this.#elements.mobileNewChat.addEventListener("click", startNewConversation);
    this.#elements.stop.addEventListener("click", () => this.#service.interrupt());
    this.#elements.reconnect.addEventListener("click", () => this.#service.reconnect());
    this.#elements.menu.addEventListener("click", toggleSidebar);
    this.#elements.sidebarBackdrop.addEventListener("click", closeSidebar);

    this.#elements.advanced.addEventListener("click", () => {
      closeSidebar();
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
      this.#elements.voice.querySelector("span:last-child").textContent = this.#voiceEnabled
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
            <div class="hf-message-inner">
              <div class="hf-message-label">${label}</div>
              <div class="hf-message-body">${body}</div>
              ${item.streaming ? '<span class="hf-streaming" aria-label="جارٍ الكتابة"><i></i><i></i><i></i></span>' : ""}
            </div>
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
      <div class="hf-sidebar-backdrop" data-role="sidebar-backdrop"></div>

      <aside class="hf-sidebar" data-role="sidebar" aria-label="قائمة المحادثة">
        <div class="hf-sidebar-top">
          <div class="hf-brand"><span class="hf-brand-mark">H</span><strong>Hermes</strong></div>
          <button type="button" class="hf-new-chat" data-role="new-chat">＋ محادثة جديدة</button>
        </div>

        <nav class="hf-nav" aria-label="المحادثات">
          <div class="hf-nav-label">المحادثات</div>
          <button type="button" class="hf-conversation-item is-active">
            <span class="hf-nav-icon">◯</span>
            <span data-role="sidebar-conversation">محادثة جديدة</span>
          </button>
        </nav>

        <div class="hf-sidebar-actions">
          <button type="button" class="hf-sidebar-action" data-role="voice" data-enabled="false" aria-pressed="false">
            <span>◉</span><span>قراءة الردود صوتيًا</span>
          </button>
          <button type="button" class="hf-sidebar-action" data-role="advanced">
            <span>⌘</span><span>الوضع المتقدم</span>
          </button>
        </div>

        <div class="hf-connection">
          <span class="hf-status-dot" data-role="status-dot"></span>
          <span data-role="status-text">جارٍ الاتصال…</span>
        </div>
      </aside>

      <section class="hf-main">
        <header class="hf-topbar">
          <button type="button" class="hf-topbar-button hf-menu" data-role="menu" aria-label="فتح القائمة">☰</button>
          <div class="hf-title" data-role="conversation-title">محادثة جديدة</div>
          <button type="button" class="hf-topbar-button hf-mobile-new" data-role="mobile-new-chat" aria-label="محادثة جديدة">＋</button>
        </header>

        <main class="hf-conversation">
          <div class="hf-messages" data-role="messages" aria-live="polite"></div>
          <section class="hf-empty" data-role="suggestions">
            <div class="hf-empty-logo">H</div>
            <h1>كيف يمكنني مساعدتك؟</h1>
            <p>اكتب طلبك بصورة طبيعية، وسيعمل Hermes على تنفيذه خطوة بخطوة.</p>
            <div class="hf-suggestions">${prompts}</div>
          </section>
        </main>

        <div class="hf-error" data-role="error" hidden>
          <span data-role="error-text"></span>
          <button type="button" data-role="reconnect">إعادة الاتصال</button>
        </div>

        <footer class="hf-footer">
          <div class="hf-composer-shell">
            <div class="hf-activity" data-role="activity">جارٍ التجهيز…</div>
            <div class="hf-composer-wrap">
              <textarea data-role="composer" rows="1" maxlength="20000" placeholder="أرسل رسالة إلى Hermes" aria-label="رسالتك إلى Hermes"></textarea>
              <div class="hf-composer-actions">
                <button type="button" class="hf-tool-button hf-mic" data-role="mic" data-listening="false" title="استخدام الميكروفون">◉</button>
                <button type="button" class="hf-stop" data-role="stop" hidden title="إيقاف التنفيذ">■</button>
                <button type="button" class="hf-send" data-role="send" aria-label="إرسال الرسالة">↑</button>
              </div>
            </div>
            <div class="hf-hint">قد يخطئ Hermes، لذلك راجع المعلومات المهمة.</div>
          </div>
        </footer>
      </section>
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
  return title.length > 42 ? `${title.slice(0, 42)}…` : title;
}

function resizeComposer(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
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
