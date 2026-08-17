import { describe, expect, it, vi } from "vitest";

import { installVitePreloadRecovery } from "./vite-preload-recovery";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

describe("installVitePreloadRecovery", () => {
  it("reloads once for a stale Vite preload and suppresses a reload loop", () => {
    const eventTarget = new EventTarget();
    const storage = memoryStorage();
    const reload = vi.fn();
    const dispose = installVitePreloadRecovery({
      eventTarget,
      storage,
      reload,
      now: () => 100_000,
    });

    const first = new Event("vite:preloadError", { cancelable: true });
    eventTarget.dispatchEvent(first);

    expect(first.defaultPrevented).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);

    const repeated = new Event("vite:preloadError", { cancelable: true });
    eventTarget.dispatchEvent(repeated);

    expect(repeated.defaultPrevented).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);

    dispose();
  });

  it("allows recovery again after the guard window expires", () => {
    const eventTarget = new EventTarget();
    const storage = memoryStorage();
    const reload = vi.fn();
    let currentTime = 100_000;

    installVitePreloadRecovery({
      eventTarget,
      storage,
      reload,
      now: () => currentTime,
      retryWindowMs: 1_000,
    });

    eventTarget.dispatchEvent(new Event("vite:preloadError", { cancelable: true }));
    currentTime += 1_001;
    eventTarget.dispatchEvent(new Event("vite:preloadError", { cancelable: true }));

    expect(reload).toHaveBeenCalledTimes(2);
  });
});
