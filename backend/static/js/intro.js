const KEY = "argus:intro:v1";

const SLIDES = [
  {
    art: `<img class="intro__icon" src="assets/argus-anime.webp" alt="">`,
    title: "Hi，我是 Argus。",
    text: "你的求职陪跑。我们一起聊经历、找方向、改简历、准备面试。",
    note: "先从一次聊天开始。",
  },
  {
    art: `<div class="intro__chat">
      <p class="intro__bubble intro__bubble--them">你说做过增长，用户分层这块呢？</p>
      <p class="intro__bubble intro__bubble--me">这个我没写，感觉不算经历。</p>
      <p class="intro__bubble intro__bubble--them">JD 里重点写了它，面试很加分。</p>
      <p class="intro__bubble intro__bubble--me">噢，我确实做过——我是按消费频次分的。</p>
    </div>`,
    title: "有些经历，要 Argus 问出来。",
    text: "他对着 JD 和面试官视角发问，把你自己略过、但对面试很有用的部分挖出来。",
  },
  {
    art: `<div class="intro__resume"><div class="intro__resume-head"><b>简历</b><span>招聘者视角</span></div><i></i><i></i><i class="is-short"></i><p>定稿由你完成</p></div>`,
    title: "简历由你亲手定稿。",
    text: "Argus 会用招聘者的视角看一遍，告诉你哪里能更快被看见；定稿由你完成。",
  },
  {
    art: `<div class="intro__map"><div class="intro__card"><b>目标岗位</b><span>同类岗位已经归好类</span></div><div class="intro__card"><b>能力地图</b><span>核心能力 · 加分项</span></div></div>`,
    title: "先看清方向，再准备怎么讲。",
    text: "Jobs 和 Career 帮你看岗位和能力地图；面试怎么讲，可以在 Chat 里先过一遍。",
    note: "有简历就传 md/txt；顶部头像随时回首页。",
    start: true,
  },
];

let showing = false;

export function maybeShowIntro(onStart) {
  if (showing) return Promise.resolve();
  const force = new URLSearchParams(location.search).has("intro");
  try { if (!force && localStorage.getItem(KEY)) return Promise.resolve(); } catch {}
  showing = true;

  return new Promise((resolve) => {
    const root = document.createElement("section");
    const shell = document.querySelector(".app");
    root.className = "intro";
    root.tabIndex = -1;
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", "Argus 引导");
    root.innerHTML = `
      <button class="intro__skip" type="button">跳过</button>
      <div class="intro__body">
        ${SLIDES.map((s, i) => `
          <div class="intro__slide${i === 0 ? " is-active intro__slide--cover" : ""}" aria-hidden="${i !== 0}">
            ${s.art}
            <h2 class="intro__title">${s.title}</h2>
            <p class="intro__text">${s.text}</p>
            ${s.note ? `<p class="intro__note">${s.note}</p>` : ""}
            ${s.start ? `<button class="intro__start" type="button">去聊聊我的经历</button><button class="intro__later" type="button">先看看</button>` : ""}
          </div>`).join("")}
      </div>
      <div class="intro__foot">
        <div class="intro__dots" aria-hidden="true">${SLIDES.map((_, i) => `<i class="${i === 0 ? "is-on" : ""}"></i>`).join("")}</div>
        <p class="intro__hint"></p>
      </div>`;
    shell?.setAttribute("inert", "");
    document.body.append(root);
    root.focus({ preventScroll: true });

    let i = 0;
    let done = false;
    let swiped = false;
    let x0 = 0;
    const slides = [...root.querySelectorAll(".intro__slide")];

    const dots = [...root.querySelectorAll(".intro__dots i")];
    const hint = root.querySelector(".intro__hint");

    const go = (n) => {
      i = Math.max(0, Math.min(SLIDES.length - 1, n));
      slides.forEach((s, k) => {
        s.classList.toggle("is-active", k === i);
        s.setAttribute("aria-hidden", String(k !== i));
        s.inert = k !== i;
      });
      dots.forEach((d, k) => d.classList.toggle("is-on", k === i));
      hint.textContent = i === SLIDES.length - 1 ? "轻点开始" : "滑动或轻点";
    };
    go(0);

    const finish = (start) => {
      if (done) return;
      done = true;
      try { localStorage.setItem(KEY, "1"); } catch {}
      document.removeEventListener("keydown", onKey);
      shell?.removeAttribute("inert");
      root.remove();
      showing = false;
      resolve();
      if (start) onStart?.();
    };
    const next = () => { if (i < SLIDES.length - 1) go(i + 1); else finish(true); };
    const prev = () => { if (i > 0) go(i - 1); };

    root.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
    root.addEventListener("touchend", (e) => {
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) < 40) return;
      swiped = true;
      setTimeout(() => { swiped = false; }, 400);
      if (dx < 0) next(); else prev();
    });
    root.addEventListener("click", (e) => {
      if (swiped) { swiped = false; return; }
      if (e.target.closest(".intro__skip")) return finish(false);
      if (e.target.closest(".intro__later")) return finish(false);
      if (e.target.closest(".intro__start")) return finish(true);
      if (i === SLIDES.length - 1) return finish(true);
      next();
    });

    const onKey = (e) => {
      if (e.key === "ArrowRight") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); prev(); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    };
    document.addEventListener("keydown", onKey);
  });
}
