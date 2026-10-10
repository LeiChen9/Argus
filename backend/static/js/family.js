/* Career 页：岗位族（S1 产物）。族卡片常驻定位与判据，能力与岗位收进两个
   默认折叠，折叠用 dom.js 的 fold()（原生 details）。 */

import { el, fold } from "./dom.js";
import { jobCards } from "./cards.js";

const stage = document.getElementById("view-career");

const LEVEL = { core: "核心", important: "重要", bonus: "加分" };

const capability = (c) => {
  const node = el("div", "fam__cap");
  node.append(
    el("i", `fam__lvl is-${c.level}`, LEVEL[c.level] ?? c.level),
    el("span", "fam__capn", c.capability),
    el("p", "fam__ev", c.jd_evidence),
  );
  return node;
};

// 定位与判据常驻：它俩是判断「这些岗位是不是一族」的唯一依据，藏进折叠里等于没写。
const family = (f) => {
  const box = el("div", "fam");
  const caps = (f.capabilities ?? []).map(capability);
  box.append(
    el("h2", "fam__name", `${f.name} · ${f.jobs.length} 个岗位`),
    el("p", "fam__pos", f.positioning),
    el("p", "fam__crit", f.membership_criteria),
    fold(`能力要求 ${caps.length} 条`, ...caps),
    fold(`岗位 ${f.jobs.length} 个`, jobCards(f.jobs)),
  );
  return box;
};

export const loadCareer = () =>
  fetch("/api/families")
    .then((res) => (res.ok ? res.json() : null))
    // 区分「取不到」和「还没有」：后端没重启时这接口是 404，冒充成「还没跑
    // S1」是骗人——S1 可能早就跑过了，文件就在 data/ 里躺着。
    .then((doc) => {
      if (!doc) return stage.replaceChildren(el("p", "placeholder__note", "读不到岗位族，后端可能没重启"));
      if (doc.families.length) stage.replaceChildren(...doc.families.map(family));
    });