const state = { projects: [], episodes: [], selectedProjectId: null, selectedEpisodeId: null };

const element = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "The request could not be completed.");
  return payload;
}

function showNotice(message, isError = false) {
  const notice = element("notice");
  notice.textContent = message;
  notice.classList.toggle("error", isError);
}

function renderProjects() {
  const list = element("projects");
  list.innerHTML = state.projects.length ? state.projects.map((project) => `<button class="project-card ${project.id === state.selectedProjectId ? "selected" : ""}" data-project-id="${project.id}" type="button"><strong>${escapeHtml(project.name)}</strong><span>${project.episode_count} episode${project.episode_count === 1 ? "" : "s"}</span></button>`).join("") : '<p class="empty-state">Open a project to begin an editorial slate.</p>';
  list.querySelectorAll("[data-project-id]").forEach((button) => button.addEventListener("click", () => selectProject(button.dataset.projectId)));
}

function renderEpisodes() {
  const episodes = state.selectedProjectId ? state.episodes.filter((episode) => episode.project_id === state.selectedProjectId) : state.episodes;
  const list = element("episodes");
  list.innerHTML = episodes.length ? episodes.map((episode) => `<button class="episode-row ${episode.id === state.selectedEpisodeId ? "selected" : ""}" data-episode-id="${episode.id}" type="button"><span class="status-dot ${episode.status}"></span><span><strong>${escapeHtml(episode.title)}</strong><small>${episode.status.replaceAll("_", " ")}</small></span><span class="cost">$${Number(episode.cost_total).toFixed(2)}</span></button>`).join("") : '<p class="empty-state">No episodes in this queue yet.</p>';
  list.querySelectorAll("[data-episode-id]").forEach((button) => button.addEventListener("click", () => selectEpisode(button.dataset.episodeId)));
}

function actionForStatus(status) {
  const actions = { discovered: ["rewrite", "Draft rewrite"], script_approved: ["storyboard", "Build storyboard"], assets_approved: ["assets", "Generate assets"], assets_ready: ["audio", "Build audio"], audio_ready: ["video", "Render video"], final_approved: ["publish", "Record publication"] };
  return actions[status] || null;
}

function reviewForStatus(status) {
  const reviews = { awaiting_script_review: ["script", "Approve script"], awaiting_asset_review: ["assets", "Approve assets"], awaiting_final_review: ["final", "Approve final" ] };
  return reviews[status] || null;
}

function renderDetail(episode, reviews = [], jobs = []) {
  const detail = element("episode-detail");
  if (!episode) { detail.innerHTML = '<p>Choose an episode to inspect its workflow, review gate, and production actions.</p>'; return; }
  const action = actionForStatus(episode.status);
  const review = reviewForStatus(episode.status);
  const scenes = episode.storyboard.map((scene) => `<li><strong>${scene.number}. ${escapeHtml(scene.shot)}</strong><span>${escapeHtml(scene.narration)}</span><small>${escapeHtml(scene.asset_status)} · ${escapeHtml(scene.prompt)}</small>${scene.motion_prompt ? `<small>Motion: ${escapeHtml(scene.motion_prompt)}</small>` : ""}${scene.video_path ? `<small>Clip: ${escapeHtml(scene.video_path)}</small>` : ""}</li>`).join("");
  const jobRows = jobs.length ? jobs.map((job) => `<li><strong>${escapeHtml(job.kind)}</strong><span>${escapeHtml(job.status)} · ${job.progress}%</span>${job.error ? `<small>${escapeHtml(job.error)}</small>` : ""}</li>`).join("") : "<li>No jobs recorded.</li>";
  const reviewRows = reviews.length ? reviews.map((item) => `<li><strong>${escapeHtml(item.gate)}</strong><span>${escapeHtml(item.decision)}</span><small>${escapeHtml(item.note)}</small></li>`).join("") : "<li>No reviews recorded.</li>";
  detail.innerHTML = `<h3>${escapeHtml(episode.title)}</h3><p class="status-label">${episode.status.replaceAll("_", " ")}</p><dl><div><dt>Source</dt><dd>${episode.source_url ? `<a href="${escapeHtml(episode.source_url)}" target="_blank" rel="noreferrer">Open source</a>` : "Editorial brief"}</dd></div><div><dt>Estimated cost</dt><dd>$${Number(episode.cost_total).toFixed(2)}</dd></div><div><dt>Storyboard</dt><dd>${episode.storyboard.length} scenes</dd></div></dl><label class="editor-label">Editorial script<textarea data-testid="script-editor" id="script-editor">${escapeHtml(episode.script_final || episode.script_draft)}</textarea></label><button class="secondary" data-save-script type="button">Save script</button>${scenes ? `<details open><summary>Scene & asset workspace</summary><ol class="record-list">${scenes}</ol></details>` : ""}<details><summary>Review record</summary><ul class="record-list">${reviewRows}</ul></details><details><summary>Job log</summary><ul class="record-list">${jobRows}</ul></details><a class="manifest-link" href="/api/episodes/${episode.id}/manifest" target="_blank" rel="noreferrer">Open output manifest</a><div class="detail-actions">${action ? `<button class="primary" data-job-kind="${action[0]}" type="button">${action[1]}</button>` : ""}${review ? `<button class="primary" data-review-gate="${review[0]}" type="button">${review[1]}</button><button class="secondary" data-changes-gate="${review[0]}" type="button">Request changes</button>` : ""}</div>`;
  detail.querySelector("[data-save-script]")?.addEventListener("click", () => saveScript(episode.id));
  detail.querySelector("[data-job-kind]")?.addEventListener("click", () => runJob(episode.id, action[0]));
  detail.querySelector("[data-review-gate]")?.addEventListener("click", () => submitReview(episode.id, review[0], "approved"));
  detail.querySelector("[data-changes-gate]")?.addEventListener("click", () => submitReview(episode.id, review[0], "changes_requested"));
}

