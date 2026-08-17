const RECOVERY_STORAGE_KEY = "hermes.vite-preload-recovery-at";
const RECOVERY_WINDOW_MS = 30_000;

type PreloadEventTarget = Pick<EventTarget, "addEventListener" | "removeEventListener">;
type PreloadStorage = Pick<Storage, "getItem" | "setItem">;

export interface VitePreloadRecoveryOptions {
  eventTarget?: PreloadEventTarget;
  storage?: PreloadStorage;
  reload?: () => void;
  now?: () => number;
  retryWindowMs?: number;
}

function resolveSessionStorage(): PreloadStorage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * Recover once from stale Vite dynamic-import URLs after a rolling deploy.
 *
 * A browser tab can keep an older dashboard shell alive while Railway swaps in
 * a freshly-built image. Lazy routes (for example /plugins) then request the
 * old hashed chunk and Vite emits `vite:preloadError`. Reloading once obtains
 * the new index/chunk graph. A session timestamp prevents a genuinely broken
 * build from entering an automatic reload loop.
 */
export function installVitePreloadRecovery(
  options: VitePreloadRecoveryOptions = {},
): () => void {
  const eventTarget = options.eventTarget ?? window;
  const storage = options.storage ?? resolveSessionStorage();
  const reload = options.reload ?? (() => window.location.reload());
  const now = options.now ?? Date.now;
  const retryWindowMs = options.retryWindowMs ?? RECOVERY_WINDOW_MS;

  const onPreloadError = (event: Event) => {
    // If session storage is unavailable we cannot persist a loop guard across
    // the reload, so fail open to the dashboard error boundary instead.
    if (!storage) return;

    const currentTime = now();
    let previousRecovery = 0;
    try {
      previousRecovery = Number(storage.getItem(RECOVERY_STORAGE_KEY) || 0);
    } catch {
      return;
    }

    if (
      Number.isFinite(previousRecovery) &&
      previousRecovery > 0 &&
      currentTime - previousRecovery < retryWindowMs
    ) {
      return;
    }

    try {
      storage.setItem(RECOVERY_STORAGE_KEY, String(currentTime));
    } catch {
      return;
    }

    // Vite recommends cancelling the stale preload failure when the app is
    // taking responsibility for recovery; the reload then boots the new build.
    event.preventDefault();
    reload();
  };

  eventTarget.addEventListener("vite:preloadError", onPreloadError);
  return () => eventTarget.removeEventListener("vite:preloadError", onPreloadError);
}
