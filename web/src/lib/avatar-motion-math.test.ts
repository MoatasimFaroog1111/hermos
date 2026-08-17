import { describe, expect, it } from "vitest";

function speechEnergy(state: string, mouthOpen: number, jaw: number, mouthWide: number): number {
  if (state !== "speaking") return 0;
  return Math.min(1, Math.max(0, 0.18 + mouthOpen * 0.52 + jaw * 0.34 + mouthWide * 0.12));
}

describe("Digital Human motion math", () => {
  it("keeps speech gestures off while idle", () => {
    expect(speechEnergy("idle", 1, 1, 1)).toBe(0);
  });

  it("increases gesture energy with speaking articulation", () => {
    const quiet = speechEnergy("speaking", 0.05, 0.02, 0.1);
    const emphatic = speechEnergy("speaking", 0.8, 0.6, 0.7);
    expect(quiet).toBeGreaterThan(0);
    expect(emphatic).toBeGreaterThan(quiet);
  });
});
