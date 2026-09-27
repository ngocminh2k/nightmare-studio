/* ============================================
   Nightmare Studio · API layer
   - mock backend in browser (state machine + jobs)
   - real backend adapter via window.NS_API_BASE
   ============================================ */
(function (global) {
  "use strict";

  const NS_API_BASE = () => (global.NS_API_BASE || "").replace(/\/$/, "");
  const USE_REMOTE  = () => !!NS_API_BASE();

  const db = () => global.__NSDB;

  /* ---------- helpers ---------- */
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const log = (ep, lvl, msg) => db().addLog(ep, lvl, msg);

  async function ensure() { if (!global.__NSDB) global.__NSDB = await new NSDatabase().init(); return global.__NSDB; }

  function reject(msg, code = 400) { const e = new Error(msg); e.status = code; return e; }

  function gateLabel(stateId) {
    return NS_STAGES.find((s) => s.id === stateId) || null;
  }

  /* ---------- provider hooks (mock) ---------- */
  const Providers = {
    async rewrite(text, brandBible) {
      await sleep(900);
      const lines = (text || "").split(/\n+/).map((l) => l.trim()).filter(Boolean);
      const voiceLines = lines.length ? lines : [
        "Ngôi nhà ở cuối đường Harkness vẫn đứng đó, ánh đèn hắt qua khung cửa sổ tầng hai.",
        "Bà Whitmore kéo chăn lên đến cằm, nhưng tiếng bước chân ở hành lang thì đã gần hơn rất nhiều so với đêm qua.",
        "Đồng hồ trên tường chỉ mười một giờ mười lăm, nhưng cô ấy đã thức từ nửa đêm — và không, không ai khác cũng thức."
      ];
      const merged = voiceLines.join(" ").replace(/\s+/g, " ").trim();
      const rewritten = merged
          .replace(/\.\s+/g, ". ")
          .replace(/(ngôi nhà|bước chân|hành lang|đèn)/gi, (m) => m);
      const footer = brandBible ? `\n\n[voice applied: ${brandBible.slice(0, 60)}]` : "";
      return {
        text: rewritten + footer,
        words: rewritten.split(/\s+/).filter(Boolean).length,
        provider: "mock-mrkane",
        model: "mrkane (mock)",
        latency_ms: 900
      };
    },
    async storyboard(scriptText) {
      await sleep(700);
      const sentences = (scriptText || "").split(/(?<=[.!?])\s+/).filter(Boolean);
      const pick = sentences.length ? sentences : [
        "Mở cảnh — ngôi nhà giữa đường Harkness vào đêm khuya.",
        "Bà Whitmore ngồi trên giường, ánh mắt dán vào cửa.",
        "Tiếng bước chân vang lên ở hành lang — closer than last night.",
        "Cánh cửa hé mở, then cửa kêu răng rắc.",
        "Mặt nạ rơi từ kệ — một khuôn mặt quen thuộc.",
        "Bình minh — nhưng bóng tối vẫn còn đó."
      ];
      const shots = ["wide", "closeup", "insert", "wide", "detail", "wide"];
      return pick.slice(0, 8).map((n, i) => ({
        title: `Scene ${String(i + 1).padStart(2, "0")}`,
        narration: n,
        shot: shots[i % shots.length],
        promptHint: n.slice(0, 60)
      }));
    },
    async veoPrompt(scene, brandBible) {
      await sleep(120);
      const ve = "Veo 3.1";
      const tone = brandBible && /first-person|first person/i.test(brandBible) ? "first-person" : "third-person";
      const parts = [
        `${ve} cinematic shot, ${scene.shot || "wide"} framing`,
        "Harkness Road horror aesthetic, desaturated color grade, deep red accent",
        tone === "first-person" ? "first-person POV, subtle handheld sway" : "locked-off tripod, slow creeping push-in",
        `scene subject: ${(scene.narration || "").slice(0, 120)}`,
        "atmospheric fog, volumetric lighting, faint eye-glow where applicable",
        "no on-screen text, no jumpscare audio"
      ];
      return parts.join("; ") + ".";
    },
    async audio(text) {
      await sleep(900);
      return { durationSec: Math.max(8, Math.round((text || "").split(/\s+/).length / 2.5)), format: "wav-48k" };
    },
    async video(scene) {
      await sleep(1400);
      return { clipPath: `outputs/mock/${scene.id || NS_uid()}.mp4`, durationSec: 8, provider: "mock-flow" };
    }
  };

  /* ---------- state ops (mock) ---------- */
  const Ops = {
    async createEpisode(data) {
      if (USE_REMOTE()) return rpost("/api/episodes", data);
      const d = await ensure();
      const ep = await d.createEpisode(data);
      await d.rebuildJobs(ep.id);
      return ep;
    },
    async listEpisodes() {
      if (USE_REMOTE()) return rget("/api/episodes");
      return (await ensure()).listEpisodes();
    },
    async getEpisode(id) {
      if (USE_REMOTE()) return rget(`/api/episodes/${id}`);
      return (await ensure()).getEpisode(id);
    },
    async deleteEpisode(id) {
      if (USE_REMOTE()) return rdel(`/api/episodes/${id}`);
      await (await ensure()).deleteEpisode(id);
    },
    async selectSource(id, url, text) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/select`, { url, text });
      const d = await ensure();
      const cur = await d.getEpisode(id);
      if (!cur) throw reject("Episode not found");
      if (!NS_canTransition(cur.state, "selected")) throw reject(`Invalid transition ${cur.state} → selected`);
      await log(id, "info", `Source selected: ${url || "manual paste"}`);
      return d.updateEpisode(id, { source: { url, text }, state: "selected" });
    },
    async runRewrite(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/rewrite`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!ep) throw reject("Episode not found");
      if (!NS_canTransition(ep.state, "rewritten")) throw reject(`Invalid transition ${ep.state} → rewritten`);
      await log(id, "info", "Rewrite job started");
      const out = await Providers.rewrite(ep.source.text || "", ep.brandBible || "");
      await log(id, "info", `Rewrite done — ${out.words} words, ${out.provider} (${out.latency_ms}ms)`);
      const next = await d.updateEpisode(id, {
        state: "rewritten",
        script: { text: out.text, words: out.words, provider: out.provider, model: out.model, latencyMs: out.latency_ms, decidedAt: null, decision: null, reviewNote: "" }
      });
      const jobs = await d.listJobs(id);
      const j = jobs.find((j) => j.type === "rewrite");
      if (j) await d.updateJob(j.id, { state: "done" });
      return next;
    },
    async submitForScriptReview(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/script-review`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "script_review")) throw reject(`Invalid transition ${ep.state} → script_review`);
      await log(id, "info", "Submitted for script review");
      return d.updateEpisode(id, { state: "script_review" });
    },
    async approveScript(id, note = "") {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/script-review/approve`, { note });
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "storyboard")) throw reject(`Invalid transition ${ep.state} → storyboard`);
      await log(id, "info", `Script approved: ${note || "(no note)"}`);
      const next = await d.updateEpisode(id, { state: "storyboard", script: { ...ep.script, decision: "approve", reviewNote: note, decidedAt: Date.now() } });
      return next;
    },
    async rejectScript(id, note = "") {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/script-review/reject`, { note });
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "rewritten")) throw reject(`Invalid transition ${ep.state} → rewritten`);
      await log(id, "warn", `Script rejected: ${note || "(no note)"}`);
      return d.updateEpisode(id, { state: "rewritten", script: { ...ep.script, decision: "reject", reviewNote: note, decidedAt: Date.now() } });
    },
    async runStoryboard(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/storyboard`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "asset_review")) throw reject(`Invalid transition ${ep.state} → asset_review`);
      await log(id, "info", "Storyboard job started");
      const scenes = await Providers.storyboard(ep.script.text || "");
      const cur = await d.listScenes(id);
      for (const s of cur) await d.deleteScene(s.id);
      for (const s of scenes) await d.addScene(id, s);
      await log(id, "info", `Storyboard ready — ${scenes.length} scenes`);
      const jobs = await d.listJobs(id);
      const j = jobs.find((j) => j.type === "storyboard");
      if (j) await d.updateJob(j.id, { state: "done" });
      return d.updateEpisode(id, { state: "asset_review" });
    },
    async reviseStoryboard(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/asset-review/revise`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "storyboard")) throw reject(`Invalid transition ${ep.state} → storyboard`);
      await log(id, "info", "Storyboard sent back to revision");
      return d.updateEpisode(id, { state: "storyboard" });
    },
    async approveStoryboard(id, note = "") {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/asset-review/approve`, { note });
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "export_csv")) throw reject(`Invalid transition ${ep.state} → export_csv`);
      await log(id, "info", `Asset review approved: ${note || "(no note)"}`);
      return d.updateEpisode(id, { state: "export_csv" });
    },
    async exportCsv(id) {
      if (USE_REMOTE()) return rget(`/api/episodes/${id}/image-prompts.csv`, { raw: true });
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "upload_scenes")) throw reject(`Invalid transition ${ep.state} → upload_scenes`);
      const scenes = await d.listScenes(id);
      const rows = [
        ["scene", "title", "shot", "prompt_hint", "filename"]
      ];
      scenes.forEach((s, i) => {
        const fn = `scene-${String(i + 1).padStart(3, "0")}.png`;
        rows.push([String(i + 1), s.title, s.shot, (s.promptHint || "").replace(/\n/g, " "), fn]);
      });
      const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
      await log(id, "info", `CSV exported (${scenes.length} rows)`);
      const jobs = await d.listJobs(id);
      const j = jobs.find((j) => j.type === "export_csv");
      if (j) await d.updateJob(j.id, { state: "done" });
      const next = await d.updateEpisode(id, { state: "upload_scenes" });
      return { csv, filename: `image_prompts-${id}.csv`, episode: next };
    },
    async commitUpload(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/scenes/commit`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "veo_prompts")) throw reject(`Invalid transition ${ep.state} → veo_prompts`);
      await log(id, "info", "Scene upload committed");
      return d.updateEpisode(id, { state: "veo_prompts" });
    },
    async runVeoPrompts(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/veo-prompts`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "audio")) throw reject(`Invalid transition ${ep.state} → audio`);
      await log(id, "info", "Veo prompt job started");
      const scenes = await d.listScenes(id);
      for (const s of scenes) {
        const p = await Providers.veoPrompt(s, ep.brandBible || "");
        await d.updateScene(s.id, { veoPrompt: p });
      }
      await log(id, "info", `Veo prompts generated — ${scenes.length} scenes`);
      const jobs = await d.listJobs(id);
      const j = jobs.find((j) => j.type === "veo_prompts");
      if (j) await d.updateJob(j.id, { state: "done" });
      return d.updateEpisode(id, { state: "audio" });
    },
    async runAudio(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/audio`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "video")) throw reject(`Invalid transition ${ep.state} → video`);
      await log(id, "info", "Audio job started");
      const scenes = await d.listScenes(id);
      const allText = scenes.map((s) => s.narration).join(" ");
      const out = await Providers.audio(allText);
      await log(id, "info", `Audio done — ${out.durationSec}s ${out.format}`);
      const jobs = await d.listJobs(id);
      const j = jobs.find((j) => j.type === "audio");
      if (j) await d.updateJob(j.id, { state: "done" });
      return d.updateEpisode(id, { state: "video" });
    },
    async runVideo(id) {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/video`, {});
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "final_review")) throw reject(`Invalid transition ${ep.state} → final_review`);
      await log(id, "info", "Video job started (Flow CDP mock)");
      const scenes = await d.listScenes(id);
      for (const s of scenes) {
        const v = await Providers.video(s);
        await d.updateScene(s.id, { videoId: v.clipPath });
      }
      await log(id, "info", `Video done — ${scenes.length} clips`);
      const jobs = await d.listJobs(id);
      const j = jobs.find((j) => j.type === "video");
      if (j) await d.updateJob(j.id, { state: "done" });
      return d.updateEpisode(id, { state: "final_review" });
    },
    async approveFinal(id, note = "") {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/final-review/approve`, { note });
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "publication")) throw reject(`Invalid transition ${ep.state} → publication`);
      await log(id, "info", `Final approved: ${note || "(no note)"}`);
      return d.updateEpisode(id, { state: "publication", finalNote: note, finalDecidedAt: Date.now() });
    },
    async rejectFinal(id, note = "") {
      if (USE_REMOTE()) return rpost(`/api/episodes/${id}/final-review/reject`, { note });
      const d = await ensure();
      const ep = await d.getEpisode(id);
      if (!NS_canTransition(ep.state, "video")) throw reject(`Invalid transition ${ep.state} → video`);
      await log(id, "warn", `Final rejected: ${note || "(no note)"}`);
      return d.updateEpisode(id, { state: "video" });
    },
    async exportManifest(id) {
      const d = await ensure();
      return d.exportEpisode(id);
    }
  };

  /* ---------- remote adapter ---------- */
  async function rget(path, opts = {}) {
    if (opts.raw) return fetch(`${NS_API_BASE()}${path}`);
    const r = await fetch(`${NS_API_BASE()}${path}`);
    if (!r.ok) throw await toErr(r);
    return r.json();
  }
  async function rpost(path, body) {
    const r = await fetch(`${NS_API_BASE()}${path}`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {})
    });
    if (!r.ok) throw await toErr(r);
    return r.json();
  }
  async function rdel(path) {
    const r = await fetch(`${NS_API_BASE()}${path}`, { method: "DELETE" });
    if (!r.ok) throw await toErr(r);
  }
  async function toErr(r) { try { return new Error((await r.json()).detail || r.statusText); } catch (_) { return new Error(r.statusText); } }

  global.NS_Ops = Ops;
  global.NS_Providers = Providers;
  global.NS_useRemote = USE_REMOTE;
  global.NS_apiBase = NS_API_BASE;

})(window);