async function refresh() {
  const [dashboard, projects, episodes, providers] = await Promise.all([request("/api/dashboard"), request("/api/projects"), request("/api/episodes"), request("/api/providers")]);
  state.projects = projects; state.episodes = episodes;
  if (!state.selectedProjectId && projects[0]) state.selectedProjectId = projects[0].id;
  if (state.selectedProjectId && !projects.some((project) => project.id === state.selectedProjectId)) state.selectedProjectId = projects[0]?.id ?? null;
  const selected = episodes.find((episode) => episode.id === state.selectedEpisodeId) || null;
  element("project-count").textContent = dashboard.project_count;
  element("episode-count").textContent = dashboard.episode_count;
  element("cost-total").textContent = `$${Number(dashboard.cost_total).toFixed(2)}`;
  element("provider-summary").textContent = providers.openai.configured ? "AI ready" : "Local";
  element("open-episode-dialog").disabled = !state.selectedProjectId;
  renderProjects(); renderEpisodes(); renderDetail(selected);
}

async function selectProject(projectId) { state.selectedProjectId = projectId; state.selectedEpisodeId = null; renderProjects(); renderEpisodes(); renderDetail(null); }
async function selectEpisode(episodeId) { state.selectedEpisodeId = episodeId; renderEpisodes(); const episode = await request(`/api/episodes/${episodeId}`); const [reviews, jobs] = await Promise.all([request(`/api/episodes/${episodeId}/reviews`), request(`/api/episodes/${episodeId}/jobs`)]); renderDetail(episode, reviews, jobs); }
async function runJob(episodeId, kind) { try { showNotice("Production job running…"); await request(`/api/episodes/${episodeId}/jobs/${kind}/run`, { method: "POST" }); await refresh(); showNotice("Job completed and the case file was updated."); } catch (error) { showNotice(error.message, true); } }
async function submitReview(episodeId, gate, decision) { try { await request(`/api/episodes/${episodeId}/reviews`, { method: "POST", body: JSON.stringify({ gate, decision, note: "Recorded from studio desk" }) }); await refresh(); showNotice(decision === "approved" ? "Review approved." : "Changes requested and recorded."); } catch (error) { showNotice(error.message, true); } }
async function saveScript(episodeId) { try { const scriptFinal = element("script-editor").value; await request(`/api/episodes/${episodeId}`, { method: "PATCH", body: JSON.stringify({ script_final: scriptFinal }) }); await selectEpisode(episodeId); showNotice("Editorial script saved."); } catch (error) { showNotice(error.message, true); } }

element("open-project-dialog").addEventListener("click", () => element("project-dialog").showModal());
element("open-episode-dialog").addEventListener("click", () => element("episode-dialog").showModal());
document.querySelectorAll("[data-dialog-dismiss]").forEach((button) => button.addEventListener("click", () => button.closest("dialog")?.close()));
element("project-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; try { const project = await request("/api/projects", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) }); state.selectedProjectId = project.id; element("project-dialog").close(); form.reset(); await refresh(); showNotice("Project opened."); } catch (error) { showNotice(error.message, true); } });
element("episode-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = event.currentTarget; try { const episode = await request("/api/episodes", { method: "POST", body: JSON.stringify({ ...Object.fromEntries(new FormData(form)), project_id: state.selectedProjectId }) }); state.selectedEpisodeId = episode.id; element("episode-dialog").close(); form.reset(); await refresh(); await selectEpisode(episode.id); showNotice("Episode added to the editorial queue."); } catch (error) { showNotice(error.message, true); } });

refresh().catch((error) => showNotice(error.message, true));
