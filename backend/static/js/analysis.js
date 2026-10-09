/* AI 解读：渲染 /api/jobs/<id>/analysis 的内容，并生成可复制的准备清单。

   键名和取值都出自 LLM 自由输出，这一批实测并不齐：30 个岗位里有 1 个把
   openning 写成 opening，defensive_script 的文案键有四种变体（实测 76 条全都
   带 mitigation_angle，其余是重复而非替代），293 条要求里有 43 条的 gap_details
   只有 has_gap。所以下面一律 ?? 兜底，不假定结构完整。 */

import { deRadical, el, fold } from "./dom.js";

const CATEGORY = {
  apply_now: "建议投递",
  build_evidence_then_apply: "补证据后投",
  learn_then_apply: "先学再投",
  develop_then_apply: "长期储备",
  deprioritize: "暂不优先",
};

// 每张卡片带一句"凭什么"，光有"已证明"三个字看不出是拿什么证明的。
const MATCH = {
  proven: { label: "已证明", cls: "ok", desc: "有直接对应的经历" },
  transferable: { label: "可迁移", cls: "mv", desc: "能力相通，场景要换" },
  gap: { label: "缺口", cls: "gap", desc: "没有相关经验" },
  unknown: { label: "待确认", cls: "unk", desc: "简历里看不出来" },
};

const CONF = { high: "高", medium: "中", low: "低" };

// LLM 只给 aligned / above_target 这类状态，没说是跟什么对齐。
// 目标值随解读一起下发（见 jobs.py 的 target），这里拼成完整的一句话。
const INTENT = {
  aligned: (t, want) => `${t}符合你的意向${want}`,
  conflict: (t, want) => `${t}与你的意向${want}不符`,
  above_target: (t, want) => `${t}高于你的意向${want}`,
  below_target: (t, want) => `${t}低于你的意向${want}`,
};

const DIFF = { hard: "难", medium: "中", easy: "轻" };
const DIFF_RANK = { hard: 2, medium: 1, easy: 0 };
const EFFORT = { heavy_project: "重", medium_effort: "中", low_cost_fast: "轻" };

const matchOf = (q) => MATCH[q.match_status] ?? { label: q.match_status ?? "—", cls: "unk" };
const reqs = (a) => (Array.isArray(a?.requirements_deep_dive) ? a.requirements_deep_dive : []);
const evidenceOf = (q) =>
  (Array.isArray(q.persona_evidence) ? q.persona_evidence : []).filter(Boolean);
const openingOf = (a) => a.openning ?? a.opening;

// gap_canonical_tag -> bridge_difficulty，用来给补齐行动排序：难补的排前面。
const difficultyOf = (list) => {
  const map = new Map();
  for (const q of list) {
    const g = q.gap_details ?? {};
    if (g.has_gap && g.gap_canonical_tag) map.set(g.gap_canonical_tag, g.bridge_difficulty);
  }
  return map;
};

const copy = async (text, btn) => {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // 局域网 http 访问不是安全上下文，没有 clipboard API。退回选中，用户自己复制。
    const ta = el("textarea");
    ta.value = text;
    ta.className = "ai__ta";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    ta.remove();
    return;
  }
  const label = btn.textContent;
  btn.textContent = "已复制";
  btn.classList.add("is-done");
  setTimeout(() => {
    btn.textContent = label;
    btn.classList.remove("is-done");
  }, 1200);
};

const copyBtn = (text, label = "复制") => {
  const btn = el("button", "ai__copy", label);
  btn.type = "button";
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    copy(text, btn);
  });
  return btn;
};

const reqItem = (q) => {
  const m = matchOf(q);
  const node = el("div", "ai__req");

  const head = el("div", "ai__rhead");
  const gap = q.gap_details ?? {};
  const tags = el("span", "ai__rtags");
  tags.appendChild(el("i", `ai__tag is-${m.cls}`, m.label));
  if (gap.has_gap && gap.bridge_difficulty) {
    tags.appendChild(el("i", "ai__tag is-diff", `补齐${DIFF[gap.bridge_difficulty] ?? ""}`));
  }
  head.append(
    el("span", "ai__rtext", deRadical(q.jd_raw_context) || "（未摘录 JD 原文）"),
    tags,
  );
  node.appendChild(head);

  const evidence = evidenceOf(q);
  const hasGapText = gap.has_gap && gap.gap_description;
  if (!evidence.length && !hasGapText) return node;

  const body = el("div", "ai__rbody");
  if (evidence.length) {
    const ul = el("ul", "ai__ev");
    evidence.forEach((e) => ul.appendChild(el("li", null, deRadical(e))));
    body.appendChild(ul);
  }
  if (hasGapText) body.appendChild(el("p", "ai__gap", deRadical(gap.gap_description)));

  let what = evidence.length ? `${evidence.length} 条证据` : "";
  if (hasGapText) what += evidence.length ? " · 缺口说明" : "缺口说明";
  node.appendChild(fold(what, body));
  return node;
};

