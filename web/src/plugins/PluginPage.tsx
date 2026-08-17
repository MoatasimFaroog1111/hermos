import { Component, useSyncExternalStore, type ReactNode } from "react";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import {
  getPluginComponent,
  getPluginLoadError,
  onPluginRegistered,
} from "./registry";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Translations } from "@/i18n/types";

class PluginRenderBoundary extends Component<
  { name: string; children: ReactNode },
  { message: string }
> {
  state = { message: "" };

  static getDerivedStateFromError(error: unknown) {
    return {
      message: error instanceof Error ? error.message : String(error || "Unknown plugin render error"),
    };
  }

  componentDidCatch(error: unknown) {
    console.error(`[plugins] ${this.props.name} render failed`, error);
  }

  render() {
    if (!this.state.message) return this.props.children;
    return (
      <div
        className={cn(
          "max-w-2xl p-4",
          "font-mondwest text-sm tracking-[0.08em] text-text-secondary",
        )}
        role="alert"
      >
        <div className="mb-2 font-semibold text-text-primary">
          {this.props.name === "hermes-avatar"
            ? "Digital Human could not render"
            : "Plugin could not render"}
        </div>
        <div className="break-words">{this.state.message}</div>
        <button
          type="button"
          className="mt-4 border border-current/25 px-3 py-2 text-xs uppercase tracking-[0.12em]"
          onClick={() => window.location.reload()}
        >
          Retry
        </button>
      </div>
    );
  }
}

/** Renders a plugin tab once its bundle has called `register()`. */
export function PluginPage({ name }: { name: string }) {
  const { t } = useI18n();
  // Subscribe in render (via useSyncExternalStore) so we never miss
  // `register()` if the script loads before a useEffect would run.
  const PluginComponent = useSyncExternalStore(
    (onChange) => onPluginRegistered(onChange),
    () => getPluginComponent(name) ?? null,
    () => null,
  );
  const loadError = useSyncExternalStore(
    (onChange) => onPluginRegistered(onChange),
    () => getPluginLoadError(name) ?? null,
    () => null,
  );

  if (PluginComponent) {
    return (
      <PluginRenderBoundary name={name}>
        <PluginComponent />
      </PluginRenderBoundary>
    );
  }

  if (loadError) {
    const message = formatPluginError(loadError, t);
    return (
      <div
        className={cn(
          "max-w-lg p-4",
          "font-mondwest text-sm tracking-[0.08em] text-text-secondary",
        )}
        role="alert"
      >
        {message}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 p-4",
        "font-mondwest text-sm tracking-[0.1em] text-text-tertiary",
      )}
    >
      <Spinner className="shrink-0" />
      <span>{t.common.loading}</span>
    </div>
  );
}

function formatPluginError(code: string, t: Translations): string {
  if (code === "LOAD_FAILED") return t.common.pluginLoadFailed;
  if (code === "NO_REGISTER") return t.common.pluginNotRegistered;
  return code;
}
