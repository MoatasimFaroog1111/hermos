/**
 * Domain contracts for the browser chat.
 *
 * The presentation and application layers depend on this port instead of a
 * concrete WebSocket implementation. That keeps the UI replaceable and makes
 * the Hermes transport an infrastructure detail.
 */
export class AgentGatewayPort {
  async connect() {
    throw new Error("AgentGatewayPort.connect() must be implemented");
  }

  disconnect() {
    throw new Error("AgentGatewayPort.disconnect() must be implemented");
  }

  async createSession() {
    throw new Error("AgentGatewayPort.createSession() must be implemented");
  }

  async sendPrompt(_sessionId, _text) {
    throw new Error("AgentGatewayPort.sendPrompt() must be implemented");
  }

  async interrupt(_sessionId) {
    throw new Error("AgentGatewayPort.interrupt() must be implemented");
  }

  subscribe(_eventName, _listener) {
    throw new Error("AgentGatewayPort.subscribe() must be implemented");
  }

  subscribeConnection(_listener) {
    throw new Error("AgentGatewayPort.subscribeConnection() must be implemented");
  }
}

export const GatewayEvents = Object.freeze({
  READY: "gateway.ready",
  SESSION_INFO: "session.info",
  MESSAGE_START: "message.start",
  MESSAGE_DELTA: "message.delta",
  MESSAGE_INTERIM: "message.interim",
  MESSAGE_COMPLETE: "message.complete",
  THINKING_DELTA: "thinking.delta",
  REASONING_DELTA: "reasoning.delta",
  STATUS_UPDATE: "status.update",
  TOOL_START: "tool.start",
  TOOL_PROGRESS: "tool.progress",
  TOOL_COMPLETE: "tool.complete",
  CLARIFY_REQUEST: "clarify.request",
  APPROVAL_REQUEST: "approval.request",
  SUDO_REQUEST: "sudo.request",
  SECRET_REQUEST: "secret.request",
  ERROR: "error",
});

export const ConnectionState = Object.freeze({
  IDLE: "idle",
  CONNECTING: "connecting",
  OPEN: "open",
  CLOSED: "closed",
  ERROR: "error",
});
