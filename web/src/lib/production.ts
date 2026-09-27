export type EpisodeStatus = string;

export type Scene = {
  number: number;
  narration?: string;
  shot?: string;
  prompt?: string;
  motion_prompt?: string;
  target_duration_seconds?: number;
  asset_path?: string;
  video_path?: string;
};

export type Episode = {
  id: string;
  project_id: string;
  title: string;
  source_url?: string;
  source_text?: string;
  status: EpisodeStatus;
  script_draft?: string;
  script_final?: string;
  storyboard?: Scene[];
  updated_at?: string;
};

export type Job = { id: string; kind: string; status: string; progress?: number; error?: string; created_at?: string; completed_at?: string };
export type QueueFilter = "all" | "review" | "running" | "failed" | "final" | "published";
export type Operation = { kind?: string; gate?: string; transition?: string; label: string } | null;

const jobOperations: Record<string, Operation> = {
  discovered: { kind: "rewrite", label: "Run rewrite" },
  selected: { kind: "rewrite", label: "Run rewrite" },
  rewritten: { transition: "awaiting_script_review", label: "Send draft to script review" },
  script_approved: { kind: "storyboard", label: "Generate storyboard" },
  assets_approved: { label: "Upload scene images below" },
  assets_ready: { label: "Upload scene videos below" },
  audio_ready: { kind: "video", label: "Generate scene video clips" },
  video_ready: { transition: "awaiting_final_review", label: "Send assembled video to final review" },
  final_approved: { kind: "publish", label: "Record publication handoff" }
};

const gateOperations: Record<string, Operation> = {
  awaiting_script_review: { gate: "script", label: "Review script" },
  awaiting_asset_review: { gate: "assets", label: "Approve storyboard & unlock image upload" },
  awaiting_final_review: { gate: "final", label: "Review final package" }
};

/** Canonical happy-path order used to render the status stepper. */
export const episodeFlow: string[] = [
  "discovered", "selected", "rewritten", "awaiting_script_review", "script_approved",
  "storyboarded", "awaiting_asset_review", "assets_approved", "assets_ready",
  "audio_ready", "video_ready", "awaiting_final_review", "final_approved", "published"
];

/**
 * Offline fallback for the operator override table. The live source of truth is
 * GET /api/episodes/{id}/transitions (app/domain.py `_TRANSITIONS`); this map is
 * used only while that fetch has not returned yet.
 */
const transitionMap: Record<string, string[]> = {
  discovered: ["selected", "rewritten", "failed"],
  selected: ["rewritten", "failed"],
  rewritten: ["awaiting_script_review", "failed"],
  awaiting_script_review: ["script_approved", "failed"],
  script_approved: ["storyboarded", "failed"],
  storyboarded: ["awaiting_asset_review", "failed"],
  awaiting_asset_review: ["assets_approved", "failed"],
  assets_approved: ["assets_ready", "failed"],
  assets_ready: ["audio_ready", "video_ready", "failed"],
  audio_ready: ["video_ready", "failed"],
  video_ready: ["assets_ready", "awaiting_final_review", "failed"],
  awaiting_final_review: ["assets_ready", "final_approved", "failed"],
  final_approved: ["published", "failed"],
  published: [],
  failed: ["selected", "rewritten", "storyboarded"]
};

export function stateTransitions(status: string): string[] { return transitionMap[status] ?? []; }
export function flowIndex(status: string): number { return episodeFlow.indexOf(status); }

export function apiPath(path = ""): string { return `/api/${path.replace(/^\/+/, "")}`; }
export function nextOperation(status: EpisodeStatus): Operation { return gateOperations[status] ?? jobOperations[status] ?? null; }
export function statusLabel(status: string): string { return status.replaceAll("_", " "); }
export function isLocalArtifact(path: string | undefined): boolean { return Boolean(path && !path.startsWith("mock://")); }
export function visibleEpisodes<T extends Pick<Episode, "id" | "status">>(episodes: T[], filter: QueueFilter, jobsByEpisode: Record<string, Job[]> = {}): T[] {
  return episodes.filter((episode) => {
    const jobs = jobsByEpisode[episode.id] ?? [];
    if (filter === "all") return true;
    if (filter === "review") return episode.status.startsWith("awaiting_");
    if (filter === "final") return episode.status === "awaiting_final_review";
    if (filter === "published") return episode.status === "published";
    if (filter === "running") return jobs.some((job) => ["queued", "running"].includes(job.status));
    return episode.status === "failed" || jobs.some((job) => job.status === "failed");
  });
}
