const views = [...document.querySelectorAll(".view")];
const tabs = [...document.querySelectorAll(".tab")];
const topbar = document.getElementById("topbar");
const tabbar = document.getElementById("tabbar");

export const go = (name) => {
  for (const view of views) {
    const on = view.id === `view-${name}`;
    view.hidden = !on;
    view.classList.toggle("is-active", on);
  }
  for (const tab of tabs) {
    tab.setAttribute("aria-selected", String(tab.dataset.view === name));
  }
  const inChat = name === "chat";
  topbar.hidden = inChat;
  tabbar.hidden = inChat;
};