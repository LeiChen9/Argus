/* Jobs 页：渲染 data/jobs.json 里的持久化岗位。 */

import { jobCard } from "./cards.js";
import { api, errNote, readJson } from "./api.js";

const meta = document.getElementById("jobs-meta");
const grid = document.getElementById("jobs-grid");

export const loadJobs = () => {
  api("/api/jobs")
    .then(readJson)
    .then(({ updated_at, jobs }) => {
      meta.textContent = updated_at ? `${jobs.length} 个活跃岗位 · 更新于 ${updated_at}` : "";
      if (!jobs.length) {
        const note = document.createElement("p");
        note.className = "placeholder__note";
        note.textContent = "还没有岗位，去 Chat 里让 Argus 搜一轮吧";
        grid.replaceChildren(note);
        return;
      }
      grid.replaceChildren(...jobs.map(jobCard));
    })
    .catch((e) => {
      meta.textContent = "";
      grid.replaceChildren(errNote(e, "取岗位"));
    });
};
