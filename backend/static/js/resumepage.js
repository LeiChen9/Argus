/* Resume 页：列表 → 详情（#resume/<career_id>），以及详情里那份亲手改的表单。
   路由写法照 job.js。

   **这页不挂 AI 的评语。** 评语是 Argus 在 Chat 里说的话，已经说过了；这里只放
   用户自己那份文件。只读件（Chat 卡片、Career 软链）和索引在 resume.js。

   卡片平时是**只读**的，右上角一个 Edit 图标；点开才变成输入框，改完点提交。
   请求只在提交那一刻发——「改完了提交」是条清楚的边界，不会像自动保存那样
   存进去一半、回头又当成另一次编辑。

   字段自带它改的是哪个 JSON Pointer（data-path），所以整页只挂一个 input
   委托，不用给每个输入框绑一遍。ops 攒到提交时才发，连改三个字段算一次改动。 */

import { el } from "./dom.js";
import { go, back as navBack } from "./nav.js";
import { loadIndex, work } from "./resume.js";

const list = document.getElementById("resume-list");

const row = (entry) => {
  const box = el("button", "rrow");
  box.type = "button";
  const head = el("div", "rrow__head");
  head.append(
    el("span", "rrow__name", entry.career_name ?? entry.career_id ?? ""),
    el("span", "rrow__at", entry.updated_at ?? ""),
  );
  box.append(head);
  // 只说他自己改过几次——那是他的劳动。AI 的评语不进这页，Chat 里已经说过了。
  if (entry.edits_count) box.append(el("p", "rrow__sub", `改过 ${entry.edits_count} 次`));
  box.addEventListener("click", () => {
    location.hash = `#resume/${encodeURIComponent(entry.career_id ?? "")}`;
  });
  return box;
};

const note = (text) => list.replaceChildren(el("p", "placeholder__note", text));

export const loadResume = () =>
  loadIndex().then((rows) => {
    if (!rows) return note("读不到简历，后端可能没重启");
    if (!rows.length) return note("还没有简历。去 Chat 里说个想投的职能，Argus 就会开始挖你的经历");
    list.replaceChildren(...rows.map(row));
  });

const idFromHash = () => {
  const m = /^#resume\/(.+)$/.exec(location.hash);
  return m ? decodeURIComponent(m[1]) : "";
};

/* ── 详情：用户亲手改 ────────────────────────────────────────────────────────
   卡片平时是**只读**的，右上角一个 Edit 图标；点开才变成输入框，改完点提交。
   请求只在提交那一刻发——「改完了提交」是条清楚的边界，不会像自动保存那样
   存进去一半、回头又当成另一次编辑。

   字段自带它改的是哪个 JSON Pointer（data-path），所以整页只挂一个 input
   委托，不用给每个输入框绑一遍。ops 攒到提交时才发，连改三个字段算一次改动。 */

let currentId = "";
let state = null;      // 最近一次从服务器拿到的简历。**只有提交成功才更新**——
let editing = null;    //   取消时靠它把没提交的改动还原回去
const ops = new Map(); // path -> op，同一字段反复改只留最后一次
let chain = Promise.resolve();   // 串行：apply_patch 按下标算，两批并发会打错位置
let seq = 0;           // add 的 path 恒为 `-`，得另给一个不撞的 key

const status = el("p", "redit__status");
const say = (text, bad = false) => {
  status.textContent = text;
  status.classList.toggle("is-bad", bad);
};

// 图标是写死的 markup，innerHTML 只用来装它（与 cards.js 一个做法）；
// 简历里的文字一律走 textContent。
const ICON_EDIT =
  '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
  '<path d="M4 19.9h3.7L19 8.6a2.06 2.06 0 0 0-2.9-2.9L4.9 16.2l-.9 3.7Z" ' +
  'stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>' +
  '<path d="m14.9 7.1 3 3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';

const ICON_TRASH =
  '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
  '<path d="M4.5 7h15M9.5 7V5.6A1.6 1.6 0 0 1 11.1 4h1.8a1.6 1.6 0 0 1 1.6 1.6V7' +
  'M6.8 7l.7 11.3A2 2 0 0 0 9.5 20.1h5a2 2 0 0 0 2-1.8L17.2 7" ' +
  'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const icon = (svg, label, onClick, cls = "redit__ib") => {
  const b = el("button", cls);
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.innerHTML = svg;
  b.addEventListener("click", onClick);
  return b;
};

const push = (op) => ops.set(`#${seq++}`, op);

