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
export type Operation = { kind?: string; gate?: string; label: string } | null;

const jobOperations: Record<string, Operation> = {
  discovered: { kind: "rewrite", label: "Run rewrite" },
  selected: { kind: "rewrite", label: "Run rewrite" },
  script_approved: { kind: "storyboard", label: "Generate storyboard" },
  assets_approved: { label: "Upload scene images below" },
  assets_ready: { label: "Upload scene videos below" },
  audio_ready: { kind: "video", label: "Generate scene video clips" },
  final_approved: { kind: "publish", label: "Record publication handoff" }
};

const gateOperations: Record<string, Operation> = {
  awaiting_script_review: { gate: "script", label: "Review script" },
  awaiting_asset_review: { gate: "assets", label: "Approve storyboard & unlock image upload" },
  awaiting_final_review: { gate: "final", label: "Review final package" }
};

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
