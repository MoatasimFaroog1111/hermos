import { ConnectionState, GatewayEvents } from "./contracts.js";

/** Application service that owns the conversation use cases and UI state. */
export class ConversationService {
  #gateway;
  #listeners = new Set();
  #unsubscribers = [];
  #state = {
    connection: ConnectionState.IDLE,
    sessionId: null,
    messages: [],
    activity: "",
    busy: false,
    error: "",
  };

  constructor(gateway) {
    this.#gateway = gateway;
  }

  get snapshot() {
    return structuredClone(this.#state);
  }

  subscribe(listener) {
    this.#listeners.add(listener);
    listener(this.snapshot);
    return () => this.#listeners.delete(listener);
  }

  async start() {
    this.#bindGatewayEvents();
    try {
      await this.#gateway.connect();
      await this.newConversation();
    } catch (error) {
      this.#fail(error);
    }
  }

  async reconnect() {
    this.#patch({ error: "", activity: "جارٍ إعادة الاتصال…" });
    try {
      this.#gateway.disconnect();
      await this.#gateway.connect();
      if (!this.#state.sessionId) await this.newConversation();
      this.#patch({ activity: "" });
    } catch (error) {
      this.#fail(error);
    }
  }

  async newConversation() {
    this.#patch({
      sessionId: null,
      messages: [],
      activity: "جارٍ تجهيز محادثة جديدة…",
      busy: true,
      error: "",
    });
    try {
      const sessionId = await this.#gateway.createSession();
      this.#patch({ sessionId, activity: "", busy: false });
    } catch (error) {
      this.#fail(error);
    }
  }

  async send(text) {
    const prompt = String(text || "").trim();
    if (!prompt || this.#state.busy) return false;
    if (!this.#state.sessionId) {
      this.#patch({ error: "الجلسة غير جاهزة بعد" });
      return false;
    }

    this.#state.messages.push(message("user", prompt));
    this.#patch({ busy: true, activity: "يفكر Hermes…", error: "" });

    try {
      // Completion is delivered through message.complete; the request response is
      // only an acknowledgement and may arrive later than the stream.
      void this.#gateway
        .sendPrompt(this.#state.sessionId, prompt)
        .catch((error) => this.#fail(error));
      return true;
    } catch (error) {
      this.#fail(error);
      return false;
    }
  }

  async interrupt() {
    if (!this.#state.sessionId) return;
    try {
      await this.#gateway.interrupt(this.#state.sessionId);
      this.#patch({ busy: false, activity: "تم إيقاف التنفيذ" });
    } catch (error) {
      this.#fail(error);
    }
  }

  dispose() {
    for (const unsubscribe of this.#unsubscribers.splice(0)) unsubscribe();
    this.#gateway.disconnect();
    this.#listeners.clear();
  }

  #bindGatewayEvents() {
    if (this.#unsubscribers.length) return;

    this.#unsubscribers.push(
      this.#gateway.subscribeConnection((connection) => {
        this.#patch({ connection });
      }),
      this.#gateway.subscribe(GatewayEvents.SESSION_INFO, (event) => {
        const sessionId = event.session_id || event.payload?.session_id;
        if (sessionId) this.#patch({ sessionId: String(sessionId) });
      }),
      this.#gateway.subscribe(GatewayEvents.MESSAGE_START, () => {
        this.#ensureAssistantDraft();
        this.#patch({ busy: true, activity: "يكتب الرد…" });
      }),
      this.#gateway.subscribe(GatewayEvents.MESSAGE_DELTA, (event) => {
        const text = readText(event.payload);
        if (!text) return;
        const draft = this.#ensureAssistantDraft();
        draft.content += text;
        this.#emit();
      }),
      this.#gateway.subscribe(GatewayEvents.MESSAGE_INTERIM, (event) => {
        const text = readText(event.payload);
        if (!text) return;
        const draft = this.#ensureAssistantDraft();
        draft.content = text;
        draft.interim = true;
        this.#emit();
      }),
      this.#gateway.subscribe(GatewayEvents.MESSAGE_COMPLETE, (event) => {
        const finalText = readText(event.payload);
        const draft = this.#ensureAssistantDraft();
        if (finalText) draft.content = finalText;
        draft.streaming = false;
        draft.interim = false;
        this.#patch({ busy: false, activity: "" });
      }),
      this.#gateway.subscribe(GatewayEvents.TOOL_START, (event) => {
        this.#patch({ activity: toolLabel(event.payload, "يستخدم أداة…") });
      }),
      this.#gateway.subscribe(GatewayEvents.TOOL_PROGRESS, (event) => {
        this.#patch({ activity: toolLabel(event.payload, "ينفذ المهمة…") });
      }),
      this.#gateway.subscribe(GatewayEvents.TOOL_COMPLETE, () => {
        this.#patch({ activity: "يراجع النتيجة…" });
      }),
      this.#gateway.subscribe(GatewayEvents.THINKING_DELTA, () => {
        this.#patch({ activity: "يفكر في أفضل إجابة…" });
      }),
      this.#gateway.subscribe(GatewayEvents.REASONING_DELTA, () => {
        this.#patch({ activity: "يحلل الطلب…" });
      }),
      this.#gateway.subscribe(GatewayEvents.STATUS_UPDATE, (event) => {
        const status = readText(event.payload);
        if (status) this.#patch({ activity: status });
      }),
      this.#gateway.subscribe(GatewayEvents.CLARIFY_REQUEST, () => {
        this.#addNotice("يحتاج Hermes إلى توضيح إضافي. اكتب إجابتك هنا أو افتح الوضع المتقدم.");
      }),
      this.#gateway.subscribe(GatewayEvents.APPROVAL_REQUEST, () => {
        this.#addNotice("هناك إجراء يحتاج موافقتك. افتح الوضع المتقدم لمراجعة التفاصيل بأمان.");
      }),
      this.#gateway.subscribe(GatewayEvents.SUDO_REQUEST, () => {
        this.#addNotice("طلب Hermes صلاحية مرتفعة. راجع الطلب من الوضع المتقدم قبل الموافقة.");
      }),
      this.#gateway.subscribe(GatewayEvents.SECRET_REQUEST, () => {
        this.#addNotice("يحتاج Hermes إلى معلومة سرية. استخدم الوضع المتقدم لإدخالها بأمان.");
      }),
      this.#gateway.subscribe(GatewayEvents.ERROR, (event) => {
        const text = readText(event.payload) || "حدث خطأ أثناء تشغيل الوكيل";
        this.#fail(new Error(text));
      }),
    );
  }

  #ensureAssistantDraft() {
    const last = this.#state.messages.at(-1);
    if (last?.role === "assistant" && last.streaming) return last;
    const draft = message("assistant", "");
    draft.streaming = true;
    this.#state.messages.push(draft);
    return draft;
  }

  #addNotice(content) {
    this.#state.messages.push(message("notice", content));
    this.#patch({ busy: false, activity: "" });
  }

  #fail(error) {
    const text = error instanceof Error ? error.message : String(error);
    this.#patch({ busy: false, activity: "", error: text });
  }

  #patch(patch) {
    Object.assign(this.#state, patch);
    this.#emit();
  }

  #emit() {
    const snapshot = this.snapshot;
    for (const listener of this.#listeners) listener(snapshot);
  }
}

function message(role, content) {
  return {
    id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
    role,
    content,
    createdAt: Date.now(),
    streaming: false,
    interim: false,
  };
}

function readText(payload) {
  if (typeof payload === "string") return payload;
  if (!payload || typeof payload !== "object") return "";
  for (const key of ["text", "rendered", "message", "content", "status"]) {
    if (typeof payload[key] === "string" && payload[key].trim()) return payload[key];
  }
  return "";
}

function toolLabel(payload, fallback) {
  if (!payload || typeof payload !== "object") return fallback;
  const name = payload.display_name || payload.name || payload.tool_name || payload.tool;
  return name ? `يعمل عبر ${name}…` : fallback;
}
