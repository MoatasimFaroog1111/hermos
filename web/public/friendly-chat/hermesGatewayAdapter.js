import { AgentGatewayPort, ConnectionState } from "./contracts.js";

const REQUEST_TIMEOUT_MS = 120_000;
const PROMPT_TIMEOUT_MS = 1_800_000;

/** Infrastructure adapter for Hermes' JSON-RPC WebSocket gateway. */
export class HermesGatewayAdapter extends AgentGatewayPort {
  #socket = null;
  #nextRequestId = 0;
  #pending = new Map();
  #eventListeners = new Map();
  #connectionListeners = new Set();
  #connectionState = ConnectionState.IDLE;
  #profile = "";

  constructor({ profile = "" } = {}) {
    super();
    this.#profile = String(profile || "").trim();
  }

  async connect() {
    if (
      this.#connectionState === ConnectionState.OPEN ||
      this.#connectionState === ConnectionState.CONNECTING
    ) {
      return;
    }

    this.#setConnectionState(ConnectionState.CONNECTING);
    const url = await this.#buildWebSocketUrl();
    const socket = new WebSocket(url);
    this.#socket = socket;

    socket.addEventListener("message", (event) => this.#handleFrame(event.data));
    socket.addEventListener("close", () => {
      if (this.#socket !== socket) return;
      this.#socket = null;
      this.#rejectPending(new Error("انقطع اتصال Hermes"));
      this.#setConnectionState(ConnectionState.CLOSED);
    });

    await new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        cleanup();
        try {
          socket.close();
        } catch {
          // Best effort.
        }
        this.#setConnectionState(ConnectionState.ERROR);
        reject(new Error("انتهت مهلة الاتصال بالوكيل"));
      }, 15_000);

      const cleanup = () => {
        window.clearTimeout(timeout);
        socket.removeEventListener("open", onOpen);
        socket.removeEventListener("error", onError);
      };
      const onOpen = () => {
        cleanup();
        this.#setConnectionState(ConnectionState.OPEN);
        resolve();
      };
      const onError = () => {
        cleanup();
        this.#setConnectionState(ConnectionState.ERROR);
        reject(new Error("تعذر فتح اتصال WebSocket مع Hermes"));
      };

      socket.addEventListener("open", onOpen, { once: true });
      socket.addEventListener("error", onError, { once: true });
    });
  }

  disconnect() {
    const socket = this.#socket;
    this.#socket = null;
    if (socket) {
      try {
        socket.close();
      } catch {
        // Best effort.
      }
    }
    this.#rejectPending(new Error("تم إغلاق اتصال Hermes"));
    this.#setConnectionState(ConnectionState.CLOSED);
  }

  async createSession() {
    const result = await this.#request("session.create", {});
    const sessionId = result?.session_id || result?.id;
    if (!sessionId) {
      throw new Error("لم يرجع Hermes رقم جلسة صالحًا");
    }
    return String(sessionId);
  }

  async sendPrompt(sessionId, text) {
    return this.#request(
      "prompt.submit",
      { session_id: sessionId, text },
      PROMPT_TIMEOUT_MS,
    );
  }

  async interrupt(sessionId) {
    return this.#request("session.interrupt", { session_id: sessionId });
  }

  subscribe(eventName, listener) {
    const key = String(eventName);
    const listeners = this.#eventListeners.get(key) || new Set();
    listeners.add(listener);
    this.#eventListeners.set(key, listeners);
    return () => listeners.delete(listener);
  }

  subscribeConnection(listener) {
    this.#connectionListeners.add(listener);
    listener(this.#connectionState);
    return () => this.#connectionListeners.delete(listener);
  }

  async #request(method, params, timeoutMs = REQUEST_TIMEOUT_MS) {
    const socket = this.#socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      throw new Error("الوكيل غير متصل");
    }

    const id = `friendly-${++this.#nextRequestId}`;
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`انتهت مهلة الطلب: ${method}`));
      }, timeoutMs);

      this.#pending.set(id, { resolve, reject, timer });
      socket.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  #handleFrame(raw) {
    let frame;
    try {
      frame = JSON.parse(String(raw));
    } catch {
      return;
    }

    if (frame.id !== undefined && frame.id !== null) {
      const pending = this.#pending.get(frame.id);
      if (!pending) return;
      window.clearTimeout(pending.timer);
      this.#pending.delete(frame.id);
      if (frame.error) {
        pending.reject(new Error(frame.error.message || "فشل طلب Hermes"));
      } else {
        pending.resolve(frame.result);
      }
      return;
    }

    if (frame.method !== "event" || !frame.params?.type) return;
    const eventName = String(frame.params.type);
    for (const listener of this.#eventListeners.get(eventName) || []) {
      listener(frame.params);
    }
    for (const listener of this.#eventListeners.get("*") || []) {
      listener(frame.params);
    }
  }

  async #buildWebSocketUrl() {
    const basePath = normalizeBasePath(window.__HERMES_BASE_PATH__ || "");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(`${protocol}//${window.location.host}${basePath}/api/ws`);

    if (this.#profile) url.searchParams.set("profile", this.#profile);

    if (window.__HERMES_AUTH_REQUIRED__) {
      const response = await fetch(`${basePath}/api/auth/ws-ticket`, {
        method: "POST",
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error(`تعذر إنشاء تصريح الاتصال (${response.status})`);
      }
      const payload = await response.json();
      if (!payload?.ticket) throw new Error("لم يرجع الخادم تصريح WebSocket");
      url.searchParams.set("ticket", payload.ticket);
    } else {
      const token = window.__HERMES_SESSION_TOKEN__ || "";
      if (!token) throw new Error("رمز جلسة لوحة Hermes غير متوفر");
      url.searchParams.set("token", token);
    }

    return url.toString();
  }

  #setConnectionState(nextState) {
    if (this.#connectionState === nextState) return;
    this.#connectionState = nextState;
    for (const listener of this.#connectionListeners) listener(nextState);
  }

  #rejectPending(error) {
    for (const pending of this.#pending.values()) {
      window.clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.#pending.clear();
  }
}

function normalizeBasePath(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return `/${text.replace(/^\/+|\/+$/g, "")}`;
}
