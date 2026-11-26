/* 岗位详情：路径是 /job/<id>，这里按路径找岗位渲染。
   岗位数据来自 /api/jobs 全量返回 + cards 渲染时顺手 remember 进来的当轮岗位。 */

import { go, back as navBack, onLeave, routeId } from "./nav.js";
import { deRadical, el } from "./dom.js";
import { api, readJson } from "./api.js";

export const SOURCE = { boss_recommend: "BOSS直聘·为你推荐", liepin: "猎聘" };

const remembered = new Map();
let store = null; // /api/jobs 的结果，懒加载一次

export const remember = (job) => {
  if (job?.id) remembered.set(job.id, job);
};

const find = async (id) => {
  if (remembered.has(id)) return remembered.get(id);
  store ??= api("/api/jobs")
    .then(readJson)
    .then((d) => {
      (d.jobs ?? []).forEach(remember);
      return d;
    })
    .catch((e) => { store = null; throw e; });
  await store;
  return remembered.get(id);
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

  // JD 是投递的原始依据，默认展开。
  kids.push(el("pre", "jdetail__jd", deRadical(job.jd) || "（暂无职位描述）"));

  document.getElementById("job-body").replaceChildren(...kids);
};

let shown = "";
const show = async (id) => {
  let job;
  try {
    job = await find(id);
  } catch {
    return;
  }
  if (!job) return; // 岗位已被新快照覆盖：留在原地，别开一个空页
  if (shown === id || routeId() !== id) return;
  shown = id;
  render(job);
  go("job");
};

// 站内点击卡片：压一条历史再渲染，返回键/iPhone 侧滑才对得上。
export const openJob = (id, push = false) => {
  if (!id) return;
  if (push) history.pushState({ view: "job" }, "", `/job/${encodeURIComponent(id)}`);
  show(id);
};

const close = () => {
  shown = "";
  navBack();
};

// 离开岗位详情（点卡片去别处、点 logo、后退）时清掉当前 id，
// 下次点同一个岗位才会重渲染。
onLeave("job", () => { shown = ""; });

export const initJobDetail = () => {
  const backBtn = document.getElementById("job-back");
  backBtn.addEventListener("click", () => {
    // 从站内卡片进来的：交给浏览器历史，iPhone 侧滑返回才对得上。
    if (history.state?.view === "job") history.back();
    else close();
  });
};