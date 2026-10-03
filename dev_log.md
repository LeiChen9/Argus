# Argus — Dev Log

倒序追加。一次 session 一个条目。技术选型不要写这里，去 `tech_doc.md`。

---

## 2026-10-03 — Session 1: 前后端链路打通

**做了什么**

读 README 确认目标（Argus = AI-native career copilot，MVP Phase 1 = Persona / Job
Intelligence / Gap Analysis / Career Plan / Interview Prep）。用户选择「先只验证链路」，
所以本 session 不碰 Persona 逻辑。

- `backend/main.py` — FastAPI app + `POST /api/echo` + mount `static` 到 `/`
- `backend/static/index.html` — input + button + fetch，够点通即可
- `tech_doc.md` / `dev_log.md` — 建立

**验证结果**

```
POST localhost:8010/api/echo  {"message":"ping"} -> {"echo":"ping"}
GET  localhost:8010/          -> HTTP 200
GET  localhost:8010/docs      -> HTTP 200
```

**踩的坑**

1. **`localhost:8000` 被别人的进程劫持。** 首次 curl 拿到 `501 Unsupported method`，
   来自一个遗留的 `python -m http.server 8000`（PID 76215，listen 在 IPv6 `*:8000`）。
   它抢在 uvicorn（只 listen `127.0.0.1`）前面被解析到。改用 **8010** 解决。
   该进程不是本次 session 起的，**未 kill**，留给用户决定。
2. `StaticFiles` mount `/` 必须写在 API 路由之后，否则遮蔽 `/api/*`。

**下个 session 从哪继续**

前后端链路与交互形状已完成（见下方补记 2）。**建表仍推迟：schema 未定，不在数据形状
定下来前建表。** `.env` 的智谱 key 目前完全未被使用——下一步应先定 Persona 数据形状，
再决定先接 LLM 抽取还是先建表。

---

## 2026-10-03 — Session 1 补记：类重命名 + Storage 决策

**`Echo` → `EchoRequest`**（`backend/main.py:10,15`）。`Echo` 与 conda env `echo`
撞名会误导。路由 `/api/echo`、函数名 `echo`、响应键 `echo` 保持不变——纯重命名，
零行为变化，`/docs` schema 名已确认变成 `EchoRequest`。

**Storage 决策：裸 stdlib `sqlite3`，不上 ORM。** 用户选定。理由见 `tech_doc.md`。

**流程教训：我给SQLite 的理由太薄，且漏写了它的隐藏条款。**
当时只写"Postgres 要起服务"，没说清真正含义是"这决定了要不要上 ORM"。
用户追问「为啥要 SQLite」才暴露出：换库成本完全取决于第0 天怎么写 SQL。
**教训：给技术选型写理由时，必须连带写出它的代价和触发条件，
否则用户批准的是一个自己没看清的选项。** 已补进 `tech_doc.md` 的「Storage 已知债务」。

---

## 2026-10-03 — Session 1 补记 2：换成真实 Argus 交互形状（Slice 3）

**做了什么**

建表被用户砍掉——「现在还没定要存什么样的数据」。改为把 echo 占位换成真实交互形状，
**零存储、零 LLM 调用**：

- `POST /api/chat`（`backend/main.py:24`）— canned 回声，`ChatRequest` 校验 422 仍在
- `GET /api/persona`（`backend/main.py:31`）— 返回 `PERSONA_MOCK`
- `backend/static/index.html` — 左侧聊天气泡流 + 右侧 persona 面板
- `POST /api/echo` 已移除（现在返回 405）

**验证**
```
POST /api/chat {"message":"我在字节做过三年数据分析师"} -> {"reply":"收到：..."}
POST /api/chat {}   -> 422 missing
GET  /api/persona   -> 11 fields
GET  /             -> 200        POST /api/echo -> 405
```

**`PERSONA_MOCK` 的 11 个字段是 UI mock，不是 schema 决定。**
抄自 README 的 Persona 分类（experience/skills/knowledge/projects/domain_expertise/
communication/career_preferences/strengths/weaknesses/evidence/goals），全部空值。
页面上标了「schema 未定稿」。**要改就改 `backend/main.py:9` 一个 dict。
别在没讨论过的情况下照它建表。**

**做过头的地方**：我在提议里说"不碰 schema"，但写下 11 个字段本身已经是在预设立场。
用户批准的是 UI mock，所以我把它标成未定稿来对冲——但这是我自己造成的张力，记下来。

**依赖现状**：没有 `requirements.txt`（用户决定先不做）。依赖全靠 `echo` env裸奔，
换机器/重建 env 会断。