/* =========================================================
   华矩检测 — 品牌片头控制（合并版）
   由 huaju-logo-intro/script.js 移植，只做三处适配：
   1) heroTitle 指向工具页标题（#heroTitle）
   2) 片头彻底隐藏后派发 site-ready，让工具页的入场动效开始播放
   3) 少量空值保护，避免工具页缺少节点时报错
   ========================================================= */

(() => {
  "use strict";

  const intro = document.getElementById("intro");
  const site = document.getElementById("site");
  const skipButton = document.getElementById("skipIntro");
  const heroTitle = document.getElementById("heroTitle");
  const canvas = document.getElementById("energy-canvas");
  const replayButtons = Array.from(document.querySelectorAll("[data-replay]"));
  const body = document.body;

  if (!intro || !site) {
    // 片头节点缺失时立即放行工具页，避免页面被 body.intro-active 锁住
    body.classList.remove("intro-active");
    window.dispatchEvent(new Event("site-ready"));
    return;
  }

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const INTRO_DURATION = reduceMotion ? 1600 : 3000;
  const EXIT_DURATION = reduceMotion ? 420 : 1120;

  let exitTimer = 0;
  let hideTimer = 0;

  /* ---------------------------------------------------------
     Ambient particle field
     --------------------------------------------------------- */

  const context = canvas ? canvas.getContext("2d") : null;
  let particles = [];
  let particleFrame = 0;
  let viewWidth = 0;
  let viewHeight = 0;
  let pixelRatio = 1;
  let particlesRunning = false;

  function setupParticles() {
    if (!canvas || !context) return;

    pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    viewWidth = intro.clientWidth;
    viewHeight = intro.clientHeight;
    canvas.width = Math.round(viewWidth * pixelRatio);
    canvas.height = Math.round(viewHeight * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    const count = Math.max(24, Math.min(72, Math.round(viewWidth / 24)));
    particles = Array.from({ length: count }, () => ({
      x: Math.random() * viewWidth,
      y: Math.random() * viewHeight,
      radius: 0.35 + Math.random() * 1.15,
      vx: (Math.random() - 0.5) * 0.1,
      vy: -0.06 - Math.random() * 0.2,
      alpha: 0.08 + Math.random() * 0.32,
      accent: Math.random() < 0.1,
    }));
  }

  function renderParticles(animate) {
    if (!context) return;

    context.clearRect(0, 0, viewWidth, viewHeight);

    const linkDistance = 112;

    for (let i = 0; i < particles.length; i += 1) {
      const a = particles[i];

      if (animate) {
        a.x += a.vx;
        a.y += a.vy;

        if (a.y < -8) {
          a.y = viewHeight + 8;
          a.x = Math.random() * viewWidth;
        }
        if (a.x < -8) a.x = viewWidth + 8;
        if (a.x > viewWidth + 8) a.x = -8;
      }

      for (let j = i + 1; j < particles.length; j += 1) {
        const b = particles[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const distance = Math.hypot(dx, dy);

        if (distance < linkDistance) {
          const lineAlpha = (1 - distance / linkDistance) * 0.055;
          context.beginPath();
          context.moveTo(a.x, a.y);
          context.lineTo(b.x, b.y);
          context.strokeStyle = `rgba(126, 174, 228, ${lineAlpha})`;
          context.lineWidth = 0.6;
          context.stroke();
        }
      }

      context.beginPath();
      context.arc(a.x, a.y, a.radius, 0, Math.PI * 2);
      context.fillStyle = a.accent
        ? `rgba(128, 229, 221, ${a.alpha * 0.9})`
        : `rgba(178, 208, 240, ${a.alpha})`;
      context.fill();
    }
  }

  function particleLoop() {
    if (!particlesRunning) return;
    renderParticles(true);
    particleFrame = window.requestAnimationFrame(particleLoop);
  }

  function startParticles() {
    if (!canvas || !context) return;
    stopParticles();
    setupParticles();
    particlesRunning = true;

    if (reduceMotion) {
      renderParticles(false);
      particlesRunning = false;
      return;
    }

    particleLoop();
  }

  function stopParticles() {
    particlesRunning = false;
    window.cancelAnimationFrame(particleFrame);
    if (context) context.clearRect(0, 0, viewWidth, viewHeight);
  }

  if (canvas) {
    window.addEventListener("resize", () => {
      if (!particlesRunning) return;
      setupParticles();
      if (reduceMotion) {
        renderParticles(false);
        particlesRunning = false;
      }
    });
  }

  /* ---------------------------------------------------------
     Accessibility + intro state
     --------------------------------------------------------- */

  function setSiteInert(isInert) {
    if ("inert" in site) site.inert = isInert;
    if (isInert) {
      site.setAttribute("aria-hidden", "true");
    } else {
      site.removeAttribute("aria-hidden");
    }
  }

  function playIntro(userInitiated = false) {
    window.clearTimeout(exitTimer);
    window.clearTimeout(hideTimer);

    intro.hidden = false;
    intro.classList.remove("is-playing", "is-leaving");
    intro.style.setProperty("--intro-duration", `${INTRO_DURATION}ms`);

    // Force a style flush so every animation starts from frame zero.
    void intro.offsetWidth;

    body.classList.remove("site-ready");
    body.classList.add("intro-active");
    setSiteInert(true);

    intro.classList.add("is-playing");
    startParticles();

    exitTimer = window.setTimeout(endIntro, INTRO_DURATION);

    if (userInitiated) {
      // 通知工具页收回入场状态，片头结束后重新播放递进动效
      window.dispatchEvent(new Event("intro-replay"));
      window.scrollTo({ top: 0, behavior: "auto" });
      window.requestAnimationFrame(() => {
        if (skipButton) skipButton.focus({ preventScroll: true });
      });
    }
  }

  function endIntro() {
    if (intro.hidden || intro.classList.contains("is-leaving")) return;

    window.clearTimeout(exitTimer);
    intro.classList.add("is-leaving");
    body.classList.add("site-ready");

    // 虹膜一开始打开就让工具页进入入场动画，避免露出空白
    window.dispatchEvent(new Event("site-ready"));

    hideTimer = window.setTimeout(() => {
      stopParticles();
      intro.hidden = true;
      intro.classList.remove("is-playing", "is-leaving");
      body.classList.remove("intro-active");
      setSiteInert(false);

      if (heroTitle) {
        heroTitle.focus({ preventScroll: true });
      }
    }, EXIT_DURATION);
  }

  if (skipButton) {
    skipButton.addEventListener("click", endIntro);
  }

  replayButtons.forEach((button) => {
    button.addEventListener("click", () => playIntro(true));
  });

  // 全局快捷键：片头播放期间按任意（非修饰）键即跳过
  const NON_SKIP_KEYS = new Set([
    "Shift", "Control", "Alt", "Meta", "CapsLock", "AltGraph", "Dead",
    "Fn", "FnLock", "Hyper", "Super", "Symbol", "SymbolLock", "Unidentified",
  ]);

  function isSkipKey(event) {
    if (!event || event.defaultPrevented) return false;
    if (event.ctrlKey || event.metaKey || event.altKey) return false;
    const key = event.key || "";
    if (!key || NON_SKIP_KEYS.has(key)) return false;
    return true;
  }

  document.addEventListener("keydown", (event) => {
    if (intro.hidden || intro.classList.contains("is-leaving")) return;
    if (isSkipKey(event)) endIntro();
  });

  // 鼠标 / 触屏：进入后点一下任意位置也能跳过
  document.addEventListener("pointerdown", (event) => {
    if (intro.hidden || intro.classList.contains("is-leaving")) return;
    if (event.button !== 0) return;
    endIntro();
  });

  // Begin automatically when the page first becomes visible.
  playIntro(false);
})();
