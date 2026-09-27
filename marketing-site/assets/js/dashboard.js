/* ============================================
   Nightmare Studio · Dashboard controller
   ============================================ */
(function (global) {
  "use strict";

  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const fmtTime = (ts) => {
    if (!ts) return "—";
    const d = new Date(ts);
    return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };
  const fmtDate = (ts) => {
    if (!ts) return "—";
    return new Date(ts).toLocaleString("vi-VN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  };

  /* ---------- App state ---------- */
  const st = {
    episodes: [],
    activeId: null,
    activeEp: null,
    scenes: [],
    jobs: [],
    logs: [],
    assets: [],
    tab: "overview",
    search: "",
    booted: false,
  };

  /* ---------- DOM refs ---------- */
  const dom = {};
  function cacheDom() {
    dom.epList       = $("#dash-ep-list");
    dom.empty        = $("#dash-empty");
    dom.detail       = $("#dash-detail");
    dom.title        = $("#dash-ep-title");
    dom.stage        = $("#dash-ep-stage");
    dom.epId         = $("#dash-ep-id");
    dom.topActions   = $("#dash-topbar-actions");
    dom.tabs         = $$(".dash-tab");
    dom.panes        = $$(".dash-pane");

    dom.ovPipeline   = $("#ov-pipeline");
    dom.ovPipelineLb = $("#ov-pipeline-label");
    dom.ovMeta       = $("#ov-meta");

    dom.scriptUrl    = $("#script-source-url");
    dom.scriptText   = $("#script-source-text");
    dom.scriptTag    = $("#script-source-tag");
    dom.rewriteText  = $("#script-rewrite-text");
    dom.rewriteTag   = $("#script-rewrite-tag");
    dom.reviewPanel  = $("#script-review");
    dom.reviewNote   = $("#script-review-note");
    dom.reviewActs   = $("#script-review-actions");

    dom.sbList       = $("#sb-list");
    dom.sbReview     = $("#sb-review");
    dom.sbReviewNote = $("#sb-review-note");
    dom.sbReviewActs = $("#sb-review-actions");

    dom.dropzone     = $("#dropzone");
    dom.assetInput   = $("#asset-input");
    dom.assetGrid    = $("#asset-grid");
    dom.sceneMap     = $("#scene-map");
    dom.assetsCommit = $("#assets-commit");

    dom.queueList    = $("#queue-list");
    dom.logList      = $("#log-list");

    dom.setTitle     = $("#set-title");
    dom.setBrandbible= $("#set-brandbible");
    dom.setBackend   = $("#set-backend");
    dom.backendInfo  = $("#dash-backend-info");

    dom.modalCreate  = $("#modal-create");
    dom.mTitle       = $("#m-title");
    dom.mSource      = $("#m-source");
    dom.mBrandbible  = $("#m-brandbible");

    dom.toastStack   = $("#toast-stack");
  }

  /* ---------- Toasts ---------- */
  function toast(msg, type = "info", ttl = 3500) {
    if (!dom.toastStack) return;
    const el = document.createElement("div");
    el.className = `toast toast--${type}`;
    const icons = { ok: "✓", err: "✕", info: "i" };
    el.innerHTML = `<span style="display:inline-flex; width:18px; height:18px; align-items:center; justify-content:center; border-radius:50%; font-family:var(--font-mono); font-size:11px; font-weight:700; color:var(--ink); background:rgba(255,255,255,.08);">${icons[type] || "i"}</span><span>${msg}</span>`;
    dom.toastStack.appendChild(el);
    setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateX(20px)"; }, ttl - 250);
    setTimeout(() => el.remove(), ttl);
  }

  /* ---------- Modals ---------- */
  function openModal(id) { const m = $("#" + id); if (m) m.hidden = false; }
  function closeModal(id) { const m = $("#" + id); if (m) m.hidden = true; }

  /* ---------- Refresh ---------- */
  async function refresh() {
    st.episodes = await NS_Ops.listEpisodes();
    if (st.search) {
      const q = st.search.toLowerCase();
      st.episodes = st.episodes.filter((e) => (e.title || "").toLowerCase().includes(q));
    }
    if (st.activeId) {
      st.activeEp = await NS_Ops.getEpisode(st.activeId);
      if (st.activeEp) {
        st.scenes = await global.__NSDB.listScenes(st.activeId);
        st.jobs   = await global.__NSDB.listJobs(st.activeId);
        st.logs   = await global.__NSDB.listLogs(st.activeId);
        st.assets = await global.__NSDB.listAssets(st.activeId);
      } else {
        st.activeId = null;
      }
    }
    renderAll();
  }

  /* ---------- Renderers ---------- */
  function renderAll() {
    renderBackendInfo();
    renderEpisodeList();
    renderEmpty();
    if (st.activeEp) {
      renderTopbar();
      renderTabs();
      renderTab();
    }
  }
  function renderBackendInfo() {
    if (!dom.backendInfo) return;
    if (NS_useRemote()) {
      dom.backendInfo.textContent = NS_apiBase();
      dom.backendInfo.style.color = "var(--good)";
    } else {
      dom.backendInfo.textContent = "in-browser · IndexedDB (local persistence)";
      dom.backendInfo.style.color = "var(--phantom)";
    }
  }
  function renderEpisodeList() {
    if (!dom.epList) return;
    if (!st.episodes.length) {
      dom.epList.innerHTML = `<div style="padding:14px 12px; color:var(--ink-faint); font-size:12px; font-family:var(--font-mono); letter-spacing:.1em; text-align:center;">Chưa có episode nào.</div>`;
      return;
    }
    dom.epList.innerHTML = st.episodes.map((ep) => {
      const idx = NS_stageIndex(ep.state);
      const isDone = idx >= NS_STAGES.length - 1;
      const isGate = NS_STAGES[idx] && NS_STAGES[idx].isGate;
      const stateClass = isDone ? "dash-ep__stage--done" : (isGate ? "dash-ep__stage--gate" : "");
      return `
        <div class="dash-ep ${st.activeId === ep.id ? "is-active" : ""}" data-id="${ep.id}">
          <div class="dash-ep__title">${escapeHtml(ep.title || "Untitled")}</div>
          <div class="dash-ep__meta">
            <span class="dash-ep__stage ${stateClass}">${escapeHtml(ep.state)}</span>
            <span>${fmtTime(ep.updatedAt)}</span>
          </div>
          <button class="dash-ep__del" data-del="${ep.id}" title="Xoá episode" aria-label="Xoá">×</button>
        </div>
      `;
    }).join("");
    $$(".dash-ep", dom.epList).forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.closest("[data-del]")) return;
        selectEpisode(el.dataset.id);
      });
    });
    $$("[data-del]", dom.epList).forEach((b) => {
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = b.getAttribute("data-del");
        const ep = st.episodes.find((x) => x.id === id);
        if (!ep) return;
        if (!confirm(`Xoá episode "${ep.title}"? Hành động này không thể hoàn tác.`)) return;
        await NS_Ops.deleteEpisode(id);
        if (st.activeId === id) st.activeId = null;
        toast("Đã xoá episode", "ok");
        await refresh();
      });
    });
  }
  function renderEmpty() {
    if (!dom.empty || !dom.detail) return;
    const showEmpty = !st.activeEp;
    dom.empty.hidden = !showEmpty;
    dom.detail.hidden = showEmpty;
  }
  function renderTopbar() {
    if (!st.activeEp) return;
    dom.title.textContent = st.activeEp.title || "Untitled";
    dom.stage.textContent = st.activeEp.state;
    dom.epId.textContent = st.activeEp.id.slice(0, 8);
    dom.topActions.innerHTML = topbarActionsHtml();
    $$("[data-act]", dom.topActions).forEach((b) => {
      b.addEventListener("click", () => doAction(b.getAttribute("data-act"), b));
    });
  }
  function topbarActionsHtml() {
    const s = st.activeEp.state;
    const acts = [];
    if (s === "discovered")   acts.push(["select-source", "Select source →"]);
    if (s === "selected")     acts.push(["run-rewrite", "Run rewrite"]);
    if (s === "rewritten")    acts.push(["submit-review", "Submit for review →"]);
    if (s === "storyboard")   acts.push(["run-storyboard", "Generate storyboard"]);
    if (s === "export_csv")     acts.push(["export-csv", "⤓ Export image CSV"]);
    if (s === "upload_scenes")acts.push(["commit-upload", "Commit upload → Veo"]);
    if (s === "veo_prompts")  acts.push(["run-veo-prompts", "Generate Veo prompts"]);
    if (s === "audio")        acts.push(["run-audio", "Generate audio"]);
    if (s === "video")        acts.push(["run-video", "Render video"]);
    if (s === "final_review") acts.push(["approve-final", "Approve final"], ["reject-final", "Reject"]);
    if (s === "publication")  acts.push(["export-manifest", "⤓ Export manifest"]);
    if (!acts.length) return `<span style="color:var(--ink-faint); font-size:12px; font-family:var(--font-mono); letter-spacing:.12em;">gate: ${s}</span>`;
    return acts.map(([act, label], i) => {
      const variant = i === 0 ? "btn--blood" : "btn--ghost";
      return `<button class="btn ${variant}" data-act="${act}" type="button">${label}</button>`;
    }).join("");
  }
  function renderTabs() {
    dom.tabs.forEach((t) => t.classList.toggle("is-active", t.dataset.tab === st.tab));
    dom.panes.forEach((p) => p.hidden = (p.id !== `pane-${st.tab}`));
  }
  function renderTab() {
    if (!st.activeEp) return;
    if (st.tab === "overview")  renderOverview();
    if (st.tab === "script")    renderScript();
    if (st.tab === "storyboard")renderStoryboard();
    if (st.tab === "assets")    renderAssets();
    if (st.tab === "queue")     renderQueue();
    if (st.tab === "logs")      renderLogs();
    if (st.tab === "settings")  renderSettings();
  }

  /* ---------- Overview ---------- */
  function renderOverview() {
    if (!dom.ovPipeline || !dom.ovMeta) return;
    const idx = NS_stageIndex(st.activeEp.state);
    dom.ovPipelineLb.textContent = `${idx + 1} / ${NS_STAGES.length}`;
    dom.ovPipeline.innerHTML = NS_STAGES.map((s, i) => {
      let cls = "";
      if (i < idx) cls = "is-done";
      if (i === idx) cls = "is-current";
      if (s.isGate) cls += " is-gate";
      const pct = i <= idx ? 100 : 0;
      return `
        <div class="ov-progress ${cls}">
          <div class="ov-progress__num">${String(i + 1).padStart(2, "0")}</div>
          <div>
            <div class="ov-progress__name">${escapeHtml(s.name)}${s.isGate ? " ★" : ""}</div>
            <div class="ov-progress__bar"><span style="width:${pct}%"></span></div>
          </div>
          <div class="ov-progress__state">${i < idx ? "done" : (i === idx ? "current" : "todo")}</div>
        </div>
      `;
    }).join("");

    const meta = [
      ["Title", st.activeEp.title || "—"],
      ["Source", st.activeEp.source && st.activeEp.source.url ? st.activeEp.source.url : "manual"],
      ["State", st.activeEp.state],
      ["Gate", `Stage ${idx + 1} / ${NS_STAGES.length}`],
      ["Brand bible", st.activeEp.brandBible ? truncate(st.activeEp.brandBible, 60) : "—"],
      ["Script words", st.activeEp.script && st.activeEp.script.words ? st.activeEp.script.words : 0],
      ["Script decision", st.activeEp.script && st.activeEp.script.decision ? st.activeEp.script.decision : "—"],
      ["Scenes", st.scenes.length],
      ["Jobs (done/total)", `${st.jobs.filter((j) => j.state === "done").length} / ${st.jobs.length}`],
      ["Assets uploaded", st.assets.length],
      ["Created", fmtDate(st.activeEp.createdAt)],
      ["Updated", fmtDate(st.activeEp.updatedAt)]
    ];
    dom.ovMeta.innerHTML = meta.map(([k, v]) => `
      <div class="ov-meta__row">
        <span>${k}</span>
        <b>${escapeHtml(String(v))}</b>
      </div>
    `).join("");
  }

  /* ---------- Script pane ---------- */
  function renderScript() {
    if (!dom.scriptText) return;
    const ep = st.activeEp;
    dom.scriptUrl.value = ep.source && ep.source.url || "";
    dom.scriptText.value = ep.source && ep.source.text || "";
    dom.scriptTag.textContent = ep.source && ep.source.url ? "from URL" : (ep.source && ep.source.text ? "manual paste" : "empty");

    const r = ep.script || {};
    if (r.text) {
      dom.rewriteText.textContent = r.text;
      dom.rewriteTag.textContent = `${r.words || 0} words · ${r.provider || "mock"}`;
    } else {
      dom.rewriteText.textContent = "Chưa có rewrite. Hãy chạy rewrite job.";
      dom.rewriteTag.textContent = "empty";
    }

    const s = ep.state;
    const reviewVisible = (s === "script_review");
    dom.reviewPanel.hidden = !reviewVisible;
    if (reviewVisible) {
      const acts = [];
      acts.push(`<button class="btn btn--blood" data-act="approve-script" type="button">Approve → Storyboard</button>`);
      acts.push(`<button class="btn btn--ghost" data-act="reject-script" type="button">Reject → Rewritten</button>`);
      dom.reviewActs.innerHTML = acts.join("");
      $$("[data-act]", dom.reviewActs).forEach((b) => {
        b.addEventListener("click", () => doAction(b.getAttribute("data-act"), b));
      });
      dom.reviewNote.value = r.reviewNote || "";
    }

    // enable/disable source editing by state
    const editable = (s === "discovered" || s === "selected");
    dom.scriptUrl.disabled = !editable;
    dom.scriptText.disabled = !editable;
    dom.scriptUrl.style.opacity = editable ? 1 : 0.6;
    dom.scriptText.style.opacity = editable ? 1 : 0.6;
  }

  /* ---------- Storyboard pane ---------- */
  function renderStoryboard() {
    if (!dom.sbList) return;
    const ep = st.activeEp;
    if (!st.scenes.length) {
      dom.sbList.innerHTML = `<div class="sb-empty">Chưa có scene. Hãy chạy storyboard job từ state <b>storyboard</b> hoặc thêm scene thủ công.</div>`;
    } else {
      dom.sbList.innerHTML = st.scenes.map((s, i) => `
        <div class="sb-card" data-scene="${s.id}">
          <div class="sb-thumb">
            ${s.assetId ? `<img src="" data-asset-id="${s.assetId}" alt="scene">` : `<span>no asset</span>`}
            <span class="sb-thumb__num">${String(i + 1).padStart(2, "0")}</span>
            ${s.veoPrompt ? `<span class="sb-thumb__veo">VEO READY</span>` : ""}
          </div>
          <div class="sb-card__body">
            <div class="sb-card__title">
              <input data-field="title" value="${escapeAttr(s.title)}" />
              <span class="sb-card__shot">${escapeHtml(s.shot || "wide")}</span>
            </div>
            <textarea class="sb-card__narration" data-field="narration" placeholder="Narration...">${escapeHtml(s.narration || "")}</textarea>
            <textarea class="sb-card__veo" data-field="veoPrompt" placeholder="Veo prompt (auto-generated)" readonly>${escapeHtml(s.veoPrompt || "")}</textarea>
          </div>
          <div class="sb-card__actions">
            <button class="icon-btn" data-scene-act="up">↑</button>
            <button class="icon-btn" data-scene-act="down">↓</button>
            <button class="icon-btn icon-btn--danger" data-scene-act="del">×</button>
          </div>
        </div>
      `).join("");
      $$(".sb-card", dom.sbList).forEach((card) => {
        const sid = card.dataset.scene;
        $$("[data-field]", card).forEach((inp) => {
          inp.addEventListener("change", async () => {
            const patch = { [inp.dataset.field]: inp.value };
            await global.__NSDB.updateScene(sid, patch);
            await refresh();
          });
        });
        $$("[data-scene-act]", card).forEach((b) => {
          b.addEventListener("click", async () => {
            const act = b.dataset.sceneAct;
            const idx = st.scenes.findIndex((x) => x.id === sid);
            if (act === "del") {
              if (!confirm("Xoá scene này?")) return;
              await global.__NSDB.deleteScene(sid);
              await refresh();
            } else if (act === "up" && idx > 0) {
              const a = st.scenes[idx - 1];
              const b2 = st.scenes[idx];
              await global.__NSDB.updateScene(a.id, { index: b2.index });
              await global.__NSDB.updateScene(b2.id, { index: a.index });
              await refresh();
            } else if (act === "down" && idx < st.scenes.length - 1) {
              const a = st.scenes[idx + 1];
              const b2 = st.scenes[idx];
              await global.__NSDB.updateScene(a.id, { index: b2.index });
              await global.__NSDB.updateScene(b2.id, { index: a.index });
              await refresh();
            }
          });
        });
      });
      // load asset thumbnails
      st.scenes.forEach((s) => {
        if (!s.assetId) return;
        const a = st.assets.find((x) => x.id === s.assetId);
        if (!a) return;
        const img = document.querySelector(`img[data-asset-id="${s.assetId}"]`);
        if (img) img.src = a.data;
      });
    }

    // gate 2 review
    const showGate2 = (ep.state === "asset_review");
    dom.sbReview.hidden = !showGate2;
    if (showGate2) {
      dom.sbReviewActs.innerHTML = `
        <button class="btn btn--blood" data-act="approve-storyboard" type="button">Approve → Export CSV</button>
        <button class="btn btn--ghost" data-act="revise-storyboard" type="button">Revise → Storyboard</button>
      `;
      $$("[data-act]", dom.sbReviewActs).forEach((b) => {
        b.addEventListener("click", () => doAction(b.getAttribute("data-act"), b));
      });
    }
  }

  /* ---------- Assets pane ---------- */
  function renderAssets() {
    if (!dom.assetGrid) return;
    const ep = st.activeEp;
    const canUpload = ["upload_scenes", "asset_review", "storyboard", "export_csv"].includes(ep.state);
    dom.dropzone.style.opacity = canUpload ? 1 : 0.5;
    dom.dropzone.style.pointerEvents = canUpload ? "auto" : "none";

    if (!st.assets.length) {
      dom.assetGrid.innerHTML = `<div style="grid-column:1/-1; padding:24px; text-align:center; color:var(--ink-faint); font-family:var(--font-serif); font-size:14px;">Chưa upload ảnh nào.</div>`;
    } else {
      dom.assetGrid.innerHTML = st.assets.map((a) => `
        <div class="asset-card">
          <div class="asset-card__img"><img src="${a.data}" alt="${escapeAttr(a.name)}"></div>
          <div class="asset-card__body">
            <div class="asset-card__name" title="${escapeAttr(a.name)}">${escapeHtml(a.name)}</div>
            <div class="asset-card__size">${Math.round(a.size / 1024)} KB</div>
            <button class="icon-btn icon-btn--danger" data-asset-del="${a.id}" type="button" style="margin-top:8px;">× Xoá</button>
          </div>
        </div>
      `).join("");
      $$("[data-asset-del]").forEach((b) => {
        b.addEventListener("click", async () => {
          await global.__NSDB.deleteAsset(b.dataset.assetDel);
          await refresh();
        });
      });
    }

    // scene -> asset mapping
    dom.sceneMap.innerHTML = "";
    if (st.scenes.length) {
      dom.sceneMap.innerHTML = `<h4 style="font-family:var(--font-display); font-weight:700; font-size:13px; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-faint); margin:18px 0 8px;">Scene → Asset mapping</h4>` + st.scenes.map((s, i) => {
        const opts = [`<option value="">— none —</option>`].concat(st.assets.map((a) => `<option value="${a.id}" ${s.assetId === a.id ? "selected" : ""}>${escapeHtml(a.name)}</option>`));
        return `
          <div class="scene-map__row">
            <span class="scene-map__name">scene-${String(i + 1).padStart(3, "0")}</span>
            <span class="scene-map__file ${s.assetId ? "" : "is-empty"}">${s.assetId ? "linked" : "chưa có ảnh"}</span>
            <select data-assign-scene="${s.id}">${opts.join("")}</select>
          </div>
        `;
      }).join("");
      $$("[data-assign-scene]").forEach((sel) => {
        sel.addEventListener("change", async () => {
          await global.__NSDB.updateScene(sel.dataset.assignScene, { assetId: sel.value || null });
          toast("Đã gán ảnh cho scene", "ok");
          await refresh();
        });
      });
    }

    dom.assetsCommit.hidden = !(ep.state === "upload_scenes" && st.assets.length >= st.scenes.length && st.scenes.length > 0);
  }

  /* ---------- Queue pane ---------- */
  function renderQueue() {
    if (!dom.queueList) return;
    if (!st.jobs.length) {
      dom.queueList.innerHTML = `<div style="padding:24px; text-align:center; color:var(--ink-faint); font-family:var(--font-serif);">Queue trống.</div>`;
      return;
    }
    dom.queueList.innerHTML = st.jobs.map((j) => {
      const elapsed = j.completedAt && j.startedAt ? `${Math.round((j.completedAt - j.startedAt) / 100) / 10}s` : (j.startedAt ? `${Math.round((Date.now() - j.startedAt) / 100) / 10}s` : "—");
      return `
        <div class="queue-row">
          <span class="dot dot--${j.state === 'done' ? 'green' : (j.state === 'failed' ? '' : 'mute')}"></span>
          <div>
            <div class="queue-row__name">${escapeHtml(j.label)}</div>
            <div class="queue-row__type">${escapeHtml(j.type)} · order ${j.order}</div>
          </div>
          <span class="queue-row__state queue-row__state--${j.state}">${j.state}</span>
          <span class="queue-row__time">${elapsed}</span>
        </div>
      `;
    }).join("");
  }

  /* ---------- Logs pane ---------- */
  function renderLogs() {
    if (!dom.logList) return;
    if (!st.logs.length) {
      dom.logList.innerHTML = `<div style="padding:24px; text-align:center; color:var(--ink-faint); font-family:var(--font-serif);">Chưa có log.</div>`;
      return;
    }
    dom.logList.innerHTML = st.logs.map((l) => `
      <div class="log-row">
        <time>${fmtTime(l.time)}</time>
        <span class="log-row__level log-row__level--${l.level}">${l.level}</span>
        <span class="log-row__msg">${escapeHtml(l.message)}</span>
      </div>
    `).join("");
  }

  /* ---------- Settings pane ---------- */
  function renderSettings() {
    if (!dom.setTitle) return;
    dom.setTitle.value = st.activeEp.title || "";
    dom.setBrandbible.value = st.activeEp.brandBible || "";
    dom.setBackend.className = NS_useRemote() ? "settings-status is-ok" : "settings-status is-mock";
    dom.setBackend.innerHTML = NS_useRemote()
      ? `<span class="dot dot--green"></span><span>Backend: <code style="color:var(--good)">${escapeHtml(NS_apiBase())}</code> · real API</span>`
      : `<span class="dot dot--green"></span><span>Storage: in-browser IndexedDB. Set <code>window.NS_API_BASE</code> trước khi load để gắn vào FastAPI.</span>`;
  }

  /* ---------- Actions ---------- */
  async function doAction(act, btn) {
    if (!st.activeEp) return;
    const epId = st.activeEp.id;
    // Auto-switch tab for actions that need a specific pane's data
    const tabByAct = {
      "select-source": "script",
      "run-rewrite": "script",
      "approve-script": "script",
      "reject-script": "script",
      "run-storyboard": "storyboard",
      "approve-storyboard": "storyboard",
      "revise-storyboard": "storyboard",
      "export-csv": "assets",
      "commit-upload": "assets",
      "run-veo-prompts": "storyboard",
      "run-audio": "storyboard",
      "run-video": "storyboard",
      "approve-final": "storyboard",
      "reject-final": "storyboard"
    };
    if (tabByAct[act]) {
      st.tab = tabByAct[act];
      renderTabs();
      renderTab();
    }
    const setBusy = (on) => {
      if (!btn) return;
      btn.disabled = !!on;
      const orig = btn.dataset.label || btn.textContent;
      if (!btn.dataset.label) btn.dataset.label = orig;
      btn.textContent = on ? "Đang chạy..." : orig;
    };
    try {
      setBusy(true);
      switch (act) {
        case "select-source": {
          const url = dom.scriptUrl.value.trim();
          const text = dom.scriptText.value.trim();
          if (!url && !text) throw new Error("Cần URL hoặc text source");
          await NS_Ops.selectSource(epId, url, text);
          toast("Source selected", "ok");
          break;
        }
        case "run-rewrite": {
          const ep = await NS_Ops.runRewrite(epId);
          toast(`Rewrite done — ${ep.script.words} words`, "ok");
          break;
        }
        case "run-storyboard": {
          await NS_Ops.runStoryboard(epId);
          toast("Storyboard generated", "ok");
          break;
        }
        case "run-veo-prompts": {
          await NS_Ops.runVeoPrompts(epId);
          toast("Veo prompts generated", "ok");
          break;
        }
        case "run-audio": {
          await NS_Ops.runAudio(epId);
          toast("Audio narration done", "ok");
          break;
        }
        case "run-video": {
          await NS_Ops.runVideo(epId);
          toast("Video rendered", "ok");
          break;
        }
        case "submit-review": {
          await NS_Ops.submitForScriptReview(epId);
          toast("Submitted for script review", "ok");
          break;
        }
        case "approve-script": {
          await NS_Ops.approveScript(epId, dom.reviewNote.value);
          toast("Script approved — generating storyboard...", "ok");
          await NS_Ops.runStoryboard(epId);
          toast("Storyboard generated", "ok");
          break;
        }
        case "reject-script": {
          await NS_Ops.rejectScript(epId, dom.reviewNote.value);
          toast("Script sent back to rewritten", "info");
          break;
        }
        case "approve-storyboard": {
          await NS_Ops.approveStoryboard(epId, dom.sbReviewNote.value);
          toast("Storyboard approved", "ok");
          break;
        }
        case "revise-storyboard": {
          await NS_Ops.reviseStoryboard(epId);
          toast("Storyboard sent back to revision", "info");
          break;
        }
        case "export-csv": {
          const { csv, filename } = await NS_Ops.exportCsv(epId);
          downloadText(csv, filename, "text/csv");
          toast("CSV downloaded", "ok");
          break;
        }
        case "commit-upload": {
          await NS_Ops.commitUpload(epId);
          await NS_Ops.runVeoPrompts(epId);
          await NS_Ops.runAudio(epId);
          await NS_Ops.runVideo(epId);
          toast("Upload committed — Veo + audio + video done", "ok");
          break;
        }
        case "approve-final": {
          await NS_Ops.approveFinal(epId, "Approved");
          toast("Final approved — manifest ready", "ok");
          break;
        }
        case "reject-final": {
          await NS_Ops.rejectFinal(epId, "Rejected");
          toast("Final rejected — back to video", "info");
          break;
        }
        case "export-manifest": {
          const data = await NS_Ops.exportManifest(epId);
          downloadJson(data, `manifest-${epId}.json`);
          toast("Manifest exported", "ok");
          break;
        }
        default: throw new Error("Unknown action: " + act);
      }
      await refresh();
    } catch (e) {
      toast(e.message || String(e), "err");
    } finally {
      setBusy(false);
    }
  }

  /* ---------- Episode ops ---------- */
  async function selectEpisode(id) {
    st.activeId = id;
    st.tab = "overview";
    await refresh();
  }
  async function createEpisode() {
    const title = dom.mTitle.value.trim() || "Untitled episode";
    const url = dom.mSource.value.trim();
    const brandbible = dom.mBrandbible.value.trim();
    const ep = await NS_Ops.createEpisode({ title, source: { url, text: "" }, brandBible: brandbible });
    closeModal("modal-create");
    dom.mTitle.value = "";
    dom.mSource.value = "";
    dom.mBrandbible.value = "";
    toast(`Episode created: ${title}`, "ok");
    st.activeId = ep.id;
    st.tab = "overview";
    await refresh();
  }
  async function seedDemo() {
    const demo = await NS_Ops.createEpisode({ title: "Demo · The House on Harkness Road", brandBible: "first-person · slow-burn · atmospheric · 02:00-04:00" });
    await NS_Ops.selectSource(demo.id, "https://reddit.com/r/nosleep/demo", "Ngôi nhà ở cuối đường Harkness vẫn đứng đó, ánh đèn hắt qua khung cửa sổ tầng hai như một con mắt chưa bao giờ chịu ngủ. Bà Whitmore kéo chăn lên đến cằm, nhưng tiếng bước chân ở hành lang thì đã gần hơn rất nhiều so với đêm qua. Đồng hồ trên tường chỉ mười một giờ mười lăm, nhưng cô ấy đã thức từ nửa đêm — và không, không ai khác cũng thức.");
    await NS_Ops.runRewrite(demo.id);
    await NS_Ops.submitForScriptReview(demo.id);
    return demo;
  }

  /* ---------- Bindings ---------- */
  function bindEvents() {
    /* tabs */
    dom.tabs.forEach((t) => {
      t.addEventListener("click", () => {
        st.tab = t.dataset.tab;
        renderTabs();
        renderTab();
      });
    });

    /* new episode modal */
    const newBtn = $("#dash-new");
    const newBtn2 = $("#dash-empty-new");
    if (newBtn)  newBtn.addEventListener("click", () => { dom.mTitle.value = ""; dom.mSource.value = ""; dom.mBrandbible.value = ""; openModal("modal-create"); });
    if (newBtn2) newBtn2.addEventListener("click", () => { dom.mTitle.value = ""; dom.mSource.value = ""; dom.mBrandbible.value = ""; openModal("modal-create"); });
    const mSubmit = $("#m-submit");
    if (mSubmit) mSubmit.addEventListener("click", createEpisode);
    $$("[data-close-modal]").forEach((b) => {
      b.addEventListener("click", () => closeModal(b.getAttribute("data-close-modal")));
    });

    /* search */
    const search = $("#dash-search");
    if (search) {
      search.addEventListener("input", () => {
        st.search = search.value;
        renderEpisodeList();
      });
    }

    /* storyboard actions */
    const sbAdd = $("#sb-add");
    if (sbAdd) sbAdd.addEventListener("click", async () => {
      await global.__NSDB.addScene(st.activeId, {});
      await refresh();
    });
    const sbRegen = $("#sb-regenerate");
    if (sbRegen) sbRegen.addEventListener("click", async () => {
      try {
        await NS_Ops.runStoryboard(st.activeId);
        toast("Storyboard regenerated", "ok");
        await refresh();
      } catch (e) { toast(e.message, "err"); }
    });

    /* dropzone */
    if (dom.dropzone && dom.assetInput) {
      dom.dropzone.addEventListener("click", () => dom.assetInput.click());
      dom.dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dom.dropzone.classList.add("is-over"); });
      dom.dropzone.addEventListener("dragleave", () => dom.dropzone.classList.remove("is-over"));
      dom.dropzone.addEventListener("drop", async (e) => {
        e.preventDefault();
        dom.dropzone.classList.remove("is-over");
        await handleFiles(e.dataTransfer.files);
      });
      dom.assetInput.addEventListener("change", async (e) => {
        await handleFiles(e.target.files);
        e.target.value = "";
      });
    }

    /* queue rebuild */
    const qRebuild = $("#queue-rebuild");
    if (qRebuild) qRebuild.addEventListener("click", async () => {
      await global.__NSDB.rebuildJobs(st.activeId);
      toast("Queue rebuilt", "ok");
      await refresh();
    });

    /* settings */
    const setSave = $("#set-save");
    if (setSave) setSave.addEventListener("click", async () => {
      await NS_Ops.updateEpisode(st.activeId, {
        title: dom.setTitle.value.trim() || "Untitled",
        brandBible: dom.setBrandbible.value
      });
      toast("Settings saved", "ok");
      await refresh();
    });
    const setExport = $("#set-export");
    if (setExport) setExport.addEventListener("click", async () => {
      const data = await NS_Ops.exportManifest(st.activeId);
      downloadJson(data, `manifest-${st.activeId}.json`);
      toast("Manifest exported", "ok");
    });
    const setDelete = $("#set-delete");
    if (setDelete) setDelete.addEventListener("click", async () => {
      if (!confirm("Xoá episode này vĩnh viễn?")) return;
      await NS_Ops.deleteEpisode(st.activeId);
      st.activeId = null;
      toast("Episode deleted", "ok");
      await refresh();
    });

    /* reset & re-seed demo */
    const resetBtn = $("#dash-reset");
    if (resetBtn) resetBtn.addEventListener("click", async () => {
      if (!confirm("Xoá toàn bộ IndexedDB và seed lại demo? Hành động này không thể hoàn tác.")) return;
      const d = global.__NSDB;
      await d.resetAll();
      st.activeId = null;
      toast("Reset xong — seeding demo...", "info");
      await refresh();
      const demo = await seedDemo();
      st.activeId = demo.id;
      await refresh();
      toast("Demo seeded — đang ở state script_review", "ok", 5000);
    });

    /* source URL/text change → no auto-save (user clicks Select source) */
    /* keybindings */
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        $$(".modal-back").forEach((m) => { if (!m.hidden) m.hidden = true; });
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        const s = $("#dash-search");
        if (s) s.focus();
      }
    });
  }

  async function handleFiles(files) {
    if (!files || !files.length) return;
    const ep = st.activeEp;
    if (!ep) return;
    const allowed = ["upload_scenes", "asset_review", "storyboard", "export_csv"];
    if (!allowed.includes(ep.state)) {
      toast(`Upload chỉ khả dụng từ state storyboard trở đi (hiện tại: ${ep.state})`, "err");
      return;
    }
    for (const file of Array.from(files)) {
      if (file.size > 8 * 1024 * 1024) { toast(`File ${file.name} quá lớn (>8MB)`, "err"); continue; }
      const a = await global.__NSDB.addAsset(ep.id, file);
      // try auto-assign by name pattern scene-NNN
      const m = /scene[-_]?(\d{2,3})/i.exec(file.name);
      if (m) {
        const idx = parseInt(m[1], 10);
        const scene = st.scenes.find((s) => s.index === idx);
        if (scene) await global.__NSDB.updateScene(scene.id, { assetId: a.id });
      }
    }
    toast(`Uploaded ${files.length} file(s)`, "ok");
    await refresh();
  }

  /* ---------- Helpers ---------- */
  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }
  function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }
  function truncate(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function downloadText(text, name, mime = "text/plain") {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function downloadJson(obj, name) {
    downloadText(JSON.stringify(obj, null, 2), name, "application/json");
  }

  /* ---------- Boot ---------- */
  async function boot() {
    if (st.booted) {
      await refresh();
      return;
    }
    st.booted = true;
    cacheDom();
    bindEvents();
    await refresh();
    if (!st.episodes.length) {
      try {
        const demo = await seedDemo();
        st.activeId = demo.id;
        await refresh();
        toast("Đã seed demo episode — chỉnh sửa thoải mái", "info", 5000);
      } catch (e) {
        console.warn(e);
      }
    }
  }

  global.NS_Dashboard = { boot, refresh };
})(window);