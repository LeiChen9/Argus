import { greeting } from "./greeting.js";
import { go, route, routeId, onRouteChange } from "./nav.js";
import { loadJobs } from "./jobs.js?v=20261126j";
import { loadCareer } from "./career.js";
import { initJobDetail, openJob } from "./job.js";
import { loadResume, initResumeDetail, openResume } from "./resumepage.js";
import { loadMe, onAuthChange } from "./me.js?v=20261126g";
import { whenUnauthorized } from "./api.js";
import { initChat } from "./chat.js";
import { maybeShowIntro } from "./intro.js?v=20261126g";

initJobDetail();
initResumeDetail();

const el = document.getElementById("greeting");

const span = (className, text) => {
  const node = document.createElement("span");
  node.className = className;
  node.textContent = text;
  return node;
};

const { lead, hook } = greeting();
el.replaceChildren(span("greet__lead", lead), span("greet__hook", hook));

// 受保护页面遇到 401 就送回 Me 页重新登录；首页和 Me 自身不跳，避免冷启动时把游客弹去注册。
whenUnauthorized(() => {
  if (route() === "home" || route() === "me") return;
  go("me");
  loadMe();
});

// 未登录时也先让游客看首页，点受保护入口时再去 Me 页登录。
let loggedIn = false;
onAuthChange((on) => {
  loggedIn = on;
  if (on) initChat();
  else if (route() !== "home") go("me");
});

// 导航：底部固定 tabbar，入口在页面最下方。
const enter = (view) => {
  if (!loggedIn && view !== "home" && view !== "me") {
    if (view === "chat") sessionStorage.setItem("argus_after_login", "chat");
    go("me");
    return;
  }
  go(view);
  if (view === "resume") loadResume();
  if (view === "jobs") loadJobs();
  if (view === "career") loadCareer();
  if (view === "me") loadMe();
  // 详情页：路径里的 id 决定渲染谁。
  if (view === "job") openJob(routeId());
  if (view === "resumedit") openResume(routeId());
};

// 浏览器前进/后退换了路径：按路径切页（用户手改地址栏也走这里）。
onRouteChange(enter);

for (const item of document.querySelectorAll(".tab")) {
  item.addEventListener("click", () => enter(item.dataset.view));
}

// 顶部固定 logo：任何页面点它都回首页。
document.getElementById("toplogo").addEventListener("click", () => go("home"));

// 进站先认一下身份：按地址栏路径落到对应页面（拿来就能直达 /chat、/jobs…），
// 没登录的受保护页面会被 enter 的闸门送去 Me 页。
const boot = loadMe().then(() => {
  enter(route() || "home");
});

maybeShowIntro(async () => {
  await boot;
  if (loggedIn) enter("chat");
  else {
    sessionStorage.setItem("argus_after_login", "chat");
    enter("chat");
  }
});