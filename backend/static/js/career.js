/* Career 页：Career 卡片（S1 产物）。定位与归属判据常驻，能力与岗位收进两个
   默认折叠，折叠用 dom.js 的 fold()（原生 details）。已写过简历的 Career 在标题下
   多挂一条 resumeLink 软链——软链是因为简历正文在 chat 里看，那里才是聊它的场合。 */

import { el, fold } from "./dom.js";
import { jobCards } from "./cards.js";
import { fetchResumes, resumeLink } from "./resume.js";
import { api } from "./api.js";

const stage = document.getElementById("view-career");

const LEVEL = { core: "核心", important: "重要", bonus: "加分" };

const capability = (c) => {
  const node = el("div", "career__cap");
  node.append(
    el("i", `career__lvl is-${c.level}`, LEVEL[c.level] ?? c.level),
    el("span", "career__capn", c.capability),
    el("p", "career__ev", c.jd_evidence),
  );
  return node;
};

// 定位与判据常驻：它俩是判断「这些岗位是不是同一个 Career」的唯一依据，藏进折叠里等于没写。
const career = (f, resume) => {
  const box = el("div", "career");
  const caps = (f.capabilities ?? []).map(capability);
  box.append(
    el("h2", "career__name", `${f.name} · ${f.jobs.length} 个岗位`),
    el("p", "career__pos", f.positioning),
    el("p", "career__crit", f.membership_criteria),
  );
  if (resume) box.append(resumeLink(resume));
  box.append(fold(`能力要求 ${caps.length} 条`, ...caps), fold(`岗位 ${f.jobs.length} 个`, jobCards(f.jobs)));
  return box;
};

export const loadCareer = () =>
  Promise.all([
    api("/api/careers").then((res) => (res.ok ? res.json() : null)),
    fetchResumes(),
  ]).then(([doc, resumes]) => {
    // 区分「取不到」和「还没有」：后端没重启时这接口是 404，冒充成「还没跑
    // S1」是骗人——S1 可能早就跑过了，文件就在 data/ 里躺着。
    if (!doc) {
      stage.replaceChildren(el("p", "placeholder__note", "读不到 Career，后端可能没重启"));
      return;
    }
    if (doc.careers.length) {
      stage.replaceChildren(...doc.careers.map((f) => career(f, resumes.get(f.career_id))));
    }
  });