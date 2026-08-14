"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiPath, Episode, Job, nextOperation, QueueFilter, Scene, statusLabel, visibleEpisodes } from "../lib/production";

type Details = { jobs: Job[]; reviews: Array<{ gate: string; decision: string; note?: string; created_at?: string }> };
type ProviderStatus = Record<string, { mode?: string; configured?: boolean }>;

const filters: QueueFilter[] = ["all", "review", "running", "failed", "final", "published"];
const stamp = (value?: string) => value ? new Date(value).toLocaleString() : "not recorded";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function ProductionDesk() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [providers, setProviders] = useState<ProviderStatus>({});
  const [selectedId, setSelectedId] = useState<string>();
  const [details, setDetails] = useState<Record<string, Details>>({});
  const [filter, setFilter] = useState<QueueFilter>("all");
  const [notice, setNotice] = useState("Loading production record...");
  const [error, setError] = useState("");
  const [projectDialog, setProjectDialog] = useState(false);
  const [reviewGate, setReviewGate] = useState<string>();

  const refresh = useCallback(async () => {
    try {
      const [loadedEpisodes, loadedProviders] = await Promise.all([request<Episode[]>("episodes"), request<ProviderStatus>("providers")]);
      setEpisodes(loadedEpisodes);
      setProviders(loadedProviders);
      setSelectedId((old) => old && loadedEpisodes.some((episode) => episode.id === old) ? old : loadedEpisodes[0]?.id);
      setNotice(`Connected to FastAPI - ${loadedEpisodes.length} episode(s) loaded`);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not reach the API");
      setNotice("Backend unavailable");
    }
  }, []);

  const loadDetails = useCallback(async (episodeId: string) => {
    try {
      const [jobs, reviews] = await Promise.all([request<Job[]>(`episodes/${episodeId}/jobs`), request<Details["reviews"]>(`episodes/${episodeId}/reviews`)]);
      setDetails((old) => ({ ...old, [episodeId]: { jobs, reviews } }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load episode details");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { if (selectedId) void loadDetails(selectedId); }, [selectedId, loadDetails]);

  const selected = episodes.find((episode) => episode.id === selectedId);
  const jobsByEpisode = useMemo(() => Object.fromEntries(Object.entries(details).map(([id, value]) => [id, value.jobs])), [details]);
  const queue = visibleEpisodes(episodes, filter, jobsByEpisode);

  const runJob = async (kind: string) => {
    if (!selected) return;
    try {
      setError("");
      setNotice(`Running ${kind}...`);
      await request(`episodes/${selected.id}/jobs/${kind}/run`, { method: "POST" });
      await refresh();
      await loadDetails(selected.id);
      setNotice(kind === "assets" ? "Veo 3.1 prompt preparation is queued in the background." : `${kind} completed`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Job failed"); }
  };

  const uploadSceneImage = async (sceneNumber: number, image: File) => {
    if (!selected) throw new Error("No episode is selected");
    const body = new FormData();
    body.set("image", image);
    setError("");
    setNotice(`Uploading image for scene ${sceneNumber}...`);
    const response = await fetch(apiPath(`episodes/${selected.id}/scenes/${sceneNumber}/image`), { method: "POST", body });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.detail ?? "Image upload failed");
    }
    await refresh();
    await loadDetails(selected.id);
    setNotice("Scene image saved. The final upload prepares every Veo 3.1 prompt.");
  };

  const uploadSceneVideo = async (sceneNumber: number, video: File) => {
    if (!selected) throw new Error("No episode is selected");
    const body = new FormData();
    body.set("video", video);
    setError("");
    setNotice(`Uploading video for scene ${sceneNumber}...`);
    const response = await fetch(apiPath(`episodes/${selected.id}/scenes/${sceneNumber}/video`), { method: "POST", body });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.detail ?? "Video upload failed");
    }
    await refresh();
    await loadDetails(selected.id);
    setNotice("Scene video saved. The final upload opens final review.");
  };

  const review = async (decision: "approved" | "changes_requested", note: string) => {
    if (!selected || !reviewGate) return;
    try {
      await request(`episodes/${selected.id}/reviews`, { method: "POST", body: JSON.stringify({ gate: reviewGate, decision, note }) });
      setReviewGate(undefined);
      await refresh();
      await loadDetails(selected.id);
      setNotice("Review decision recorded");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Review could not be recorded"); }
  };

  const createProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await request("projects", { method: "POST", body: JSON.stringify({ name: form.get("name"), description: form.get("description") }) });
      setProjectDialog(false);
      await refresh();
      setNotice("Project created");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create project"); }
  };

  const autoProduceEpisode = async () => {
    try {
      setError("");
      setNotice("Finding a new source and preparing its script and storyboard...");
      const episode = await request<Episode>("episodes/auto-produce", { method: "POST" });
      await refresh();
      setSelectedId(episode.id);
      await loadDetails(episode.id);
      setNotice(`Created ${episode.title} through storyboard. Export its CSV, then upload the scene images.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not automatically produce an episode"); }
  };

  return <main className="app-shell">
    <a className="skip" href="#workspace">Skip to workspace</a>
    <header className="topbar"><div><p className="eyebrow">Nightmare Studio / live production desk</p><h1>From dread to delivery.</h1><p>One operational surface for source, review gates, scene media and output truth.</p></div><div className="top-actions"><span className={`connection ${error ? "bad" : "ok"}`}>{error ? "API unavailable" : `Studio database - ${episodes.length} stored episode${episodes.length === 1 ? "" : "s"}`}</span><button className="button" onClick={() => void refresh()}>Refresh</button><button className="button" onClick={() => setProjectDialog(true)}>New project</button><button className="button primary" onClick={() => void autoProduceEpisode()}>New episode</button></div></header>
    <section className="metrics" aria-label="Queue summary"><Metric label="All work" value={episodes.length}/><Metric label="At review" value={visibleEpisodes(episodes, "review", jobsByEpisode).length}/><Metric label="Final review" value={visibleEpisodes(episodes, "final", jobsByEpisode).length}/><Metric label="Failures" value={visibleEpisodes(episodes, "failed", jobsByEpisode).length}/></section>
    <p className={`notice ${error ? "error" : ""}`}>{error || notice}</p>
    <div className="layout"><aside className="panel queue"><div className="panel-head"><div><p className="eyebrow">Production queue</p><h2>Episodes</h2></div><span className="state">{queue.length}</span></div><div className="filters">{filters.map((item) => <button className={`filter ${filter === item ? "active" : ""}`} onClick={() => setFilter(item)} key={item}>{item}</button>)}</div><div className="episode-list">{queue.map((episode) => <button className={`episode ${episode.id === selectedId ? "selected" : ""}`} key={episode.id} onClick={() => setSelectedId(episode.id)}><i className={`dot ${episode.status.startsWith("awaiting") ? "review" : episode.status === "published" ? "ready" : ""}`}/><span><strong>{episode.title}</strong><small>{statusLabel(episode.status)}</small></span><time>{stamp(episode.updated_at)}</time></button>)}{!queue.length && <div className="empty"><p>No episodes in this filter.</p><button className="button primary" onClick={() => void autoProduceEpisode()}>New episode</button></div>}</div></aside><section className="desk" id="workspace">{selected ? <Workspace episode={selected} details={details[selected.id] ?? { jobs: [], reviews: [] }} providers={providers} onRun={runJob} onReview={setReviewGate} onUpload={uploadSceneImage}/> : <section className="panel empty"><h2>No episode selected</h2><p>New episode finds a source, writes the script, and builds the storyboard automatically.</p><button className="button primary" onClick={() => void autoProduceEpisode()}>New episode</button></section>}</section></div>
    {projectDialog && <Modal title="Create project" onClose={() => setProjectDialog(false)}><form className="form" onSubmit={createProject}><Field label="Name"><input required name="name" maxLength={160}/></Field><Field label="Description"><textarea name="description" maxLength={2000}/></Field><Actions onCancel={() => setProjectDialog(false)} submit="Create project"/></form></Modal>}
    {reviewGate && <Modal title={`${reviewGate} review`} onClose={() => setReviewGate(undefined)}><form className="form" onSubmit={(event) => { event.preventDefault(); void review("approved", String(new FormData(event.currentTarget).get("note") ?? "")); }}><Field label="Review note"><textarea required name="note" maxLength={4000}/></Field><div className="action-row"><button type="button" className="button" onClick={() => setReviewGate(undefined)}>Cancel</button><button type="button" className="button danger" onClick={(event) => { const form = event.currentTarget.form; if (form) void review("changes_requested", String(new FormData(form).get("note") ?? "")); }}>Request changes</button><button className="button primary" type="submit">Approve</button></div></form></Modal>}
  </main>;
}

function Workspace({ episode, details, providers, onRun, onReview, onUpload }: { episode: Episode; details: Details; providers: ProviderStatus; onRun: (kind: string) => void; onReview: (gate: string) => void; onUpload: (sceneNumber: number, image: File) => Promise<void> }) {
  const operation = nextOperation(episode.status);
  const scenes = episode.storyboard ?? [];
  const canUpload = episode.status === "assets_approved";
  const canUploadVideo = episode.status === "assets_ready";
  const canReviseVideo = ["video_ready", "awaiting_final_review"].includes(episode.status);
  return <><section className="panel workspace"><div className="workspace-title"><div><p className="eyebrow">Episode workspace</p><h2>{episode.title}</h2><p>{episode.source_url || "Manual source / editorial brief"} - updated {stamp(episode.updated_at)}</p></div><span className="state review">{statusLabel(episode.status)}</span></div><div className="next-action"><div><p>Next valid operation</p><strong>{operation?.label ?? "No further operation"}</strong></div>{operation?.kind && <button className="button primary" onClick={() => onRun(operation.kind!)}>{operation.label}</button>}{operation?.gate && <button className="button primary" onClick={() => onReview(operation.gate!)}>{operation.label}</button>}</div><div className="section-grid"><section className="panel-inner"><p className="eyebrow">Editorial record</p><h3>Source & script</h3><Field label="Final script"><textarea readOnly value={episode.script_final || episode.script_draft || "Script is generated by the rewrite job."}/></Field><details><summary>Review history ({details.reviews.length})</summary>{details.reviews.map((item, index) => <p className="log-row" key={index}><strong>{item.gate} - {item.decision}</strong><small>{item.note || "No note"} - {stamp(item.created_at)}</small></p>)}</details></section><aside className="panel-inner"><p className="eyebrow">Provider preflight</p><h3>Truthful status</h3><Provider name="LLM" state={providers.llm}/><Provider name="Media" state={providers.media}/><p className="caution">Images and finished clips are supplied by you. FFmpeg keeps original clip audio; the LLM chooses each scene's trim and playback pace.</p></aside></div></section><section className="panel block"><p className="eyebrow">Scene production</p><h3>Storyboard & media record <span className="state">{scenes.length} scenes</span></h3>{canUpload ? <BatchImageUploader episodeId={episode.id} sceneCount={scenes.length}/> : canUploadVideo ? <BatchVideoUploader episodeId={episode.id} sceneCount={scenes.length}/> : canReviseVideo ? <MediaRevisionButton episodeId={episode.id}/> : <p className="caution">You are the reviewer: approve the storyboard to unlock ordered batch upload.</p>}<div className="scene-grid">{scenes.length ? scenes.map((scene) => <SceneCard key={scene.number} scene={scene} canUpload={canUpload} onUpload={onUpload}/>) : <p className="empty">Generate a storyboard to expose scene prompts and media paths.</p>}</div></section><section className="panel block"><p className="eyebrow">Jobs & recovery</p><h3>Job log</h3>{details.jobs.length ? details.jobs.map((job) => <article className="job" key={job.id}><div className="row"><strong>{job.kind}</strong><span className={`state ${job.status === "failed" ? "failed" : ""}`}>{job.status} - {job.progress ?? 0}%</span></div><small>{stamp(job.created_at)} to {stamp(job.completed_at)}</small>{job.error && <p className="job-error">{job.error}</p>}</article>) : <p className="empty">No job has run yet.</p>}</section></>;
}

function BatchImageUploader({ episodeId, sceneCount }: { episodeId: string; sceneCount: number }) {
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  return <section className="panel-inner"><p className="eyebrow">Ordered batch upload</p><h4>Upload all {sceneCount} scene images once</h4><p className="caution">Name files by scene number, for example scene-001.png or scene_1_image.jpg. The app maps each image to that scene automatically.</p><label className="field"><span>Select ordered scene images</span><input type="file" multiple accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={async (event) => { const files = Array.from(event.currentTarget.files ?? []); if (!files.length) return; const body = new FormData(); files.forEach((file) => body.append("images", file)); setUploading(true); setError(""); try { const response = await fetch(apiPath(`episodes/${episodeId}/scene-images`), { method: "POST", body }); if (!response.ok) { const problem = await response.json().catch(() => ({})); throw new Error(problem.detail ?? "Batch image upload failed"); } window.location.reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Batch image upload failed"); } finally { setUploading(false); }}}/>{uploading && <small>Uploading ordered images...</small>}{error && <small>{error}</small>}</label></section>;
}

function BatchVideoUploader({ episodeId, sceneCount }: { episodeId: string; sceneCount: number }) {
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  return <section className="panel-inner"><p className="eyebrow">Ordered scene-video upload</p><h4>Upload all {sceneCount} finished clips once</h4><p className="caution">Name clips scene-001.mp4 or scene_1_video.mov. The LLM reads each clip's actual duration, chooses tense slow/fast trims, then FFmpeg preserves original clip audio.</p><label className="field"><span>Select ordered scene videos</span><input type="file" multiple accept="video/mp4,video/quicktime,video/webm" disabled={uploading} onChange={async (event) => { const files = Array.from(event.currentTarget.files ?? []); if (!files.length) return; const body = new FormData(); files.forEach((file) => body.append("videos", file)); setUploading(true); setError(""); try { const response = await fetch(apiPath(`episodes/${episodeId}/scene-videos`), { method: "POST", body }); if (!response.ok) { const problem = await response.json().catch(() => ({})); throw new Error(problem.detail ?? "Batch video upload failed"); } window.location.reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Batch video upload failed"); } finally { setUploading(false); }}}/>{uploading && <small>Saving local video files...</small>}{error && <small>{error}</small>}</label></section>;
}

function MediaRevisionButton({ episodeId }: { episodeId: string }) { const [error, setError] = useState(""); const [working, setWorking] = useState(false); return <section className="panel-inner"><p className="eyebrow">Media revision</p><h4>Replace uploaded scene videos</h4><p className="caution">The previous final remains on disk. Start a revision to reopen batch video upload and assemble a new cut.</p><button className="button primary" disabled={working} onClick={async () => { setWorking(true); setError(""); try { const response = await fetch(apiPath(`episodes/${episodeId}/media-revision`), { method: "POST" }); if (!response.ok) { const problem = await response.json().catch(() => ({})); throw new Error(problem.detail ?? "Could not start media revision"); } window.location.reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start media revision"); } finally { setWorking(false); }}}>Start media revision</button>{error && <small>{error}</small>}</section>; }

function SceneCard({ scene, canUpload, onUpload }: { scene: Scene; canUpload: boolean; onUpload: (sceneNumber: number, image: File) => Promise<void> }) {
  const isLegacyPlaceholder = (path?: string | null) => path?.startsWith("mock://") ?? false;
  const hasImage = Boolean(scene.asset_path) && !isLegacyPlaceholder(scene.asset_path);
  const hasVideo = Boolean(scene.video_path) && !isLegacyPlaceholder(scene.video_path);
  return <article className="scene"><div className="row"><h4>Scene {scene.number}</h4><span className="state">{hasImage ? "image uploaded" : "awaiting image"}</span></div><p>{scene.narration}</p><p><strong>Shot:</strong> {scene.shot}</p><p><strong>Directed screen time:</strong> {scene.target_duration_seconds ?? 5}s (max 5s)</p><Field label="Image prompt"><textarea readOnly value={scene.prompt ?? "Not generated"}/></Field>{canUpload ? <SceneUploader sceneNumber={scene.number} onUpload={onUpload}/> : <p className="caution">You are the reviewer: approve this storyboard first to unlock image upload.</p>}<Field label="Veo 3.1 video prompt"><textarea readOnly value={scene.motion_prompt ?? "Prepared automatically after all scene images are uploaded."}/></Field><p className="artifact">Image: {hasImage ? scene.asset_path : "not uploaded"}</p><p className="artifact">Clip: {hasVideo ? scene.video_path : "not generated"}</p></article>;
}

function SceneUploader({ sceneNumber, onUpload }: { sceneNumber: number; onUpload: (sceneNumber: number, image: File) => Promise<void> }) {
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  return <label className="field"><span>Upload or replace scene image</span><input type="file" accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={async (event) => { const file = event.currentTarget.files?.[0]; if (!file) return; setUploading(true); setError(""); try { await onUpload(sceneNumber, file); event.currentTarget.value = ""; } catch (reason) { setError(reason instanceof Error ? reason.message : "Image upload failed"); } finally { setUploading(false); } }}/>{uploading && <small>Uploading...</small>}{error && <small>{error}</small>}</label>;
}

function Provider({ name, state }: { name: string; state?: { mode?: string; configured?: boolean } }) { const ready = state?.configured; return <div className="provider"><div className="row"><strong>{name}</strong><span className={`state ${ready ? "ready" : "review"}`}>{ready ? "configured" : "not configured"}</span></div><small>{ready ? state?.mode : "Configuration required"}</small></div>; }
function Metric({ label, value }: { label: string; value: number }) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="field"><span>{label}</span>{children}</label>; }
function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) { return <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label={title}><div className="row"><h2>{title}</h2><button className="icon" onClick={onClose} aria-label="Close">x</button></div>{children}</section></div>; }
function Actions({ onCancel, submit }: { onCancel: () => void; submit: string }) { return <div className="action-row"><button type="button" className="button" onClick={onCancel}>Cancel</button><button className="button primary" type="submit">{submit}</button></div>; }
