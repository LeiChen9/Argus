/* Jobs 页：渲染 data/jobs.json 里的持久化岗位。 */

import { jobCard } from "./cards.js";
import { api, errNote, readJson } from "./api.js";

const meta = document.getElementById("jobs-meta");
const grid = document.getElementById("jobs-grid");

const mk = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};

const ICON_GLOBE = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="8.2" stroke="currentColor" stroke-width="1.7"/><path d="M4 12h16M12 3.8c2.6 2.2 2.6 14.2 0 16.4M12 3.8c-2.6 2.2-2.6 14.2 0 16.4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
const ICON_TERM = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 7.5 9.2 12 5 16.5M12.5 17h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const ICON_REFRESH = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M19 12a7 7 0 1 1-2.1-5M19 5v4h-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const icon = (svg) => {
  const node = mk("span", "jobs-guide__icon");
  node.innerHTML = svg;
  return node;
};

const copyText = async (text, button) => {
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "已复制";
  } catch {
    button.textContent = "复制失败";
  }
  setTimeout(() => { button.textContent = "复制"; }, 1600);
};

const command = (text) => {
  const row = mk("div", "jobs-guide__cmd");
  const code = mk("code", null, text);
  const button = mk("button", "jobs-guide__copy", "复制");
  button.type = "button";
  button.addEventListener("click", () => copyText(text, button));
  row.append(code, button);
  return row;
};

const row = (svg, title, text, extra) => {
  const node = mk("div", "jobs-guide__row");
  const body = mk("div", "jobs-guide__body");
  body.append(mk("b", null, title), mk("p", null, text));
  if (extra) body.append(extra);
  node.append(icon(svg), body);
  return node;
};

const guide = (user) => {
  const box = mk("section", "jobs-guide");
  const head = mk("header", "jobs-guide__head");
  head.append(
    mk("h2", "jobs-guide__title", "设置岗位库"),
    mk("p", "jobs-guide__sub", "在电脑上完成一次，之后回来刷新。"),
  );

  const group = mk("div", "jobs-guide__group");
  group.append(
    row(ICON_GLOBE, "登录 BOSS", "在独立 Chrome 里登录自己的账号。", command("bash scripts/setup_boss.sh")),
    row(ICON_TERM, "采集岗位", "运行后会把岗位推到你的账号。", command(`ARGUS_USER=${user} bash scripts/crawl_jobs.sh`)),
  );

  const refresh = mk("button", "jobs-guide__row jobs-guide__row--action");
  refresh.type = "button";
  const body = mk("div", "jobs-guide__body");
  body.append(mk("b", null, "刷新岗位"), mk("p", null, "采集完成后点这里。"));
  refresh.append(icon(ICON_REFRESH), body, mk("span", "jobs-guide__chev", "›"));
  refresh.addEventListener("click", loadJobs);
  group.append(refresh);

  box.append(
    head,
    group,
    mk("p", "jobs-guide__note", "登录只在独立 Chrome 里进行，不要在 Argus 输入 BOSS 密码。手机端看不到这一步，需要电脑。"),
  );
  return box;
};

export const loadJobs = async () => {
  try {
    const { updated_at, jobs } = await readJson(await api("/api/jobs"));
    const list = Array.isArray(jobs) ? jobs : [];
    meta.textContent = updated_at ? `${list.length} 个活跃岗位 · 更新于 ${updated_at}` : "";
    if (!list.length) {
      const me = await api("/api/me").then(readJson).catch(() => ({}));
      const user = me?.me?.user || "你的用户名";
      grid.replaceChildren(guide(user));
      return;
    }
    grid.replaceChildren(...list.map(jobCard));
  } catch (e) {
    meta.textContent = "";
    grid.replaceChildren(errNote(e, "取岗位"));
  }
};
