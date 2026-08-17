import { HERMES_BASE_PATH } from "@/lib/api";
import type { PluginManifest } from "./types";

interface RecoverySpec {
  name: string;
  expectedPath: string;
}

const RECOVERABLE_BUNDLED_DASHBOARD_PLUGINS: RecoverySpec[] = [
  { name: "hermes-avatar", expectedPath: "/digital-human" },
];

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function normalizeBundledManifest(
  rawValue: unknown,
  spec: RecoverySpec,
): PluginManifest | null {
  const raw = asRecord(rawValue);
  const tab = asRecord(raw?.tab);
  if (!raw || !tab) return null;

  const name = asString(raw.name);
  const path = asString(tab.path);
  const entry = asString(raw.entry);
  if (name !== spec.name || path !== spec.expectedPath || !entry) return null;

  const slots = Array.isArray(raw.slots)
    ? raw.slots.filter((value): value is string => typeof value === "string")
    : undefined;

  return {
    name,
    label: asString(raw.label) || name,
    description: asString(raw.description),
    icon: asString(raw.icon) || "Puzzle",
    version: asString(raw.version),
    tab: {
      path,
      position: asString(tab.position) || undefined,
      override: asString(tab.override) || undefined,
      hidden: typeof tab.hidden === "boolean" ? tab.hidden : undefined,
    },
    slots,
    entry,
    css: typeof raw.css === "string" ? raw.css : null,
    has_api: Boolean(raw.api),
    integrity: asString(raw.integrity) || undefined,
    source: "bundled",
  };
}

async function recoverOneBundledManifest(
  spec: RecoverySpec,
): Promise<PluginManifest | null> {
  const url =
    `${HERMES_BASE_PATH}/dashboard-plugins/${encodeURIComponent(spec.name)}/manifest.json` +
    `?hermes_manifest_recovery=${Date.now()}`;

  try {
    const response = await fetch(url, {
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) return null;
    return normalizeBundledManifest(await response.json(), spec);
  } catch {
    return null;
  }
}

/**
 * Recover application-owned bundled dashboard manifests that are physically
 * available but were omitted from the discovery response by stale visibility
 * state. The static asset endpoint still enforces explicit plugin disablement,
 * so this never revives a bundled plugin the user intentionally disabled.
 */
export async function recoverBundledDashboardManifests(
  manifests: PluginManifest[],
): Promise<PluginManifest[]> {
  const recovered = [...manifests];
  const names = new Set(recovered.map((manifest) => manifest.name));

  for (const spec of RECOVERABLE_BUNDLED_DASHBOARD_PLUGINS) {
    if (names.has(spec.name)) continue;
    const manifest = await recoverOneBundledManifest(spec);
    if (!manifest) continue;
    recovered.push(manifest);
    names.add(manifest.name);
  }

  return recovered;
}
