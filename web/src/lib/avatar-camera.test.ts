import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

interface FitArgs {
  width?: number;
  height?: number;
  depth?: number;
  fovDegrees?: number;
  aspect?: number;
  padding?: number;
}

type FitDistance = (args?: FitArgs) => number;

function loadFitDistance(): FitDistance {
  const source = readFileSync(
    new URL(
      "../../../plugins/hermes-avatar/dashboard/dist/three-avatar-renderer.js",
      import.meta.url,
    ),
    "utf8",
  );
  const host: {
    __HERMES_PLUGIN_SDK__: object;
    __HERMES_AVATAR_RENDERER__?: {
      perspectiveFitDistance?: FitDistance;
    };
  } = { __HERMES_PLUGIN_SDK__: {} };

  new Function("window", source)(host);
  const fit = host.__HERMES_AVATAR_RENDERER__?.perspectiveFitDistance;
  if (!fit) throw new Error("Avatar renderer did not expose perspectiveFitDistance");
  return fit;
}

describe("perspectiveFitDistance", () => {
  it("moves a full-body avatar farther back than the old fixed camera distance", () => {
    const fit = loadFitDistance();
    const distance = fit({
      width: 1.2,
      height: 3.25,
      depth: 0.5,
      fovDegrees: 28,
      aspect: 1.2,
    });

    expect(distance).toBeGreaterThan(7);
  });

  it("accounts for canvas aspect ratio so narrow layouts do not crop the model", () => {
    const fit = loadFitDistance();
    const wide = fit({
      width: 3,
      height: 2,
      depth: 0.5,
      fovDegrees: 28,
      aspect: 1.8,
    });
    const narrow = fit({
      width: 3,
      height: 2,
      depth: 0.5,
      fovDegrees: 28,
      aspect: 0.5,
    });

    expect(narrow).toBeGreaterThan(wide);
  });
});
