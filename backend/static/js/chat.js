import { go } from "./nav.js";

const msgs = document.getElementById("msgs");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const file = document.getElementById("file");
const attach = document.getElementById("attach");
const chip = document.getElementById("chip");

const row = (who, text) => {
  const el = document.createElement("div");
  el.className = `msg msg--${who}`;
  if (who === "them") {
    const avatar = document.createElement("img");
    avatar.className = "avatar";
    avatar.src = "assets/argus-anime.webp";
    avatar.alt = "";
    el.appendChild(avatar);
  }
  const bubble = document.createElement("p");
  bubble.className = "bubble";
  bubble.textContent = text;
  el.appendChild(bubble);
  return el;
};

const show = (node) => {
  msgs.appendChild(node);
  msgs.scrollTop = msgs.scrollHeight;
};

document.getElementById("chat-back").addEventListener("click", () => go("home"));

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  show(row("me", message));
  input.value = "";
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  show(row("them", (await res.json()).reply));
});

attach.addEventListener("click", () => file.click());

file.addEventListener("change", () => {
  const picked = file.files[0];
  chip.textContent = picked ? `待解析：${picked.name}` : "";
  chip.hidden = !picked;
});