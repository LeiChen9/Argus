// me.js —— Me 页：登录 / 注册 / 账号信息 / token 用量。
//
// 数据隔离的可见面就这一页：登录前谁都进不来（Worker 那边 401），登录后看到
// 「我是谁」和「我烧了多少 token」。用量是 Worker 每轮对话结束时累加进
// <用户>/usage.json 的，前端只读不算。

import { api, apiJson, setAccessCode } from "./api.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};

const root = () => document.getElementById("me-body");

const fmt = (n) => {
  n = Number(n) || 0;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
};

function renderLogin(message) {
  const box = root();
  box.replaceChildren();

  // 「访问码不对」单独一套表单。**不能复用下面那个**：那个 form 里有个空的、
  // 标着 required 的用户名输入框，点提交时浏览器的表单校验会先拦下它，
  // submit 事件根本不触发——用户看到的就是「点了没反应」。
  if (message && message !== "没登录") {
    const cform = el("form", "meform");
    const code = el("input", "meform__input");
    code.type = "password"; code.placeholder = "访问码";
    code.autocomplete = "off"; code.required = true;
    const cbtn = el("button", "meform__btn", "用这个访问码再试一次");
    cbtn.type = "submit";
    cform.append(code, cbtn, el("p", "meform__note", `${message}。填一次存在这台设备上，以后不用再填`));
    cform.addEventListener("submit", (e) => {
      e.preventDefault();
      setAccessCode(code.value.trim());
      loadMe();
    });
    box.append(cform);
    code.focus();
    return;
  }

  const form = el("form", "meform");
  const user = el("input", "meform__input");
  user.name = "username"; user.placeholder = "用户名"; user.autocomplete = "username";
  user.required = true; user.maxLength = 24;
  const pass = el("input", "meform__input");
  pass.name = "password"; pass.type = "password"; pass.placeholder = "密码";
  pass.autocomplete = "current-password"; pass.required = true;

  const note = el("p", "meform__note", message || "");
  const swap = el("button", "meform__alt", "没有账号？注册");
  swap.type = "button";
  form.append(user, pass);

  const submit = el("button", "meform__btn", "登录");
  submit.type = "submit";
  form.append(submit, note);

  const send = async (path, body) => {
    note.textContent = "…";
    try {
      await api(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      note.textContent = "";
      await loadMe();
    } catch (e) {
      const detail = e.detail || e.message || "登录失败";
      // 访问码不对时重画一次登录框，把访问码输入框补上——用户刚填的
      // 用户名密码会保留不了，但至少给他一条能走通的路。
      if (detail === "access code 不对") { renderLogin(detail); return; }
      note.textContent = detail;
    }
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    send("/api/auth/login", { username: user.value.trim(), password: pass.value });
  });

  let registering = false;
  swap.addEventListener("click", () => {
    registering = !registering;
    submit.textContent = registering ? "注册并登录" : "登录";
    swap.textContent = registering ? "已有账号？登录" : "没有账号？注册";
    note.textContent = registering ? "注册后会带你那一份职位库，简历和个人资料要自己上传" : "";
  });

  box.append(form, swap);
  user.focus();
}

function renderProfile(data) {
  const box = root();
  box.replaceChildren();

  const card = el("div", "mecard");
  card.append(el("div", "mecard__name", data.me.user));
  card.append(el("div", "mecard__sub", "数据都存在你自己的命名空间里，别人看不到"));
  box.append(card);

  const rows = Object.entries(data.usage || {}).sort((a, b) => (b[1].input + b[1].output) - (a[1].input + a[1].output));
  const section = el("div", "meusage");
  section.append(el("div", "meusage__title", "token 用量"));
  if (!rows.length) {
    section.append(el("p", "meusage__empty", "还没有记账，聊一轮就有了"));
  } else {
    for (const [model, u] of rows) {
      const row = el("div", "meusage__row");
      row.append(el("span", "meusage__model", model));
      const nums = el("span", "meusage__nums");
      nums.append(el("span", null, `输入 ${fmt(u.input)}`));
      nums.append(el("span", null, `输出 ${fmt(u.output)}`));
      nums.append(el("span", null, `${u.calls} 次`));
      row.append(nums);
      section.append(row);
    }
    section.append(el("p", "meusage__note",
      "输入是估算值（provider 没回 usage 就按 token 数算），输出按正文字数折。够看个大概。"));
  }
  box.append(section);

  const out = el("button", "meform__alt", "退出登录");
  out.addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    renderLogin("已退出");
    onAuth(false);
  });
  box.append(out);

  box.append(selfCheck());
}

// 自检：把三个页面的接口逐个打一遍，把状态和条数写在屏幕上。
//
// 为什么要有它：页面取数失败过一次是「静默空白」——jobs.js 没有 catch，resume/
// career 显示一句「后端可能没重启」，而真实原因可能是访问码过期、cookie 掉了、
// 或者真的 500，三种病三种药。没有这一屏就只能在浏览器控制台里猜。
// 返回的是节点本身，**不是 async**：写成 async 的话 box.append(selfCheck())
// 塞进去的是个 Promise，页面显示 [object Promise]，自检一条都出不来。
function selfCheck() {
  const wrap = el("div", "meusage");
  wrap.append(el("div", "meusage__title", "数据自检"));
  const targets = [["/api/careers", "careers"], ["/api/jobs", "jobs"], ["/api/resumes", "resumes"]];
  for (const [path, name] of targets) {
    const nums = el("span", "meusage__nums", "…");
    const line = el("div", "meusage__row");
    line.append(el("span", "meusage__model", name), nums);
    wrap.append(line);
    api(path).then(async (res) => {
      const body = await res.text();
      let detail;
      try {
        const doc = JSON.parse(body);
        const count = doc.careers?.length ?? doc.resumes?.length ?? (doc.jobs?.length ?? "-");
        detail = res.ok ? `${count} 条` : `HTTP ${res.status}`;
      } catch { detail = `HTTP ${res.status}`; }
      nums.textContent = `${detail}（${res.status}）`;
    }).catch((e) => {
      nums.textContent = `失败：${e.detail || e.message}`;
    });
  }
  return wrap;
}

// 登录状态变了就通知外面（app.js 拿它开关 tabbar）——登录成功后 tabbar 要回来。
let onAuth = () => {};
export const onAuthChange = (fn) => { onAuth = fn; };

export async function loadMe() {
  try {
    const data = await apiJson("/api/me");
    renderProfile(data);
    onAuth(true);
  } catch (e) {
    // **不要按 status 一刀切吞掉 detail**：两种 401 的含义完全不同——「没登录」
    // 是正常状态（空账户，静默出登录框），而「access code 不对」必须原样显示，
    // 否则登录框里不会出现访问码输入框，用户填完用户名密码提交必然又被挡在
    // 访问码这一关，只能看见一句没头没尾的「access code 不对」。
    const detail = e.detail || e.message || "";
    renderLogin(detail === "没登录" ? "" : detail);
    onAuth(false);
  }
  return root();
}

// 未登录时把用户送到 Me 页（app.js 的 tabbar 闸门用）
export async function ensureLogin() {
  try {
    return await apiJson("/api/me");
  } catch {
    return null;
  }
}
