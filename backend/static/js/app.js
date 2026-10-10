import { greeting } from "./greeting.js";
import { go } from "./nav.js";
import { loadJobs } from "./jobs.js";
import { loadCareer } from "./family.js";
import { initJobDetail } from "./job.js";
import "./chat.js";

initJobDetail();

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

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    if (tab.getAttribute("aria-selected") === "true") return;
    go(tab.dataset.view);
    if (tab.dataset.view === "jobs") loadJobs();
    if (tab.dataset.view === "career") loadCareer();
  });
}