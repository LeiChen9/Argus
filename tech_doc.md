# Argus — Tech Doc

已达成共识的技术选型。**只记已确定的选择和决策理由**，不记实现细节、不记待办。
进度与踩坑记录写 `dev_log.md`。

Last updated: 2026-10-03

---

## Environment

| 项 | 值 | 备注 |
|---|---|---|
| Conda env | **`echo`** | 所有 Python 命令前加 `source activate echo` |
| Python | 3.10.20 | echo env 自带版本 |
| 机器 | macOS (darwin) | zsh |
| 已装关键包 | fastapi 0.115.6 / uvicorn 0.30.0 / pydantic 2.7 / httpx 0.28 | 切片 1 阶段**不建 requirements.txt**，够用即可 |

## Stack

| 层 | 选型 | 决策理由 |
|---|---|---|
| Backend | **Python + FastAPI** | 用户指定 Python（熟悉）。FastAPI 自动出 `/docs`，Pydantic 类型化便于后续接 LLM 流式响应。 |
| Frontend | **静态 HTML + 原生 JS** | 无构建步骤、无 node 工具链进应用路径。改完刷新即见，Phase 1 迭代最快。 |
| Storage | **SQLite，走 stdlib `sqlite3`，不上ORM** | 单用户单进程，慢的是 LLM 不是 DB。零新依赖。`.gitignore` 已忽略 `db.sqlite3`。 |
| LLM Provider | 智谱 `zhipu_realtime`，key 在 `.env` | `.env` 已被 gitignore；`.env` 不入库。 |

### Storage 已知债务

裸 `sqlite3` 意味着**方言绑定**。将来若换 Postgres，以下都要重写：
`AUTOINCREMENT`、`?` 占位符、类型声明、以及每一个拼接出来的查询字符串。

这是**明确接受的债务**，不是疏漏。换库的前提条件是：先引入 ORM 做一次集中迁移。
在债务兑现前，不要写 ORM 也不要提前抽象 DAL —— 按需引入。

## Layout

```
backend/
  main.py                      FastAPI app
  static/
    index.html                 由 FastAPI StaticFiles 直接 serve
    css/app.css                设计系统，移植自 FluentChat
    js/app.js                  tab 切换 + 招呼语注入
    js/greeting.js             时段×星期招呼语
    assets/argus-anime.jpeg    NPC 源图（用户设计）
    assets/argus-anime.webp    带 alpha，页面实际使用
tech_doc.md         本文件
dev_log.md          开发日志
```

## Frontend

**设计系统移植自 `../FluentChat/site/`**，不重复造轮子。`css/app.css` 268 行里
除注释外与上游逐字节相同。回上游取改动：`diff` 一下就知道我们改过哪。

底部三个 tab 是产品结构，不是实现细节：

| Tab | 职责 | 状态 |
|---|---|---|
| **Chat** | 更新 Persona 的地方 | 首页，NPC + 招呼语已做；对话气泡/persona 面板未做 |
| **Jobs** | 爬虫找到的求职意向下的活跃岗位聚类 | placeholder，爬虫未接 |
| **Me** | 个人资料与设置 | placeholder |

### NPC 资产：JPEG 必须转带 alpha 的 webp

源图 `argus-anime.jpeg` 是 **RGB，无 alpha 通道，白底烘死在像素里**。
页面暗色模式底色是 `#000000`，直接用会是一块发光白板。

所以用**连通域泛洪**抠底：判白条件 `min(RGB) >= 246`，只保留**触边**的白色连通域。
关键点：只抠触边区域，角色身上的白斑/高光不触边，不会被抠穿成洞。
产出 `argus-anime.webp`（RGBA，45% 透明）。FluentChat 的 `npc-cat.webp` 同样是这个套路。

**不要再用 PIL 的 `ImageDraw.floodfill`** —— 实测 thresh=8 下它会把中心像素
`(250,237,221)` 也填掉（蓝通道差 34 本该拦住），整图被吞光。语义不可靠，用连通域。

## Run

```bash
source activate echo
uvicorn main:app --app-dir backend --port 8010
```

访问 `http://localhost:8010`（页面）/ `http://localhost:8010/docs`（API 文档）。

**端口 8010**：机器上 8000 被一个遗留的 `python -m http.server 8000` 占用
（它 listen 在 IPv6 `*:8000`，会劫持 `localhost` 的 IPv6 解析）。不要用 8000。

## 约定

- `StaticFiles` mount 在 `/` **必须放在所有 API 路由声明之后**，否则会遮蔽它们。
- 前端所有 API 调用走相对路径 `/api/...`，由同一个 FastAPI 进程 serve，无需 CORS、无需 dev server 代理。

## 尚未决定（不要自行假设）

- Persona 的存储 schema 与 Evidence 链怎么建模
- 接哪个 LLM 做 Persona 抽取 / Gap Analysis，以及是否流式
- 前端在 Phase 1 之后是否升级为 React + Vite（引入构建链）
- 前端形态（对话流 / Persona 面板 / Gap 列表）如何对应 README 的 MVP 五个模块