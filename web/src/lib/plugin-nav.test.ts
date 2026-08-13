import { describe, expect, it } from "vitest";

import { anchoredSidebarPluginPaths } from "./plugin-nav";

describe("anchoredSidebarPluginPaths", () => {
  it("keeps before/after plugins inline when their built-in target exists", () => {
    const paths = anchoredSidebarPluginPaths(
      [
        {
          tab: {
            path: "/digital-human",
            position: "after:chat",
          },
        },
        {
          tab: {
            path: "/achievements",
            position: "after:analytics",
          },
        },
      ],
      new Set(["/chat", "/analytics", "/sessions"]),
    );

    expect([...paths]).toEqual(["/digital-human", "/achievements"]);
  });

  it("leaves end, hidden, override, and unresolved anchors in the plugin group", () => {
    const paths = anchoredSidebarPluginPaths(
      [
        { tab: { path: "/end-plugin", position: "end" } },
        { tab: { path: "/hidden", position: "after:chat", hidden: true } },
        { tab: { path: "/override", position: "after:chat", override: "/chat" } },
        { tab: { path: "/missing", position: "after:not-present" } },
      ],
      new Set(["/chat", "/sessions"]),
    );

    expect([...paths]).toEqual([]);
  });
});
