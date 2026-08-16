/**
 * usePlugins hook — discovers and loads dashboard plugins.
 *
 * 1. Fetches plugin manifests from GET /api/dashboard/plugins
 * 2. Injects CSS <link> tags for plugins that declare css
 * 3. Loads plugin JS bundles via <script> tags
 * 4. Waits for plugins to call register() and resolves them
 */

import { useState, useEffect, useRef } from "react";
import { api, HERMES_BASE_PATH } from "@/lib/api";
import type { PluginManifest, RegisteredPlugin } from "./types";
import {
  getPluginComponent,
  onPluginRegistered,
  notifyPluginRegistry,
  setPluginLoadError,
} from "./registry";

// Bump only when the dashboard plugin-loading contract changes in a way that
// must invalidate already-cached production plugin assets even when the plugin
// semantic version itself intentionally stays stable.
const PLUGIN_ASSET_CACHE_EPOCH = "20260816.3";

function versionedPluginAssetUrl(
  manifest: PluginManifest,
  relativePath: string,
): string {
  const baseUrl = `${HERMES_BASE_PATH}/dashboard-plugins/${manifest.name}/${relativePath}`;
  const params = new URLSearchParams();
  const version = String(manifest.version || "").trim();
  if (version) params.set("hermes_plugin_v", version);
  params.set("hermes_asset_epoch", PLUGIN_ASSET_CACHE_EPOCH);
  const query = params.toString();
  if (!query) return baseUrl;
  const separator = baseUrl.includes("?") ? "&" : "?";
  return `${baseUrl}${separator}${query}`;
}

export function usePlugins() {
  const [manifests, setManifests] = useState<PluginManifest[]>([]);
  const [plugins, setPlugins] = useState<RegisteredPlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const loadedScripts = useRef<Set<string>>(new Set());

  // Fetch manifests on mount.
  useEffect(() => {
    api
      .getPlugins()
      .then((list) => {
        setManifests(list);
        if (list.length === 0) setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  // Load plugin assets when manifests arrive.
  useEffect(() => {
    if (manifests.length === 0) return;

    const injectedScripts: HTMLScriptElement[] = [];

    for (const manifest of manifests) {
      // Version plugin assets by semantic version plus a dashboard loader epoch.
      // Railway/CDN/browser caches may otherwise keep an older entry bundle
      // while the API already serves a newer manifest or host loader contract.
      if (manifest.css) {
        const cssUrl = versionedPluginAssetUrl(manifest, manifest.css);
        if (!document.querySelector(`link[href="${cssUrl}"]`)) {
          const link = document.createElement("link");
          link.rel = "stylesheet";
          link.href = cssUrl;
          document.head.appendChild(link);
        }
      }

      const versionedUrl = versionedPluginAssetUrl(manifest, manifest.entry);
      // In dev, add a second per-load nonce so Vite HMR can clear the
      // in-memory registry while the browser would otherwise reuse a script.
      const scriptSrc = import.meta.env.DEV
        ? `${versionedUrl}${versionedUrl.includes("?") ? "&" : "?"}hermes_dv=${Date.now()}`
        : versionedUrl;
      if (!import.meta.env.DEV) {
        if (loadedScripts.current.has(scriptSrc)) continue;
        loadedScripts.current.add(scriptSrc);
      }

      const script = document.createElement("script");
      script.setAttribute("data-hermes-plugin", manifest.name);
      script.setAttribute("data-hermes-plugin-version", String(manifest.version || ""));
      script.setAttribute("data-hermes-asset-epoch", PLUGIN_ASSET_CACHE_EPOCH);
      script.src = scriptSrc;
      script.async = true;
      // SRI integrity verification — defense against compromised plugin
      // delivery. Plugin manifests can declare an integrity hash
      // (e.g. "sha384-...") which the browser verifies before executing.
      // Without this, a man-in-the-middle or compromised plugin server
      // can substitute the JS bundle silently. Opt-in: when no integrity
      // is declared in the manifest, behavior is unchanged.
      if (manifest.integrity && typeof manifest.integrity === "string") {
        script.integrity = manifest.integrity;
        script.crossOrigin = "anonymous";
      }
      script.onerror = () => {
        setPluginLoadError(manifest.name, "LOAD_FAILED");
        console.warn(
          `[plugins] Failed to load ${manifest.name} v${manifest.version || "unknown"} epoch ${PLUGIN_ASSET_CACHE_EPOCH} from ${scriptSrc} (open Network tab)`,
        );
      };
      script.onload = () => {
        notifyPluginRegistry();
        queueMicrotask(() => {
          if (getPluginComponent(manifest.name)) return;
          setPluginLoadError(manifest.name, "NO_REGISTER");
        });
      };
      document.body.appendChild(script);
      injectedScripts.push(script);
    }

    // Give plugins a moment to load and register, then stop loading state.
    const timeout = setTimeout(() => setLoading(false), 2000);
    return () => {
      clearTimeout(timeout);
      if (import.meta.env.DEV) {
        for (const el of injectedScripts) {
          el.remove();
        }
      }
    };
  }, [manifests]);

  // Listen for plugin registrations and resolve them against manifests.
  useEffect(() => {
    function resolvePlugins() {
      const resolved: RegisteredPlugin[] = [];
      for (const manifest of manifests) {
        const component = getPluginComponent(manifest.name);
        if (component) {
          resolved.push({ manifest, component });
        }
      }
      setPlugins(resolved);
      // If all plugins registered, stop loading early.
      if (resolved.length === manifests.length && manifests.length > 0) {
        setLoading(false);
      }
    }

    resolvePlugins();
    const unsub = onPluginRegistered(resolvePlugins);
    return unsub;
  }, [manifests]);

  return { plugins, manifests, loading };
}