// 原来是一条 6px 细条 + 一行小字图例，四种颜色靠盯着 6px 去分辨，手机上很难受。
// 改成卡片：每种状态一张，数字大到能一眼扫到，下面写清"凭什么算这一类"。
const overview = (list) => {
  const counts = {};
  list.forEach((q) => {
    const k = MATCH[q.match_status] ? q.match_status : "unknown";
    counts[k] = (counts[k] ?? 0) + 1;
  });
  const total = list.length || 1;
  const present = Object.keys(MATCH).filter((k) => counts[k]);
  const ov = el("div", "ai__ov");
  ov.setAttribute("aria-label", `全部 ${list.length} 项要求的匹配分布`);

  const grid = el("div", "ai__cards");
  for (const k of present) {
    const card = el("div", `ai__card is-${MATCH[k].cls}`);
    card.append(
      el("span", "ai__cardn", String(counts[k])),
      el("span", "ai__cardl", MATCH[k].label),
      el("span", "ai__cardd", MATCH[k].desc),
    );
    grid.appendChild(card);
  }
  ov.appendChild(grid);

  const bar = el("div", "ai__bar");
  bar.setAttribute("aria-hidden", "true");
  for (const k of present) {
    const seg = el("i", `ai__seg is-${MATCH[k].cls}`);
    seg.style.width = `${(counts[k] / total) * 100}%`;
    bar.appendChild(seg);
  }
  ov.appendChild(bar);
  return ov;
};

const reqSection = (list) => {
  const core = list.filter((q) => q.weight === "core");
  const rest = list.filter((q) => q.weight !== "core");
  const wrap = el("div", "ai__sec");
  wrap.appendChild(el("h3", "ai__h", `核心要求 ${core.length}`));
  core.forEach((q) => wrap.appendChild(reqItem(q)));
  if (rest.length) {
    // important / bonus 不影响投不投的判断，默认收起来，只在概览里计入分母。
    wrap.appendChild(fold(`展开全部 ${list.length} 项要求（含 ${rest.length} 项非核心）`, ...rest.map(reqItem)));
  }
  return wrap;
};

const strategySection = (a) => {
  const s = a.interview_strategy ?? {};
  const pitches = (Array.isArray(s.leverage_pitch) ? s.leverage_pitch : []).filter(Boolean);
  const defense = (Array.isArray(s.defensive_script) ? s.defensive_script : []).filter(Boolean);
  const body = el("div", "ai__sec");

  for (const p of pitches) {
    const item = el("div", "ai__blk");
    item.append(
      el("p", "ai__blkh", p.strength_point ?? ""),
      el("p", "ai__txt", deRadical(p.pitch_narrative)),
    );
    if (p.mapped_project) item.appendChild(el("p", "ai__blkmeta", `对应经历：${p.mapped_project}`));
    body.appendChild(item);
  }

  for (const d of defense) {
    const item = el("div", "ai__blk ai__blk--warn");
    item.append(
      el("p", "ai__blkh", `可能被追问：${d.potential_concern ?? ""}`),
      el("p", "ai__txt", deRadical(d.mitigation_angle)),
    );
    body.appendChild(item);
  }

  if (!body.childNodes.length) return null;
  return fold(`面试打法 ${pitches.length} 个卖点 · ${defense.length} 个防守点`, body);
};

const actionSection = (a, diff) => {
  const acts = Array.isArray(a.actions) ? a.actions.filter(Boolean) : [];
  if (!acts.length) return null;
  const rank = (act) => DIFF_RANK[diff.get(act.target_gap_tag)] ?? 0;
  const sorted = [...acts].sort((x, y) => rank(y) - rank(x)); // 难补的排前面
  const body = el("div", "ai__sec");

  sorted.forEach((act, i) => {
    const item = el("div", "ai__blk");
    const head = el("p", "ai__blkh", `${i + 1}. ${act.task_description ?? ""}`);
    const effort = EFFORT[act.estimated_effort] ?? "";
    const d = DIFF[diff.get(act.target_gap_tag)] ?? "";
    if (effort || d) {
      const tags = el("span", "ai__rtags");
      if (effort) tags.appendChild(el("i", "ai__tag is-eff", `投入${effort}`));
      if (d) tags.appendChild(el("i", "ai__tag is-diff", `补齐${d}`));
      head.appendChild(tags);
    }
    item.appendChild(head);
    if (act.expected_deliverable) {
      item.appendChild(el("p", "ai__txt", `交付物：${act.expected_deliverable}`));
    }
    body.appendChild(item);
  });
  return fold(`补齐行动 ${acts.length} 项 · 按难度排序`, body);
};

