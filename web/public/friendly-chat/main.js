import { ConversationService } from "./conversationService.js";
import { FriendlyChatView } from "./friendlyChatView.js";
import { HermesGatewayAdapter } from "./hermesGatewayAdapter.js";

let mounted = null;

function selectedProfile() {
  return new URLSearchParams(window.location.search).get("profile") || "";
}

/**
 * Friendly Chat owns the terminal/chat surface only.
 * Plugin pages have their own runtime (for example Digital Human) and must not
 * be observed or mutated by the chat composition root.
 */
function isPluginRoute(pathname = window.location.pathname) {
  const path = String(pathname || "/").replace(/\/+$/, "") || "/";
  return path === "/plugins"
    || path.startsWith("/plugins/")
    || path === "/digital-human"
    || path.startsWith("/digital-human/")
    || path.startsWith("/dashboard-plugins/");
}

function chatHost() {
  return document.querySelector(".hermes-chat-xterm-host");
}

/**
 * Tear the Friendly Chat composition root down completely.
 *
 * The dashboard is an SPA, so leaving Chat does not reload this module. Merely
 * refusing a new mount is not enough: the existing view owns a canvas,
 * microphone state and DOM listeners, while the service owns gateway listeners
 * and a live connection. All of those must be disposed before a plugin route
 * becomes active.
 */
function unmountFriendlyChat() {
  if (!mounted) return;

  // Clear first because dispose() mutates DOM and therefore re-enters the
  // MutationObserver. Reconciliation must see a stable "not mounted" state.
  const current = mounted;
  mounted = null;

  try {
    current.view.dispose();
  } catch (error) {
    console.warn("[friendly-chat] view disposal failed", error);
  }

  try {
    current.service.dispose();
  } catch (error) {
    console.warn("[friendly-chat] service disposal failed", error);
  }

  current.wrapper?.classList.remove("friendly-chat-active", "friendly-chat-advanced");
}

function mountedSurfaceIsStale() {
  if (!mounted) return false;
  if (isPluginRoute()) return true;
  if (!mounted.host?.isConnected) return true;
  return chatHost() !== mounted.host;
}

function reconcileMount() {
  if (mountedSurfaceIsStale()) {
    unmountFriendlyChat();
  }

  if (isPluginRoute()) return;
  if (mounted || document.getElementById("hermes-friendly-chat")) return;

  const host = chatHost();
  const wrapper = host?.parentElement || null;
  if (!host || !wrapper) return;

  const gateway = new HermesGatewayAdapter({ profile: selectedProfile() });
  const service = new ConversationService(gateway);
  const view = new FriendlyChatView({ host, service });

  try {
    view.mount();
    mounted = { service, view, host, wrapper };
    void service.start();
  } catch (error) {
    try {
      view.dispose();
    } catch {
      // Best-effort cleanup after a partial mount.
    }
    service.dispose();
    console.error("[friendly-chat] failed to mount", error);
  }
}

const observer = new MutationObserver(reconcileMount);
observer.observe(document.documentElement, { childList: true, subtree: true });

// Back/forward navigation can change the route before React mutates the tree.
// Reconcile immediately; regular SPA link transitions are also caught by the
// MutationObserver when the route outlet changes.
window.addEventListener("popstate", reconcileMount);

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", reconcileMount, { once: true });
} else {
  reconcileMount();
}
