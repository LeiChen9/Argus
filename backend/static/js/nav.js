const views = [...document.querySelectorAll(".view")];
const chatClear = document.getElementById("chat-clear");

// 详情页不在导航里，返回时要回到它进来之前的那一页。
let last = "home";

export const go = (name) => {
  for (const view of views) {
    const on = view.id === `view-${name}`;
    view.hidden = !on;
    view.classList.toggle("is-active", on);
  }
  if (name !== "job" && name !== "resumedit") last = name;
  // 顶栏常驻。左边的头像点它回首页；右边那颗「清空对话」只有 chat 用得上，
  // 别的页面就收起来（顶栏高度不变，视觉上不会跳）。
  if (chatClear) chatClear.hidden = name !== "chat";
};

export const back = () => go(last);