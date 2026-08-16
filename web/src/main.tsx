import { Component, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App";
import { SystemActionsProvider } from "./contexts/SystemActions";
import { I18nProvider } from "./i18n";
import { exposePluginSDK } from "./plugins";
import { ThemeProvider } from "./themes";
import { HERMES_BASE_PATH } from "./lib/api";

class DashboardErrorBoundary extends Component<
  { children: ReactNode },
  { message: string }
> {
  state = { message: "" };

  static getDerivedStateFromError(error: unknown) {
    return {
      message: error instanceof Error ? error.message : String(error || "Unknown dashboard error"),
    };
  }

  componentDidCatch(error: unknown) {
    console.error("[dashboard] fatal render error", error);
  }

  render() {
    if (!this.state.message) return this.props.children;
    return (
      <main className="min-h-dvh bg-background-base p-6 text-text-primary">
        <div className="mx-auto max-w-3xl border border-current/20 p-5">
          <h1 className="text-xl font-semibold">Hermes dashboard could not render</h1>
          <p className="mt-3 break-words text-sm text-text-secondary">
            {this.state.message}
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              type="button"
              className="border border-current/25 px-3 py-2 text-xs uppercase tracking-[0.12em]"
              onClick={() => window.location.reload()}
            >
              Retry
            </button>
            <button
              type="button"
              className="border border-current/25 px-3 py-2 text-xs uppercase tracking-[0.12em]"
              onClick={() => window.location.assign(`${HERMES_BASE_PATH || ""}/sessions`)}
            >
              Open sessions
            </button>
          </div>
        </div>
      </main>
    );
  }
}

// Expose the plugin SDK before rendering so plugins loaded via <script>
// can access React, components, etc. immediately.
exposePluginSDK();

createRoot(document.getElementById("root")!).render(
  <DashboardErrorBoundary>
    <BrowserRouter basename={HERMES_BASE_PATH || undefined}>
      <I18nProvider>
        <ThemeProvider>
          <SystemActionsProvider>
            <App />
          </SystemActionsProvider>
        </ThemeProvider>
      </I18nProvider>
    </BrowserRouter>
  </DashboardErrorBoundary>,
);
