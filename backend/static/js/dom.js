/* 极小的 DOM 工具：job.js 和 analysis.js 都要用 el/deRadical，
   单独成文件是为了不出现 analysis ← job ← analysis 的循环依赖。 */

// 抓取器的字体解码会把常用字还原成康熙部首（建⽴⽬标）。只对这几个码位段做
// NFKC——整串 NFKC 会把全角逗号也压成半角。LLM 引用的 JD 原文同样带着这些部首
// （实测 23 处），所以解读里的 jd_raw_context / pitch_narrative 也要过一遍。
const RADICALS = new RegExp(
  "[\\u2E80-\\u2EFF\\u2F00-\\u2FDF\\uF900-\\uFAFF\\uFE30-\\uFE4F]",
  "g",
);

export const deRadical = (s) => String(s ?? "").replace(RADICALS, (c) => c.normalize("NFKC"));

// 第三参是 textContent，不是子节点。要塞子节点请用 append。
export const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};

// <details> 折叠：原生行为，键盘和读屏都免费，不用自己写 accordion。
export const fold = (summaryText, ...kids) => {
  const box = el("details", "ai__fold");
  const sum = el("summary", "ai__sum");
  sum.append(el("span", "ai__sumt", summaryText), el("i", "ai__chev"));
  box.append(sum, ...kids);
  return box;
};