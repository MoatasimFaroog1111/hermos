/**
 * usePlugins hook — discovers and loads dashboard plugins.
 *
 * 1. Fetches plugin manifests from GET /api/dashboard/plugins
 * 2. Recovers bundled dashboard manifests that are physically available but
 *    were omitted by stale visibility state
 * 3. Injects CSS <link> tags for plugins that declare css
 * 4. Loads plugin JS bundles via <script> tags
 * 5. Waits for plugins to call register() and resolves them
 */

import { useState, useEffect, useRef } from "react";
import { api, HERMES_BASE_PATH } from "@/lib/api";
import type { PluginManifest, RegisteredPlugin } from "./types";
import { recoverBundledDashboardManifests } from "./coreManifestRecovery";
import {
  getPluginComponent,
  onPluginRegistered,
  notifyPluginRegistry,
  setPluginLoadError,
} from "./registry";

/**
 * Return one coherent URL revision for every asset that belongs to a plugin.
 *
 * Dashboard plugin files are served from stable paths, so a browser/CDN can
 * otherwise combine a fresh manifest with an older JS/CSS object after a
 * Railway deploy. The semantic plugin version is the cache key in production;
 * dev gets an additional nonce so HMR always re-executes the bundle.
 */
function pluginAssetUrl(manifest: PluginManifest, relativePath: string): string {
  const baseUrl = `${HERMES_BASE_PATH}/dashboard-plugins/${manifest.name}/${relativePath}`;
  const params = new URLSearchParams();
  const version = String(manifest.version || "").trim();
  if (version) params.set("hermes_plugin_v", version);
  if (import.meta.env.DEV) params.set("hermes_dv", String(Date.now()));

  const query = params.toString();
  if (!query) return baseUrl;
  return `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}${query}`;
}

export function usePlugins() {
  const [manifests, setManifests] = useState<PluginManifest[]>([]);
  const [plugins, setPlugins] = useState<RegisteredPlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const loadedScripts = useRef<Set<string>>(new Set());

  // Fetch manifests on mount. A stale dashboard.hidden_plugins value can omit
  // an application-owned bundled extension from this API, so recover only
  // bundled manifests whose static manifest is still actually servable.
  useEffect(() => {
    let cancelled = false;

    const applyManifests = async (list: PluginManifest[]) => {
      const effective = await recoverBundledDashboardManifests(list);
      if (cancelled) return;
      setManifests(effective);
      if (effective.length === 0) setLoading(false);
    };

    api
      .getPlugins()
      .then((list) => applyManifests(list))
      .catch(() => applyManifests([]));

    return () => {
      cancelled = true;
    };
  }, []);

  // Load plugin assets when manifests arrive.
  useEffect(() => {
    if (manifests.length === 0) return;

    const injectedScripts: HTMLScriptElement[] = [];

    for (const manifest of manifests) {
      // CSS and JS must carry the same plugin revision so the page cannot mix
      // assets from different deployments.
      if (manifest.css) {
        const cssUrl = pluginAssetUrl(manifest, manifest.css);
        if (!document.querySelector(`link[href="${cssUrl}"]`)) {
          const link = document.createElement("link");
          link.rel = "stylesheet";
          link.href = cssUrl;
          link.setAttribute("data-hermes-plugin", manifest.name);
          link.setAttribute("data-hermes-plugin-version", String(manifest.version || ""));
          document.head.appendChild(link);
        }
      }

      const scriptSrc = pluginAssetUrl(manifest, manifest.entry);
      if (!import.meta.env.DEV) {
        if (loadedScripts.current.has(scriptSrc)) continue;
        // Reserve while in-flight to prevent duplicate insertion. A failed
        // request removes the reservation so a rescan/remount can retry.
        loadedScripts.current.add(scriptSrc);
      }

      const script = document.createElement("script");
      script.setAttribute("data-hermes-plugin", manifest.name);
      script.setAttribute("data-hermes-plugin-version", String(manifest.version || ""));
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
        if (!import.meta.env.DEV) loadedScripts.current.delete(scriptSrc);
        setPluginLoadError(manifest.name, "LOAD_FAILED");
        console.warn(
          `[plugins] Failed to load ${manifest.name} v${manifest.version || "unknown"} from ${scriptSrc} (open Network tab)`,
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
