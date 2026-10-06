/* 岗位卡片组件：Chat 横滑轨道与 Jobs 页网格共用。 */

const SOURCE = { boss_recommend: "BOSS直聘·为你推荐", liepin: "猎聘" };

export const jobCard = (job) => {
  const a = document.createElement("a");
  a.className = "jobcard";
  a.href = job.link || "#";
  a.target = "_blank";
  a.rel = "noreferrer";
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