const checklist = (job, doc) => {
  const a = doc.analysis ?? {};
  const list = reqs(a);
  const diff = difficultyOf(list);
  const opening = openingOf(a);
  const lines = [
    `【${job.title}】${job.company}`,
    `【建议】${CATEGORY[a.decision?.cluster_category] ?? ""} · 把握度${CONF[a.decision?.confidence] ?? ""}`,
    "",
    "一、核心差距",
    ...list
      .filter((q) => q.weight === "core" && q.gap_details?.has_gap)
      .map(
        (q, i) =>
          `${i + 1}. [${DIFF[q.gap_details.bridge_difficulty] ?? ""}] ${deRadical(q.jd_raw_context)}\n   ${deRadical(q.gap_details.gap_description)}`,
      ),
    "",
    "二、补齐行动",
    ...(a.actions ?? []).map(
      (act, i) =>
        `${i + 1}. ${act.task_description}\n   交付物：${act.expected_deliverable}\n   难度：${DIFF[diff.get(act.target_gap_tag)] ?? "-"} / 投入${EFFORT[act.estimated_effort] ?? "-"}`,
    ),
  ];
  if (opening) lines.push("", "三、开场白", deRadical(opening));
  return lines.join("\n");
};

// 模型给的推论单独包一层 details：JD 是原始依据，解读是二手判断，
// 折叠起来让用户在需要时自己打开，而不是被推着先读一段 AI 的话。
export const aiSection = (job, doc) => {
  const a = doc.analysis ?? {};
  const dec = a.decision ?? {};
  const cat = CATEGORY[dec.cluster_category] ?? "—";
  const list = reqs(a);
  const diff = difficultyOf(list);

  const wrap = el("details", "ai__wrap");
  const sum = el("summary", "ai__wsum");
  sum.append(
    el("span", "ai__wttl", "AI 解读"),
    el("span", `ai__wcat is-${dec.cluster_category ?? ""}`, cat),
    el("i", "ai__chev"),
  );

  const box = el("div", "ai__box");
  const stamp = [doc.generated_at, doc.model].filter(Boolean).join(" · ");
  if (stamp) box.appendChild(el("p", "ai__stamp", stamp));

  const verdict = el("div", "ai__verdict");
  verdict.append(
    el("span", `ai__badge is-${dec.cluster_category ?? ""}`, cat),
    el("span", "ai__conf", `把握度 ${CONF[dec.confidence] ?? "—"}`),
  );
  box.appendChild(verdict);

  // "已对齐"这种话没主语，这里补上跟什么对齐：地点对 target_base，薪资对 target_salary。
  const im = a.intent_match ?? {};
  const meta = el("div", "ai__chips");
  [
    [im.location_status, "地点", doc.target?.target_base],
    [im.salary_status, "薪资", doc.target?.target_salary],
  ].forEach(([status, label, want]) => {
    if (!status) return;
    const say = INTENT[status]?.(label, want ? ` ${want}` : "") ?? `${label}${status}`;
    meta.appendChild(el("p", `ai__meta is-${status}`, say));
  });
  if (meta.childNodes.length) box.appendChild(meta);

  if (dec.matching_rationale) box.appendChild(el("p", "ai__why", deRadical(dec.matching_rationale)));
  if (list.length) box.appendChild(overview(list));

  const rs = reqSection(list);
  if (rs.childNodes.length) box.appendChild(rs);

  for (const sec of [strategySection(a), actionSection(a, diff)]) {
    if (sec) box.appendChild(sec);
  }

  const opening = openingOf(a);
  if (opening) {
    const text = deRadical(opening);
    const open = el("div", "ai__open");
    open.append(
      el("p", "ai__blkh", "开场白"),
      el("p", "ai__txt", text),
      copyBtn(text),
    );
    box.appendChild(open);
  }

  const foot = el("div", "ai__foot");
  foot.appendChild(copyBtn(checklist(job, doc), "复制准备清单"));
  box.appendChild(foot);

  wrap.append(sum, box);
  return wrap;
};