import { describe, expect, it } from "vitest";
import { apiPath, isLocalArtifact, nextOperation, statusLabel, visibleEpisodes } from "./production";

describe("production desk workflow", () => {
  it("uses the same-origin API proxy instead of calling a separate UI backend", () => {
    expect(apiPath("episodes")).toBe("/api/episodes");
    expect(apiPath("/episodes")).toBe("/api/episodes");
  });

  it("routes an approved script to the storyboard job", () => {
    expect(nextOperation("script_approved")).toEqual({ kind: "storyboard", label: "Generate storyboard" });
  });

  it("keeps review work human-gated and filters failed jobs accurately", () => {
    expect(nextOperation("awaiting_asset_review")).toEqual({ gate: "assets", label: "Approve storyboard & unlock image upload" });
    expect(visibleEpisodes([{ id: "a", status: "assets_ready" }], "failed", { a: [{ id: "job", kind: "video", status: "failed" }] })).toHaveLength(1);
  });

  it("exposes every queue view without turning a queued job into a failure", () => {
    const episodes = [
      { id: "review", status: "awaiting_script_review" }, { id: "run", status: "assets_ready" },
      { id: "failed", status: "assets_ready" }, { id: "state", status: "failed" }, { id: "done", status: "published" }
    ];
    const jobs = { run: [{ id: "r", kind: "assets", status: "queued" }], failed: [{ id: "f", kind: "video", status: "failed" }] };
    expect(visibleEpisodes(episodes, "all", jobs)).toHaveLength(5);
    expect(visibleEpisodes(episodes, "review", jobs).map((item) => item.id)).toEqual(["review"]);
    expect(visibleEpisodes(episodes, "running", jobs).map((item) => item.id)).toEqual(["run"]);
    expect(visibleEpisodes(episodes, "final", jobs)).toHaveLength(0);
    expect(visibleEpisodes(episodes, "failed", jobs).map((item) => item.id)).toEqual(["failed", "state"]);
    expect(visibleEpisodes(episodes, "published", jobs).map((item) => item.id)).toEqual(["done"]);
  });

  it("handles terminal states and only treats non-mock paths as real artifacts", () => {
    expect(nextOperation("published")).toBeNull();
    expect(isLocalArtifact("C:/outputs/scene.png")).toBe(true);
    expect(isLocalArtifact("mock://scene.png")).toBe(false);
    expect(isLocalArtifact(undefined)).toBe(false);
    expect(statusLabel("awaiting_final_review")).toBe("awaiting final review");
  });
});
