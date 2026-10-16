/* 简历的**共享件**：Chat 里的全文卡、Career 页的软链、以及索引数据。
   Resume 页自己那份在 resumepage.js——组件被谁消费就跟谁，拆开跟 cards.js / job.js
   一个路子（那两个是岗位卡与岗位详情）。

   全文卡不进 markdown 管道：简历是结构化数据，交给 render_markdown 等于让它被
   当成模型的话再解释一遍——这里只排版，不改写。

   **Resume 页不挂 AI 的评语**：评语是 Argus 在 Chat 里说的话，已经说过了。verdict /
   one_line 仍然随索引返回，Career 页的软链要显示它们。 */

import { el, fold } from "./dom.js";
import { go } from "./nav.js";
import { api, errNote } from "./api.js";

const VERDICT_CLASS = { 进面试: "is-in", 边缘: "is-edge", 不进: "is-out" };

const verdictTag = (verdict) =>
  el("i", `rcard__v ${VERDICT_CLASS[verdict] ?? ""}`, verdict || "还没筛");

/** 一段工作经历的只读渲染。Chat 卡片和 Resume 页的只读态共用同一份排版。 */
export const work = (w) => {
  const box = el("div", "rcard__work");
  box.append(
    el("h4", "rcard__role", [w.role, w.company].filter(Boolean).join(" · ")),
    el("p", "rcard__span", [w.start_date, w.end_date].filter(Boolean).join(" – ")),
  );
  const list = el("ul", "rcard__projs");
  (w.projects ?? []).forEach((p) => {
    // 项目名是扫读时唯一会被抓住的东西，单独提出来加重；描述压成次级。
    const li = el("li", "rcard__proj");
    li.append(el("strong", "", p.name), ` ${p.description}`);
    list.append(li);
  });
  if (list.children.length) box.append(list);
  return box;
};

/** Chat 里的全文卡。resume 是 /api/resumes/{id} 的返回。 */
export const resumeCard = (resume) => {
  const box = el("div", "rcard");
  const head = el("div", "rcard__head");
  head.append(
    el("span", "rcard__cname", `${resume.career_name ?? ""} · 简历`.trim()),
    el("span", "rcard__at", resume.updated_at ?? ""),
  );
  box.append(head);

  const review = resume.review ?? {};
  if (review.verdict || review.one_line) {
    const v = el("div", "rcard__verdict");
    v.append(verdictTag(review.verdict), el("p", "rcard__line", review.one_line ?? ""));
    box.append(v);
  }

  (resume.work_history ?? []).forEach((w) => box.append(work(w)));

  const skills = resume.skills ?? [];
  if (skills.length) {
    box.append(fold(`技能 ${skills.length} 项`, el("p", "rcard__tags", skills.join(" · "))));
  }

  // 缺口不是这份简历的缺陷，是下一轮该问什么——所以单独拎出来，不混在工作经历里。
  const gaps = review.needs_mining ?? [];
  if (gaps.length) {
    const list = el("ul", "rcard__gaps");
    gaps.forEach((g) => list.append(el("li", "", [g.capability, g.ask].filter(Boolean).join(" —— "))));
    box.append(fold(`还缺 ${gaps.length} 处，只能继续问他`, list));
  }

  // 改过几次是有用信息：这一版是第几版、上次为什么改的。
  const edits = resume.edits ?? [];
  if (edits.length) {
    const last = edits[edits.length - 1];
    box.append(el("p", "rcard__edit", `改过 ${edits.length} 次 · ${last.reason ?? ""}`));
  }
  return box;
};

/** Career 页卡片里的软链：只报状态与结论，点进去是 chat。
    后端的简历模式是进程内状态，从 Career 页跳过去时 agent 本来就知道在聊哪份，
    所以链接不用带 career_id。 */
export const resumeLink = (entry) => {
  const box = el("button", "rcard__link");
  box.type = "button";
  const top = el("div", "rcard__linktop");
  top.append(
    el("span", "rcard__linkttl", "已有一份简历"),
    el("span", "rcard__at", entry.updated_at ?? ""),
  );
  box.append(top, verdictTag(entry.verdict));
  if (entry.one_line) box.append(el("p", "rcard__line", entry.one_line));
  if ((entry.needs_mining ?? []).length) {
    box.append(el("p", "rcard__gapn", `还缺 ${entry.needs_mining.length} 处，去聊`));
  }
  box.addEventListener("click", () => go("chat"));
  return box;
};

/** 简历索引，Chat 卡片之外的两处都要：Resume 页列表、Career 页软链。
    后端在 GET 上补齐每个 Career 的底稿，所以拉一次就够，别各处各拉一遍。 */
// 取不到就把原因带出去：连着 null 吞掉的话，页面上只剩一句「后端可能没
// 重启」，而实际是会话掉了 / 500——两种病两种药。
export const loadIndex = () =>
  api("/api/resumes")
    .then((res) => (res.ok ? res.json() : Promise.reject(Object.assign(new Error(`HTTP ${res.status}`), { status: res.status }))))
    .then((doc) => doc?.resumes ?? null)
    .catch((e) => { throw e; });

/** Career 页用：索引转成 career_id → 条目的表。取不到就当没有，不报错。 */
export const fetchResumes = () =>
  loadIndex().then((rows) => new Map((rows ?? []).map((r) => [r.career_id, r])));
