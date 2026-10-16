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

// 会话失效（cookie 没了、别人登了同一个账号）就把人送回 Me 页重新登录：
// 其余页面留着只会各自弹一个报错，没人知道该干嘛。
whenUnauthorized(() => { go("me"); loadMe(); });

// 未登录时不许进别的页面：它们每个都会各自弹一句「没登录」，不如直接把人
// 送到 Me 页。登录后这个限制自然解除（登录本来就是在那儿完成的）。
let loggedIn = false;
onAuthChange((on) => {
  loggedIn = on;
  if (!on) go("me");
});

// 导航：底部 tabbar 去掉了，入口集中在首页那一排。
const enter = (view) => {
  if (view !== "me" && !loggedIn) { go("me"); return; }
  go(view);
  if (view === "resume") loadResume();
  if (view === "jobs") loadJobs();
  if (view === "career") loadCareer();
  if (view === "me") loadMe();
};

for (const item of document.querySelectorAll(".homenav__item")) {
  item.addEventListener("click", () => enter(item.dataset.view));
}

// 顶部固定 logo：任何页面点它都回首页。
document.getElementById("toplogo").addEventListener("click", () => go("home"));

// 进站先认一下身份：没登录就落在 Me 页；**已经登录的别把人扣在 Me 页**——
// 底部栏去掉了，从那儿再点一次 logo 才能回首页，等于登录完先迷路一下。
loadMe().then((box) => {
  go(box.querySelector(".meform") ? "me" : "home");
});