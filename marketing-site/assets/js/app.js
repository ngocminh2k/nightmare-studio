/* ============================================
   Nightmare Studio · Marketing Site JS
   ============================================ */
(function () {
  "use strict";

  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const prefersReduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Year (optional placeholder use) ---------- */
  /* none */

  /* ---------- Sticky nav ---------- */
  const nav = $("#nav");
  const onScroll = () => {
    if (!nav) return;
    if (window.scrollY > 12) nav.classList.add("is-stuck");
    else nav.classList.remove("is-stuck");
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- Mobile nav panel ---------- */
  const burger = $("#nav-burger");
  const panel  = $("#nav-panel");
  if (burger && panel) {
    burger.addEventListener("click", () => {
      const open = burger.getAttribute("aria-expanded") === "true";
      burger.setAttribute("aria-expanded", String(!open));
      panel.classList.toggle("is-open", !open);
      panel.setAttribute("aria-hidden", String(open));
    });
    panel.addEventListener("click", (e) => {
      if (e.target.tagName === "A") {
        burger.setAttribute("aria-expanded", "false");
        panel.classList.remove("is-open");
        panel.setAttribute("aria-hidden", "true");
      }
    });
  }

  /* ---------- Theme toggle ---------- */
  const themeBtn = $("#theme-toggle");
  const setTheme = (t) => {
    document.body.dataset.theme = t;
    try { localStorage.setItem("ns-theme", t); } catch (_) {}
  };
  // Default to night theme unless user explicitly chose bone before
  try {
    const saved = localStorage.getItem("ns-theme");
    if (saved === "bone") setTheme("bone");
    else setTheme("night");
  } catch (_) {
    document.body.dataset.theme = "night";
  }
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      setTheme(document.body.dataset.theme === "bone" ? "night" : "bone");
    });
  }

  /* ---------- Reveal on scroll ---------- */
  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const delay = entry.target.getAttribute("data-delay");
        if (delay) {
          setTimeout(() => entry.target.classList.add("is-in"), parseInt(delay, 10));
        } else {
          entry.target.classList.add("is-in");
        }
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -60px 0px" });
  $$("[data-reveal]").forEach((el) => revealObserver.observe(el));

  /* ---------- Cursor follower ---------- */
  const dot  = $(".cursor-dot");
  const ring = $(".cursor-ring");
  if (dot && ring && !prefersReduce && matchMedia("(hover: hover)").matches) {
    let mx = window.innerWidth / 2, my = window.innerHeight / 2;
    let rx = mx, ry = my;
    document.addEventListener("mousemove", (e) => { mx = e.clientX; my = e.clientY; });
    const tick = () => {
      rx += (mx - rx) * 0.18;
      ry += (my - ry) * 0.18;
      dot.style.transform  = `translate(${mx}px, ${my}px) translate(-50%, -50%)`;
      ring.style.transform = `translate(${rx}px, ${ry}px) translate(-50%, -50%)`;
      requestAnimationFrame(tick);
    };
    tick();
    $$("a, button, .gate, .feature, .thumbs li").forEach((el) => {
      el.addEventListener("mouseenter", () => ring.classList.add("is-hover"));
      el.addEventListener("mouseleave", () => ring.classList.remove("is-hover"));
    });
  }

  /* ---------- Fog canvas (subtle drifting particles) ---------- */
  const fog = $("#fog-canvas");
  if (fog && !prefersReduce) {
    const ctx = fog.getContext("2d");
    let W = 0, H = 0;
    const particles = [];
    const SPARKS = 28;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      W = fog.clientWidth; H = fog.clientHeight;
      fog.width = W * dpr; fog.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);
    for (let i = 0; i < SPARKS; i++) {
      particles.push({
        x: Math.random() * 2000,
        y: Math.random() * 1200,
        r: 0.6 + Math.random() * 1.8,
        vx: -0.05 - Math.random() * 0.18,
        vy: -0.02 - Math.random() * 0.08,
        a: 0.05 + Math.random() * 0.18,
        c: Math.random() > 0.5 ? "220, 20, 60" : "125, 60, 152"
      });
    }
    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      particles.forEach((p) => {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < -10) p.x = W + 10;
        if (p.y < -10) { p.y = H + 10; p.x = Math.random() * W; }
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 14);
        g.addColorStop(0, `rgba(${p.c}, ${p.a})`);
        g.addColorStop(1, `rgba(${p.c}, 0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * 14, 0, Math.PI * 2);
        ctx.fill();
      });
      requestAnimationFrame(draw);
    };
    draw();
  }

  /* ---------- Hero title glitch ---------- */
  const heroTitle = $(".hero__title");
  if (heroTitle && !prefersReduce) {
    let armed = true;
    setInterval(() => {
      if (!armed) return;
      heroTitle.classList.add("is-glitching");
      setTimeout(() => heroTitle.classList.remove("is-glitching"), 360);
    }, 4200);
  }

  /* ---------- Workflow interactive pipeline ---------- */
  const gates = $$(".gate");
  const detail = {
    num:   $("#gd-num"),
    title: $("#gd-title"),
    sub:   $("#gd-sub"),
    state: $("#gd-state"),
    body:  $("#gd-body"),
    list:  $("#gd-list"),
  };
  const gateData = {
    1: {
      title: "Discovered",
      sub: "Tìm một source r/nosleep chưa được crawl — provenance được ghi ngay.",
      state: "DONE",
      body: "Source được dedupe local. URL gốc và timestamp được lưu trong DB. Một episode mới được khởi tạo với liên kết tới source này.",
      list: ["URL & text gốc", "Dedupe theo domain + slug", "Episode seed state = discovered"]
    },
    2: {
      title: "Selected",
      sub: "Creator chọn source để đi tiếp — không có gì chạy tự động.",
      state: "DONE",
      body: "Episode chuyển sang selected. Từ đây mọi bước đều do creator quyết định.",
      list: ["Manual pick", "Editor có thể edit brand bible", "State machine enforce hành vi hợp lệ"]
    },
    3: {
      title: "Rewritten",
      sub: "LLM viết lại câu chuyện theo brand bible của project.",
      state: "DONE",
      body: "Qua local 9Router, mrkane trước, gemini fallback. Output KHÔNG đi thẳng đến media — luôn dừng ở gate tiếp theo.",
      list: ["Local-first key", "Fallback chain có kiểm soát", "Draft chờ script review"]
    },
    4: {
      title: "Script Review",
      sub: "Gate đầu tiên — quyết định rewrite có được đưa vào production.",
      state: "ĐANG CHẠY",
      body: "Creator đọc lại kịch bản sau khi LLM viết lại. Duyệt hoặc yêu cầu chỉnh sửa. Không có bước nào đi tiếp nếu gate này chưa ký.",
      list: ["Decision: approve / request changes", "Note, timestamp và state kế tiếp đều được persist", "Reject sẽ requeue về Rewritten, giữ nguyên source provenance"]
    },
    5: {
      title: "Storyboard",
      sub: "Tách kịch bản đã duyệt thành các scene narration, shot, prompt.",
      state: "BLOCKED",
      body: "Mỗi scene có narration word count, loại shot, Veo prompt sơ bộ và asset status. Editor có thể sửa trước khi asset review.",
      list: ["Per-scene fields", "Editable storyboard", "Asset tracking per scene"]
    },
    6: {
      title: "Asset Review",
      sub: "Gate thứ hai — duyệt storyboard trước khi xuất CSV.",
      state: "BLOCKED",
      body: "Đảm bảo mỗi scene có shot rõ ràng, không scene nào trống. Sau duyệt, app export image_prompts.csv.",
      list: ["Per-scene gate", "Bulk CSV export", "Resume-safe — không phá storyboard khi fail"]
    },
    7: {
      title: "Export CSV",
      sub: "Xuất image_prompts.csv để creator render ảnh ngoài tool.",
      state: "BLOCKED",
      body: "File CSV có sẵn schema đặt tên scene-NNN.png. Creator có toàn quyền chọn tool generate ảnh.",
      list: ["Schema ổn định", "CLI: py .\\export_csv.py <id>", "Cùng DB với web app"]
    },
    8: {
      title: "Upload Scenes",
      sub: "Upload đúng một lần — app tự gán ảnh cho từng scene theo tên file.",
      state: "BLOCKED",
      body: "Tên file phải match scene-NNN.png. Sau khi upload đầy đủ, gate Veo prompts tự mở.",
      list: ["Bulk upload", "Auto-assign by filename", "Path lưu outputs/<episode>/scene-NNN.png"]
    },
    9: {
      title: "Veo Prompts",
      sub: "LLM viết final Veo 3.1 prompt cho từng scene theo rules.",
      state: "BLOCKED",
      body: "Prompt được sinh theo docs/veo-3.1-prompt-rules.md. Mỗi scene có một final prompt để đưa vào Flow.",
      list: ["Veo 3.1 rules enforced", "Editable per scene", "Persisted in DB"]
    },
    10: {
      title: "Audio",
      sub: "TTS narration theo từng scene, có waveform preview.",
      state: "BLOCKED",
      body: "Audio narration được sinh và ghép theo thứ tự storyboard. Có thể retry per-scene nếu provider fail.",
      list: ["Per-scene TTS", "Retry an toàn", "Output path outputs/<episode>/audio/"]
    },
    11: {
      title: "Video",
      sub: "Render video clip qua Google Flow CDP — fail-closed.",
      state: "BLOCKED",
      body: "CDP workspace phải được cấu hình thật. Nếu selector hoặc Flow không khả dụng, job fail mà không ghi artifact giả.",
      list: ["CDP-backed", "No fake artifacts", "Real clip per scene"]
    },
    12: {
      title: "Final Review",
      sub: "Gate cuối + publication handoff — không tự động upload.",
      state: "BLOCKED",
      body: "Creator ký tên cuối cùng, app sinh episode manifest portable. Chưa bao giờ tự publish lên YouTube hay nơi khác.",
      list: ["Manifest export", "Editorial signature", "Explicit handoff only"]
    }
  };
  const renderGate = (step) => {
    const d = gateData[step];
    if (!d || !detail.num) return;
    detail.num.textContent   = String(step).padStart(2, "0");
    detail.title.textContent = d.title;
    detail.sub.textContent   = d.sub;
    detail.state.textContent = d.state;
    detail.body.textContent  = d.body;
    detail.list.innerHTML = d.list.map((t) => `<li>${t}</li>`).join("");
    const stateClass = d.state === "DONE" ? "tag--ghost" : (d.state === "BLOCKED" ? "tag--ghost" : "tag--red");
    detail.state.className = `gate-detail__state ${stateClass}`;
  };
  gates.forEach((g) => {
    g.addEventListener("click", () => {
      gates.forEach((x) => x.classList.remove("is-current"));
      g.classList.add("is-current");
      const step = parseInt(g.dataset.step, 10);
      renderGate(step);
    });
  });
  // initial render
  renderGate(4);

  /* ---------- Player play (visual only) ---------- */
  const play = $(".player__play");
  if (play) {
    play.addEventListener("click", () => {
      play.style.transform = "scale(.92)";
      setTimeout(() => (play.style.transform = ""), 180);
    });
  }

  /* ---------- Smooth scroll for hash links ---------- */
  $$('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href");
      // Route-level hash → let router handle
      if (id.startsWith("#/")) return;
      if (id.length < 2) return;
      const target = $(id);
      if (!target) return;
      e.preventDefault();
      const y = target.getBoundingClientRect().top + window.scrollY - 68;
      window.scrollTo({ top: y, behavior: prefersReduce ? "auto" : "smooth" });
    });
  });

  /* ---------- SPA router (landing ↔ dashboard) ---------- */
  const landingView = document.querySelector("main#top");
  const dashView    = $("#view-dashboard");
  const navLinks    = $$(".nav__links a");
  const navPanel    = $("#nav-panel");
  const navBurger   = $("#nav-burger");

  function closeBurger() {
    if (!navBurger || !navPanel) return;
    navBurger.setAttribute("aria-expanded", "false");
    navPanel.classList.remove("is-open");
    navPanel.setAttribute("aria-hidden", "true");
  }

  function applyRoute() {
    const hash = (location.hash || "").replace(/^#/, "");
    const isDash = hash.startsWith("/dashboard");

    if (landingView) landingView.hidden = !!isDash;
    if (dashView)    dashView.hidden    = !isDash;

    navLinks.forEach((a) => {
      const r = a.getAttribute("data-route") || "";
      a.classList.toggle("is-dash-active", r === "dashboard" && isDash);
    });

    if (isDash) {
      window.scrollTo(0, 0);
      closeBurger();
      // boot dashboard
      if (globalThis.NS_Dashboard && typeof globalThis.NS_Dashboard.boot === "function") {
        globalThis.NS_Dashboard.boot();
      }
    } else {
      window.scrollTo(0, 0);
    }
    document.documentElement.scrollBehavior = "";
  }

  window.addEventListener("hashchange", applyRoute);
  document.addEventListener("DOMContentLoaded", applyRoute);
  // also try immediately in case scripts already loaded
  applyRoute();

})();