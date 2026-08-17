export interface SidebarPluginManifestLike {
  tab: {
    path: string;
    position?: string;
    override?: string;
    hidden?: boolean;
  };
}

function anchoredTarget(position?: string): string | null {
  if (!position) return null;
  if (position.startsWith("after:")) {
    return `/${position.slice(6)}`;
  }
  if (position.startsWith("before:")) {
    return `/${position.slice(7)}`;
  }
  return null;
}

/**
 * Return plugin paths whose explicit before:/after: position anchors them to
 * an existing built-in sidebar item.
 *
 * The dashboard renders unanchored plugin tabs in a dedicated Plugins group,
 * but an explicit relative position is part of the plugin contract and must
 * stay inline with its target. Keeping this policy in a pure helper makes the
 * host navigation deterministic and independently testable.
 */
export function anchoredSidebarPluginPaths(
  manifests: SidebarPluginManifestLike[],
  builtInPaths: ReadonlySet<string>,
): Set<string> {
  const anchored = new Set<string>();

  for (const manifest of manifests) {
    if (manifest.tab.override || manifest.tab.hidden) continue;
    const target = anchoredTarget(manifest.tab.position);
    if (target && builtInPaths.has(target)) {
      anchored.add(manifest.tab.path);
    }
  }

  return anchored;
}