const post = async (id, batch) => {
  const res = await fetch(`/api/resumes/${encodeURIComponent(id)}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ops: batch, reason: `手改 ${batch.length} 处` }),
  });
  if (!res.ok) {
    const doc = await res.json().catch(() => ({}));
    say(`没存上：${doc.detail || res.status}`, true);
    return null;
  }
  say("");
  return res.json();
};

const flush = () => {
  const batch = [...ops.values()];
  // 目标 id 在入队那一刻就钉住：攒到提交时人可能已经点进另一份简历了。
  const id = currentId;
  ops.clear();
  if (!batch.length) return Promise.resolve(null);
  chain = chain.then(async () => {
    const doc = await post(id, batch);
    if (doc && id === currentId) state = doc;
    return doc;
  });
  return chain;
};

const paint = () => {
  if (state) render(state);
};

const submit = async () => {
  await flush();
  editing = null;
  paint();
};

// 取消 = 这一块没提交过的改动全不要了。state 还是上次从服务器拿的那份，
// 重画一遍就回去了。
const cancel = () => {
  ops.clear();
  editing = null;
  paint();
};

// 同时只改一块。换块之前把手上这批先交了——静默丢掉用户刚敲的字最难受。
const beginEdit = async (key) => {
  if (editing === key) return;
  if (editing) await flush();
  editing = key;
  paint();
};

const field = (path, value, cls, long = false) => {
  const node = document.createElement(long ? "textarea" : "input");
  if (!long) node.type = "text";
  node.className = cls;
  if (long) node.rows = 3;   // 描述是好几句话，input 装不下会截断成一行
  node.value = value ?? "";
  node.dataset.path = path;
  return node;
};

const onInput = (e) => {
  const path = e.target?.dataset?.path;
  if (!path) return;
  ops.set(path, { op: "set", path, value: e.target.value });
};

const add = (label, op) => {
  const b = el("button", "redit__add", label);
  b.type = "button";
  b.addEventListener("click", () => push(op));
  return b;
};

// 「删掉整段经历」要二次确认。这一个 tap 抹掉的是几年经历，不是一行字。
const drop = (label, op) => {
  const b = el("button", "redit__drop");
  b.type = "button";
  b.innerHTML = ICON_TRASH + `<span></span>`;
  b.querySelector("span").textContent = label;
  b.addEventListener("click", () => {
    if (b.dataset.arm) {
      push(op);
      return;
    }
    b.dataset.arm = "1";
    b.querySelector("span").textContent = `真的删？再点一次`;
    setTimeout(() => {
      if (b.dataset.arm) {
        delete b.dataset.arm;
        b.querySelector("span").textContent = label;
      }
    }, 3000);
  });
  return b;
};

// 卡片右上角：平时一个 Edit 图标，正在改就换成 取消 / 提交。
const bar = (key) => {
  const box = el("div", "redit__bar");
  if (editing !== key) {
    box.append(icon(ICON_EDIT, "改这段", () => beginEdit(key)));
    return box;
  }
  const no = el("button", "redit__txt", "取消");
  no.type = "button";
  no.addEventListener("click", cancel);
  const yes = el("button", "redit__ok", "提交");
  yes.type = "button";
  yes.addEventListener("click", submit);
  box.append(no, yes);
  return box;
};

const project = (p, wi, pi) => {
  const box = el("div", "redit__proj");
  box.append(
    field(`/work_history/${wi}/projects/${pi}/name`, p.name, "redit__name"),
    field(`/work_history/${wi}/projects/${pi}/description`, p.description, "redit__area", true),
    icon(ICON_TRASH, "删掉这个项目",
      () => push({ op: "remove", path: `/work_history/${wi}/projects/${pi}` }),
      "redit__ib is-trash"),
  );
  return box;
};

const experience = (w, wi) => {
  const key = `work${wi}`;
  const box = el("section", "redit__work");
  box.append(bar(key));
  if (editing !== key) {
    box.append(work(w));   // 只读那套，Chat 卡片同款
    return box;
  }
  box.append(
    field(`/work_history/${wi}/company`, w.company, "redit__co"),
    field(`/work_history/${wi}/role`, w.role, "redit__role"),
    field(`/work_history/${wi}/start_date`, w.start_date, "redit__date"),
    field(`/work_history/${wi}/end_date`, w.end_date, "redit__date"),
  );
  (w.projects ?? []).forEach((p, pi) => box.append(project(p, wi, pi)));
  box.append(add("＋ 项目", {
    op: "add",
    path: `/work_history/${wi}/projects/-`,
    value: { name: "", description: "" },
  }));
  box.append(drop("删掉整段经历", { op: "remove", path: `/work_history/${wi}` }));
  return box;
};

const skills = (list) => {
  const key = "skills";
  const box = el("section", "redit__sect");
  const head = el("div", "redit__bar");
  head.append(el("h3", "redit__h", "技能"), bar(key));
  box.append(head);

  const chips = el("div", "redit__chips");
  list.forEach((s, i) => {
    const chip = el("span", `redit__skill${editing === key ? "" : " is-plain"}`);
    if (editing === key) {
      chip.append(el("i", null, s), icon(ICON_TRASH, `删掉 ${s}`,
        () => push({ op: "remove", path: `/skills/${i}` }), "redit__ib is-trash is-mini"));
    } else {
      chip.append(el("i", null, s));
    }
    chips.append(chip);
  });

  if (editing === key) {
    const entry = el("input", "redit__addskill");
    entry.type = "text";
    entry.placeholder = "加一项，回车";
    entry.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const text = entry.value.trim();
      if (!text) return;
      e.preventDefault();
      entry.value = "";
      push({ op: "add", path: "/skills/-", value: text });
    });
    chips.append(entry);
  }
  box.append(chips);
  return box;
};

const education = (list) => {
  const key = "edu";
  const box = el("section", "redit__sect");
  const head = el("div", "redit__bar");
  head.append(el("h3", "redit__h", "教育"), bar(key));
  box.append(head);

  list.forEach((e, i) => {
    if (editing !== key) {
      const bits = [e.university, e.degree, e.major].filter(Boolean);
      const span = [e.start_date, e.end_date].filter(Boolean).join("–");
      box.append(el("p", "redit__eduline", [...bits, span].filter(Boolean).join(" · ")));
      return;
    }
    const row = el("div", "redit__edu");
    row.append(
      field(`/education/${i}/university`, e.university, "redit__co"),
      field(`/education/${i}/degree`, e.degree, "redit__date"),
      field(`/education/${i}/major`, e.major, "redit__date"),
      icon(ICON_TRASH, "删掉这段教育",
        () => push({ op: "remove", path: `/education/${i}` }), "redit__ib is-trash"),
    );
    box.append(row);
  });

  if (editing === key) {
    box.append(add("＋ 教育", {
      op: "add",
      path: "/education/-",
      value: { university: "", degree: "", major: "", start_date: "", end_date: "" },
    }));
  }
  return box;
};

const render = (doc) => {
  state = doc;
  currentId = doc.career_id || currentId;
  document.getElementById("resume-htitle").textContent = doc.career_name ?? "简历";
  const kids = (doc.work_history ?? []).map(experience);
  kids.push(add("＋ 一段经历", {
    op: "add",
    path: "/work_history/-",
    value: { company: "", role: "", start_date: "", end_date: "", projects: [] },
  }));
  kids.push(skills(doc.skills ?? []), education(doc.education ?? []), status);
  const host = document.getElementById("resume-body");
  host.replaceChildren(...kids);
  host.oninput = onInput;
  say("");
};

let shown = "";
const show = async (id) => {
  if (!id || shown === id) return;
  // 上一份还没提交的改动要先走完再换人，否则会落到刚打开的那份简历头上。
  if (editing) await flush();
  const doc = await fetch(`/api/resumes/${encodeURIComponent(id)}`)
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  // 简历可能刚被删掉：留在原地，别开一个空页
  if (!doc) return;
  shown = id;
  editing = null;
  render(doc);
  go("resumedit");
};

const close = () => {
  shown = "";
  // 没提交就退出的，靠 pagehide 那道保险兜底；这里再发一次是双保险。
  if (editing) flush();
  // 直接粘链接进来的：hash 还在，清掉，否则下次刷新又会弹回详情页
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  navBack();
};

export const initResumeDetail = () => {
  // 关标签页 / 切到后台：还在编辑态、没点提交的那批赶紧发出去，否则敲的字白敲。
  // 点了「取消」的话 ops 是空的，这道保险自然什么都不做。
  addEventListener("pagehide", () => { if (editing) flush(); });
  document.getElementById("resume-back").addEventListener("click", () => {
    // 从站内列表进来的：交给浏览器历史，iPhone 侧滑返回才对得上。
    if (history.state?.resume) history.back();
    else close();
  });
  addEventListener("hashchange", () => {
    const id = idFromHash();
    if (id) {
      // 锚点点击已经压了一条历史，这里只补 state，让返回键知道该往回退。
      history.replaceState({ resume: id }, "", `#resume/${encodeURIComponent(id)}`);
      return show(id);
    }
    // 同 job.js：岗位详情也用 hash（#job/<id>），那个 handler 比我们先注册、先跑。
    // 「不是我的 hash」不等于「关闭」，否则被它清掉 hash，这里读到的也是空。
    if (location.hash) return;
    close();
  });
  const id = idFromHash();
  if (id) show(id);
};