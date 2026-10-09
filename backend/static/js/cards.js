/* 岗位卡片组件：Chat 横滑轨道与 Jobs 页网格共用。
   卡片是站内 hash 锚点（#job/<id>），不是外链——投递才是唯一离开本站的动作。
   渲染时顺手把 job 交给详情页存着，省掉详情页为 chat 当轮的岗位再发一次请求。 */

import { remember, SOURCE } from "./job.js";

export const jobCard = (job) => {
  remember(job);
  const a = document.createElement("a");
  a.className = "jobcard";
  a.href = `#job/${encodeURIComponent(job.id ?? "")}`;
  a.innerHTML =
    '<div class="jobcard__top"><span class="jobcard__title"></span><span class="jobcard__salary"></span></div>' +
    '<p class="jobcard__company"></p><p class="jobcard__meta"></p><p class="jobcard__foot"></p>';
  a.querySelector(".jobcard__title").textContent = job.title;
  a.querySelector(".jobcard__salary").textContent = job.salary;
  a.querySelector(".jobcard__company").textContent = job.company;
  a.querySelector(".jobcard__meta").textContent = [job.location, job.tags].filter(Boolean).join(" · ");
  a.querySelector(".jobcard__foot").textContent = `${SOURCE[job.source] ?? job.source} · ${job.collected_at ?? ""}`;
  return a;
};

export const jobCards = (jobs) => {
  const rail = document.createElement("div");
  rail.className = "jobcards";
  jobs.forEach((job) => rail.appendChild(jobCard(job)));
  return rail;
};