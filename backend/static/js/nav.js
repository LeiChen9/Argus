const views = [...document.querySelectorAll(".view")];
const tabs = [...document.querySelectorAll(".tab")];
const topbar = document.getElementById("topbar");
const tabbar = document.getElementById("tabbar");

// 详情页不在 tabbar 里，返回时要回到它进来之前的那一页。
let last = "home";

export const go = (name) => {
  for (const view of views) {
    const on = view.id === `view-${name}`;
    view.hidden = !on;
    view.classList.toggle("is-active", on);
  }
  for (const tab of tabs) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === name));
  }
  if (name !== "job") last = name;
  // 详情页和 Chat 一样是"沉浸式"：tabbar 让位，否则在详情页点 Jobs tab 会撞上
  // app.js 里"已选中就 return"的短路，卡在原地回不去。
  const bare = name === "chat" || name === "job";
  topbar.hidden = bare;
  tabbar.hidden = bare;
};

export const back = () => go(last);