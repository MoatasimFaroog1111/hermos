import { ConversationService } from "./conversationService.js";
import { FriendlyChatView } from "./friendlyChatView.js";
import { HermesGatewayAdapter } from "./hermesGatewayAdapter.js";

let mounted = null;

function selectedProfile() {
  return new URLSearchParams(window.location.search).get("profile") || "";
}

function tryMount() {
  if (mounted || document.getElementById("hermes-friendly-chat")) return;
  const host = document.querySelector(".hermes-chat-xterm-host");
  if (!host) return;

  const gateway = new HermesGatewayAdapter({ profile: selectedProfile() });
  const service = new ConversationService(gateway);
  const view = new FriendlyChatView({ host, service });
  view.mount();
  mounted = { service, view };
  void service.start();
}

const observer = new MutationObserver(tryMount);
observer.observe(document.documentElement, { childList: true, subtree: true });

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", tryMount, { once: true });
} else {
  tryMount();
}
