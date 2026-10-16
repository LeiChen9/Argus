import { greeting } from "./greeting.js";
import { go } from "./nav.js";
import { loadJobs } from "./jobs.js";
import { loadCareer } from "./career.js";
import { initJobDetail } from "./job.js";
import { loadResume, initResumeDetail } from "./resumepage.js";
import { loadMe, onAuthChange } from "./me.js";
import { whenUnauthorized } from "./api.js";
import "./chat.js";

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

document.getElementById("wordmark").addEventListener("click", () => go("home"));

// 会话失效（cookie 没了、别人登了同一个账号）就把人送回 Me 页重新登录：
// 其余页面留着只会各自弹一个报错，没人知道该干嘛。
whenUnauthorized(() => { go("me"); loadMe(); });

// 登录闸门：没登录时只留 Me 页（登录/注册），登录后把 tabbar 和其它 tab 放回来。
// 每个请求返回的也是数据，一屏全灰比一个登录框更让人困惑。
const bar = document.getElementById("tabbar");
const applyGate = (loggedIn) => {
  for (const tab of document.querySelectorAll(".tab")) tab.hidden = !loggedIn && tab.dataset.view !== "me";
  bar.hidden = !loggedIn;
};
onAuthChange(applyGate);

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    if (tab.getAttribute("aria-selected") === "true") return;
    go(tab.dataset.view);
    if (tab.dataset.view === "resume") loadResume();
    if (tab.dataset.view === "jobs") loadJobs();
    if (tab.dataset.view === "career") loadCareer();
    if (tab.dataset.view === "me") loadMe();
  });
}

// 进站先认一下身份：没登录就把人落在 Me 页。
// 顺序有讲究：先 go("me")（它会把 tabbar 放回来），再 applyGate(false) 压回去——
// 反过来的话 tabbar 会留在屏幕上。
loadMe().then((box) => {
  if (box.querySelector(".meform")) {
    go("me");
    applyGate(false);
  }
});