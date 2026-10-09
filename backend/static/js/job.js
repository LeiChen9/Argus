/* 岗位详情：卡片是 #job/<id> 锚点，这里按 hash 找岗位渲染。
   数据来自 /api/jobs 全量返回 + cards 渲染时顺手 remember 进来的当轮岗位，
   后端不用为详情页加任何接口。 */

import { go, back as navBack } from "./nav.js";

export const SOURCE = { boss_recommend: "BOSS直聘·为你推荐", liepin: "猎聘" };

const remembered = new Map();
let store = null; // /api/jobs 的结果，懒加载一次

export const remember = (job) => {
  if (job?.id) remembered.set(job.id, job);
};

const idFromHash = () => {
  const m = /^#job\/(.+)$/.exec(location.hash);
  return m ? decodeURIComponent(m[1]) : "";
};

const find = async (id) => {
  if (remembered.has(id)) return remembered.get(id);
  store ??= fetch("/api/jobs")
    .then((r) => r.json())
    .then((d) => {
      (d.jobs ?? []).forEach(remember);
      return d;
    });
  await store;
  return remembered.get(id);
};

// 抓取器的字体解码会把常用字还原成康熙部首（建⽴⽬标）。只对这几个码位段做
// NFKC——整串 NFKC 会把全角逗号也压成半角。
const RADICALS = new RegExp(
  "[\\u2E80-\\u2EFF\\u2F00-\\u2FDF\\uF900-\\uFAFF\\uFE30-\\uFE4F]",
  "g",
);
const deRadical = (s) => String(s ?? "").replace(RADICALS, (c) => c.normalize("NFKC"));

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};

const row = (label, value) => {
  if (!value) return null;
  const node = el("div", "jdetail__row");
  node.append(el("span", "jdetail__label", label), el("span", "jdetail__val", value));
  return node;
};

const chips = (label, value) => {
  const list = (Array.isArray(value) ? value : String(value ?? "").split(/[|,、]/))
    .map((v) => String(v).trim())
    .filter(Boolean);
  if (!list.length) return null;
  const node = el("div", "jdetail__row");
  const wrap = el("span", "jdetail__chips");
  list.forEach((v) => wrap.appendChild(el("i", "jchip", v)));
  node.append(el("span", "jdetail__label", label), wrap);
  return node;
};

const render = (job) => {
  document.getElementById("job-htitle").textContent = job.title || "岗位详情";
  const cta = document.getElementById("job-cta");
  cta.textContent = job.source === "boss_recommend" ? "去 BOSS 直聘投递" : "去猎聘投递";
  cta.href = job.link || "#";

  const meta = el("p", "jdetail__meta");
  meta.append(el("span", "jdetail__salary", job.salary), el("span", "jdetail__company", job.company));

  const rows = [
    row("地点", job.location),
    chips("要求", job.tags),
    chips("技能标签", job.skill_tags),
    row("公司规模", job.company_scale),
    row("融资阶段", job.company_stage),
    row("行业", job.company_industry),
    chips("福利", job.welfare),
    chips("技能要求", job.skills),
    chips("标签", job.job_labels),
    row("HR", job.boss_title),
    row("HR 活跃", job.boss_active_status),
    row("来源", SOURCE[job.source] ?? job.source),
    row("采集于", job.collected_at),
  ].filter(Boolean);

  const kids = [el("h1", "jdetail__title", job.title), meta];
  if (rows.length) {
    const box = el("div", "jdetail__rows");
    box.append(...rows);
    kids.push(box);
  }
  kids.push(el("pre", "jdetail__jd", deRadical(job.jd) || "（暂无职位描述）"));
  document.getElementById("job-body").replaceChildren(...kids);
};

let shown = "";
const show = async (id) => {
  const job = await find(id);
  if (!job) return; // 岗位已被新快照覆盖：留在原地，别开一个空页
  if (shown === id) return;
  shown = id;
  render(job);
  go("job");
};

const close = () => {
  shown = "";
  // 直接粘链接进来的：hash 还在，清掉，否则下次刷新又会弹回详情页
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  navBack();
};

export const initJobDetail = () => {
  const backBtn = document.getElementById("job-back");
  backBtn.addEventListener("click", () => {
    // 从站内卡片进来的：交给浏览器历史，iPhone 侧滑返回才对得上。
    if (history.state?.job) history.back();
    else close();
  });
  addEventListener("hashchange", () => {
    const id = idFromHash();
    if (!id) return close();
    // 锚点点击已经压了一条历史，这里只补 state，让返回键知道该往回退。
    history.replaceState({ job: id }, "", `#job/${encodeURIComponent(id)}`);
    show(id);
  });
  const id = idFromHash();
  if (id) show(id);
};