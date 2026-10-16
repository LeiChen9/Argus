const views = [...document.querySelectorAll(".view")];
const topLogo = document.getElementById("toplogo");

// 详情页不在导航里，返回时要回到它进来之前的那一页。
let last = "home";

export const go = (name) => {
  for (const view of views) {
    const on = view.id === `view-${name}`;
    view.hidden = !on;
    view.classList.toggle("is-active", on);
  }
  if (name !== "job" && name !== "resumedit") last = name;
  // 顶部 logo 就是回首页的入口（fixed，压在所有页面之上）。已经在首页时不必
  // 显示——点它什么都不会发生，纯占地方。
  if (topLogo) topLogo.hidden = name === "home";
};

export const back = () => go(last);