/* ============================================
   Nightmare Studio · IndexedDB + State Machine
   ============================================ */
(function (global) {
  "use strict";

  /* ---------- 13-stage pipeline (matches README) ---------- */
  const STAGES = [
    { id: "discovered",    name: "Discovered",       isGate: false, hint: "tìm source"           },
    { id: "selected",      name: "Selected",         isGate: false, hint: "chọn source"          },
    { id: "rewritten",     name: "Rewritten",        isGate: false, hint: "LLM rewrite"          },
    { id: "script_review", name: "Script Review",    isGate: true,  hint: "gate 1"               },
    { id: "storyboard",    name: "Storyboard",       isGate: false, hint: "scene split"          },
    { id: "asset_review",  name: "Asset Review",     isGate: true,  hint: "gate 2"               },
    { id: "export_csv",    name: "Export CSV",       isGate: false, hint: "image prompts"        },
    { id: "upload_scenes", name: "Upload Scenes",    isGate: false, hint: "ảnh theo scene"       },
    { id: "veo_prompts",   name: "Veo Prompts",      isGate: false, hint: "final Veo prompt"     },
    { id: "audio",         name: "Audio",            isGate: false, hint: "TTS narration"        },
    { id: "video",         name: "Video",            isGate: false, hint: "Flow CDP clip"        },
    { id: "final_review",  name: "Final Review",     isGate: true,  hint: "gate 3"               },
    { id: "publication",   name: "Publication",      isGate: false, hint: "manifest handoff"     }
  ];

  /* ---------- allowed transitions ---------- */
  const TRANSITIONS = {
    discovered:    ["selected"],
    selected:      ["rewritten"],
    rewritten:     ["script_review"],
    script_review: ["storyboard", "rewritten"],   // approve / re-rewrite
    storyboard:    ["asset_review"],
    asset_review:  ["export_csv", "storyboard"],  // approve / revise
    export_csv:    ["upload_scenes"],
    upload_scenes: ["veo_prompts"],
    veo_prompts:   ["audio"],
    audio:         ["video"],
    video:         ["final_review"],
    final_review:  ["publication", "video"],      // approve / reject to video
    publication:   []
  };

  const STAGE_INDEX = STAGES.reduce((m, s, i) => (m[s.id] = i, m), {});

  function stageIndex(id) { return STAGE_INDEX[id] ?? -1; }
  function nextStage(id) {
    const i = stageIndex(id);
    return i >= 0 && i < STAGES.length - 1 ? STAGES[i + 1].id : null;
  }
  function prevStage(id) {
    const i = stageIndex(id);
    return i > 0 ? STAGES[i - 1].id : null;
  }
  function canTransition(from, to) {
    return (TRANSITIONS[from] || []).includes(to);
  }
  function progressPct(id) {
    const i = stageIndex(id);
    return Math.max(0, Math.min(100, Math.round(((i + 1) / STAGES.length) * 100)));
  }

  /* ---------- IndexedDB ---------- */
  const DB_NAME = "nightmare-studio";
  const DB_VERSION = 1;
  const STORES = ["episodes", "scenes", "jobs", "logs", "assets", "settings"];

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        STORES.forEach((s) => {
          if (!db.objectStoreNames.contains(s)) {
            const opts = s === "settings" ? { keyPath: "key" } : { keyPath: "id" };
            db.createObjectStore(s, opts);
          }
        });
        const eps = req.transaction.objectStore("episodes");
        if (!eps.indexNames.contains("byUpdated")) eps.createIndex("byUpdated", "updatedAt");
        const logs = req.transaction.objectStore("logs");
        if (!logs.indexNames.contains("byEpisode")) logs.createIndex("byEpisode", "episodeId");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function tx(db, store, mode = "readonly") {
    return db.transaction(store, mode).objectStore(store);
  }
  function p(req) { return new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); }); }
  function uid() { return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 9); }

  class NSDatabase {
    constructor() { this.db = null; }
    async init() { if (!this.db) this.db = await openDB(); return this; }

    /* episodes */
    async listEpisodes() {
      await this.init();
      const all = await p(tx(this.db, "episodes").getAll());
      return all.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    }
    async getEpisode(id) {
      await this.init();
      return p(tx(this.db, "episodes").get(id));
    }
    async createEpisode(data = {}) {
      await this.init();
      const now = Date.now();
      const ep = {
        id: uid(),
        title: data.title || "Untitled episode",
        source: data.source || { url: "", text: "" },
        state: "discovered",
        gate: 1,
        brandBible: data.brandBible || "",
        script: { text: "", words: 0, reviewNote: "", decidedAt: null, decision: null },
        storyboard: { notes: "" },
        createdAt: now,
        updatedAt: now
      };
      await p(tx(this.db, "episodes", "readwrite").add(ep));
      await this.addLog(ep.id, "info", `Episode created: ${ep.title}`);
      return ep;
    }
    async updateEpisode(id, patch) {
      await this.init();
      const cur = await this.getEpisode(id);
      if (!cur) throw new Error("Episode not found");
      const next = { ...cur, ...patch, updatedAt: Date.now() };
      next.gate = stageIndex(next.state) + 1;
      await p(tx(this.db, "episodes", "readwrite").put(next));
      return next;
    }
    async deleteEpisode(id) {
      await this.init();
      const stores = ["episodes", "scenes", "jobs", "logs", "assets"];
      for (const s of stores) {
        if (s === "scenes" || s === "jobs" || s === "logs" || s === "assets") {
          const idx = this.db.transaction(s, "readwrite").objectStore(s);
          const all = await p(idx.getAll());
          for (const r of all) {
            if ((s === "scenes" && r.episodeId === id) ||
                (s === "jobs"   && r.episodeId === id) ||
                (s === "logs"   && r.episodeId === id) ||
                (s === "assets" && r.episodeId === id)) {
              await p(idx.delete(r.id));
            }
          }
        } else {
          await p(this.db.transaction(s, "readwrite").objectStore(s).delete(id));
        }
      }
    }

    /* scenes */
    async listScenes(episodeId) {
      await this.init();
      const all = await p(tx(this.db, "scenes").getAll());
      return all.filter((s) => s.episodeId === episodeId).sort((a, b) => a.index - b.index);
    }
    async addScene(episodeId, scene = {}) {
      await this.init();
      const cur = await this.listScenes(episodeId);
      const idx = cur.length + 1;
      const s = {
        id: uid(),
        episodeId,
        index: idx,
        title: scene.title || `Scene ${String(idx).padStart(2, "0")}`,
        narration: scene.narration || "",
        shot: scene.shot || "wide",
        promptHint: scene.promptHint || "",
        veoPrompt: scene.veoPrompt || "",
        assetId: scene.assetId || null,
        audioId: scene.audioId || null,
        videoId: scene.videoId || null,
        createdAt: Date.now()
      };
      await p(tx(this.db, "scenes", "readwrite").add(s));
      await this.addLog(episodeId, "info", `Scene added: ${s.title}`);
      return s;
    }
    async updateScene(sceneId, patch) {
      await this.init();
      const all = await p(tx(this.db, "scenes").getAll());
      const cur = all.find((s) => s.id === sceneId);
      if (!cur) throw new Error("Scene not found");
      const next = { ...cur, ...patch };
      await p(tx(this.db, "scenes", "readwrite").put(next));
      return next;
    }
    async deleteScene(sceneId) {
      await this.init();
      const cur = await p(tx(this.db, "scenes").get(sceneId));
      await p(tx(this.db, "scenes", "readwrite").delete(sceneId));
      if (cur) await this.addLog(cur.episodeId, "info", `Scene deleted`);
    }
    async reseatScenes(episodeId) {
      await this.init();
      const list = await this.listScenes(episodeId);
      for (let i = 0; i < list.length; i++) {
        const patch = { index: i + 1 };
        if (list[i].title === `Scene ${String(list[i].index).padStart(2, "0")}`) {
          patch.title = `Scene ${String(i + 1).padStart(2, "0")}`;
        }
        await this.updateScene(list[i].id, patch);
      }
    }

    /* jobs */
    async listJobs(episodeId) {
      await this.init();
      const all = await p(tx(this.db, "jobs").getAll());
      return all.filter((j) => j.episodeId === episodeId).sort((a, b) => (a.order || 0) - (b.order || 0));
    }
    async addJob(episodeId, job) {
      await this.init();
      const cur = await this.listJobs(episodeId);
      const j = {
        id: uid(),
        episodeId,
        type: job.type,
        label: job.label || job.type,
        state: job.state || "queued",
        order: cur.length + 1,
        error: null,
        startedAt: null,
        completedAt: null,
        createdAt: Date.now()
      };
      await p(tx(this.db, "jobs", "readwrite").add(j));
      return j;
    }
    async updateJob(jobId, patch) {
      await this.init();
      const all = await p(tx(this.db, "jobs").getAll());
      const cur = all.find((j) => j.id === jobId);
      if (!cur) throw new Error("Job not found");
      const next = { ...cur, ...patch };
      if (patch.state === "running" && !cur.startedAt) next.startedAt = Date.now();
      if (patch.state === "done" || patch.state === "failed") next.completedAt = Date.now();
      await p(tx(this.db, "jobs", "readwrite").put(next));
      return next;
    }
    async clearJobs(episodeId) {
      await this.init();
      const list = await this.listJobs(episodeId);
      for (const j of list) await p(tx(this.db, "jobs", "readwrite").delete(j.id));
    }
    async rebuildJobs(episodeId) {
      await this.clearJobs(episodeId);
      const plan = [
        { type: "rewrite",       label: "Rewrite via LLM"     },
        { type: "storyboard",    label: "Generate storyboard" },
        { type: "export_csv",      label: "Export image CSV"    },
        { type: "veo_prompts",   label: "Generate Veo prompts"},
        { type: "audio",         label: "TTS audio narration" },
        { type: "video",         label: "Render Flow CDP clip"}
      ];
      for (const p of plan) await this.addJob(episodeId, p);
    }

    /* logs */
    async listLogs(episodeId) {
      await this.init();
      const all = await p(tx(this.db, "logs").getAll());
      return all.filter((l) => l.episodeId === episodeId).sort((a, b) => b.time - a.time);
    }
    async addLog(episodeId, level, message) {
      await this.init();
      const entry = { id: uid(), episodeId, time: Date.now(), level, message };
      await p(tx(this.db, "logs", "readwrite").add(entry));
      return entry;
    }

    /* assets (base64) */
    async listAssets(episodeId) {
      await this.init();
      const all = await p(tx(this.db, "assets").getAll());
      return all.filter((a) => a.episodeId === episodeId).sort((a, b) => a.createdAt - b.createdAt);
    }
    async addAsset(episodeId, file) {
      await this.init();
      const data = await fileToBase64(file);
      const a = {
        id: uid(),
        episodeId,
        name: file.name,
        type: file.type,
        size: file.size,
        data,
        createdAt: Date.now()
      };
      await p(tx(this.db, "assets", "readwrite").add(a));
      await this.addLog(episodeId, "info", `Asset uploaded: ${file.name} (${Math.round(file.size / 1024)} KB)`);
      return a;
    }
    async deleteAsset(assetId) {
      await this.init();
      const cur = await p(tx(this.db, "assets").get(assetId));
      await p(tx(this.db, "assets", "readwrite").delete(assetId));
      // detach from any scene
      const scenes = await p(tx(this.db, "scenes").getAll());
      for (const s of scenes) {
        if (s.assetId === assetId) await this.updateScene(s.id, { assetId: null });
      }
      if (cur) await this.addLog(cur.episodeId, "info", `Asset deleted: ${cur.name}`);
    }

    /* settings */
    async getSetting(key, fallback = null) {
      await this.init();
      const r = await p(tx(this.db, "settings").get(key));
      return r ? r.value : fallback;
    }
    async setSetting(key, value) {
      await this.init();
      await p(tx(this.db, "settings", "readwrite").put({ key, value }));
    }

    /* helpers */
    async exportEpisode(id) {
      const ep  = await this.getEpisode(id);
      if (!ep) throw new Error("Episode not found");
      const sc  = await this.listScenes(id);
      const jb  = await this.listJobs(id);
      const lg  = await this.listLogs(id);
      const ast = (await this.listAssets(id)).map((a) => ({ id: a.id, name: a.name, type: a.type, size: a.size }));
      return {
        exported_at: new Date().toISOString(),
        episode: ep,
        scenes: sc,
        jobs: jb,
        logs: lg,
        assets: ast
      };
    }
    async resetAll() {
      await this.init();
      for (const s of STORES) {
        await p(tx(this.db, s, "readwrite").clear());
      }
    }
  }

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(r.result);
      r.onerror = () => reject(r.error);
      r.readAsDataURL(file);
    });
  }

  global.NSDatabase = NSDatabase;
  global.NS_STAGES  = STAGES;
  global.NS_TRANSITIONS = TRANSITIONS;
  global.NS_stageIndex = stageIndex;
  global.NS_nextStage = nextStage;
  global.NS_prevStage = prevStage;
  global.NS_canTransition = canTransition;
  global.NS_progressPct = progressPct;
  global.NS_uid = uid;

})(window);