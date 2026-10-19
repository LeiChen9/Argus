const views = [...document.querySelectorAll(".view")];
const app = document.querySelector(".app");
// 顶栏右侧两颗 chat 专用按钮（会话菜单、新建会话），别的页面收起来。
const chatActs = ["chat-menu", "chat-new"].map((id) => document.getElementById(id));

// 顶层页面各有自己的路径，浏览器返回/刷新/直达才走得通；详情页也走真路径，
// 只是带 id：/job/<id>、/resume/<id>，分别落在 job / resumedit 两个视图。
const PATH = { home: "/", chat: "/chat", resume: "/resume", jobs: "/jobs", career: "/career", me: "/me" };
const VIEW = Object.fromEntries(Object.entries(PATH).map(([v, p]) => [p, v]));
const DETAIL = /^\/(job|resume)\/(.+)$/;
const DETAIL_VIEW = { job: "job", resume: "resumedit" };
const detail = () => DETAIL.exec(location.pathname);

// 当前 URL 对应的视图；认不出来（陌生路径）给空串。
export const route = () => VIEW[location.pathname] || DETAIL_VIEW[detail()?.[1]] || "";

// 详情路径里的 id；不是详情路径给空串。
export const routeId = () => {
  const m = detail();
  return m ? decodeURIComponent(m[2]) : "";
};

// 浏览器前进/后退换了路径时通知外面切页（app.js 的 enter）。
let onRoute = () => {};
export const onRouteChange = (fn) => { onRoute = fn; };

// 离开某个视图时让它收尾（详情页清状态、简历详情把没提交的改动发出去）。
// 只要经过 go 的切换（点卡片、点 logo、前进后退）都会走到，不依赖 hash 事件。
const leaveHooks = {};
export const onLeave = (name, fn) => { leaveHooks[name] = fn; };

// 详情页不在导航里，返回时要回到它进来之前的那一页。
let last = "home";
let cur = "";

export const go = (name, path) => {
  if (cur !== name) leaveHooks[cur]?.();
  for (const view of views) {
    const on = view.id === `view-${name}`;
    view.hidden = !on;
    view.classList.toggle("is-active", on);
  }
  cur = name;
  if (name !== "job" && name !== "resumedit") last = name;
  // 顶栏常驻。左边的头像点它回首页；右侧会话按钮只有 chat 用得上，
  // 别的页面就收起来（顶栏高度不变，视觉上不会跳）。侧栏也只属于 chat：
  // 手机默认收起（点菜单滑出），桌面默认展开（可折叠）。离开 chat 一律收起。
  for (const b of chatActs) if (b) b.hidden = name !== "chat";
  if (name === "chat" && matchMedia("(min-width: 768px)").matches) app?.classList.add("side-open");
  else app?.classList.remove("side-open");
  // 顶层页面走固定 PATH；详情页带 id，由调用方把完整路径传进来。
  const target = path ?? PATH[name];
  if (target && location.pathname !== target) history.pushState({ view: name }, "", target);
};

export const back = () => go(last);

addEventListener("popstate", () => {
  const name = route();
  if (name) onRoute(name);
});