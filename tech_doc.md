# Argus — Tech Doc

已达成共识的技术选型。**只记已确定的选择和决策理由**，不记实现细节、不记待办。
进度与踩坑记录写 `dev_log.md`。

Last updated: 2026-10-09

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
| Storage | **JSON 文件，无 DB、无 ORM** | 单用户单进程，慢的是 LLM 不是存储。`data/boss_jobs.json`（岗位覆盖快照）+ `backend/persona.json`（简历解析结果），都在 `.gitignore` 里 |
| LLM Provider | 智谱 `zhipu_realtime`，key 在 `.env` | `.env` 已被 gitignore；`.env` 不入库。 |

### Storage 说明

早期 tech_doc 写的是 SQLite，那是**计划**不是现状：`backend/` 里没有任何 `sqlite3`
引用，`db.sqlite3` 的 gitignore 条目是那份计划留下的残留。

岗位数据物理含义是**覆盖快照**而非追加（`save_snapshot` 按 id 去重合并，新批次覆盖
旧值），写入时过滤掉 `jd` 为空的岗位。数据量级是几十条，`/api/jobs` 全量返回前端，
没有分页。真的到需要分页或并发写的那天再谈迁移，不要提前抽象 DAL。

## Layout

```
backend/
  main.py                      FastAPI app + no-store 中间件
  chat.py                      /api/chat Agent 循环、/api/persona*
  jobs.py                      /api/jobs、/api/jobs/{id}/analysis、normalize、save_snapshot
  crawler.py                   BOSS CDP 采集 + 猎聘回退
  persona.py                   简历解析与 Persona 落盘
  common.py                    .env 读取、LLM 容灾链、markdown 渲染
  me.py                        /api/me 占位
  static/
    index.html                 由 FastAPI StaticFiles 直接 serve
    css/app.css                设计系统，移植自 FluentChat；含岗位详情与 AI 解读段
    js/app.js                  tab 切换 + 招呼语注入 + 引入 chat.js + initJobDetail
    js/chat.js                 气泡渲染 / 调 /api/chat / 上传 chip
    js/jobs.js                 Jobs 页拉 /api/jobs
    js/cards.js                岗位卡片（Chat 横滑轨道与 Jobs 网格共用）
    js/job.js                  岗位详情：hash 路由 + 岗位本体渲染 + 拉解读
    js/analysis.js             AI 解读渲染：结论、要求拆解、面试打法、补齐行动
    js/dom.js                  el / deRadical / fold，job.js 与 analysis.js 共用
    js/nav.js                  视图切换 + 返回来源记忆
    js/greeting.js             时段×星期招呼语
    assets/argus-anime.jpeg    NPC 源图（用户设计）
    assets/argus-anime.webp    带 alpha，页面实际使用
worker-proxy/
  worker.js                    公网入口，读 KV 得上游地址
  wrangler.jsonc               KV binding
scripts/restart.sh             起本机 + 拉 tunnel + 写 KV + 校验
tech_doc.md         本文件
dev_log.md          开发日志
```

## Frontend

**设计系统移植自 `../FluentChat/site/`**，不重复造轮子。移植进来的那部分
（首页 + Chat + tabbar）与上游逐字节相同，回上游取改动时 `diff` 一下就知道我们改过哪。
往后追加的段落（岗位详情、AI 解读）是我们自己的，**不承诺与上游一致**。

底部三个 tab 是产品结构，不是实现细节：

| Tab | 职责 | 状态 |
|---|---|---|
| **Chat** | 更新 Persona 的地方 | 已做：WhatsApp 式气泡 + composer + 上传按钮 |
| **Jobs** | 爬虫找到的求职意向下的活跃岗位聚类 | 已做：拉 `/api/jobs` 渲染卡片网格，点开进站内详情页 |
| **Me** | 个人资料与设置 | placeholder |

### NPC 资产：JPEG 必须转带 alpha 的 webp

源图 `argus-anime.jpeg` 是 **RGB，无 alpha 通道，白底烘死在像素里**。
页面暗色模式底色是 `#000000`，直接用会是一块发光白板。

所以用**连通域泛洪**抠底：判白条件 `min(RGB) >= 246`，只保留**触边**的白色连通域。
关键点：只抠触边区域，角色身上的白斑/高光不触边，不会被抠穿成洞。
产出 `argus-anime.webp`（RGBA，45% 透明）。FluentChat 的 `npc-cat.webp` 同样是这个套路。

### Chat 视图

对话气泡层是**新写的**，FluentChat 里没有可抄（它是语音应用，`grep` bubble/msg/
composer/avatar 命中 0）。能复用的只有 token、`.view` 入场动画、`.tabbar`。

**首页与 Chat 是两个独立 view。** 顶部全局 `.topbar` 的 "Argus" 文字标识是
**回首页的唯一入口**，首页不在 tabbar 里（tabbar 仍是 Chat / Jobs / Me）。

Chat 页让位给对话：`.topbar` 换成 `.chat__head`（返回键 + 头像 + 名字），
`.tabbar` 隐藏、composer 顶替 —— WhatsApp / Line / 微信进具体会话都是这样。
切页逻辑集中在 `js/nav.js` 的 `go(name)`：同时处理 view 显隐、tab 选中态、
两条 bar 的显隐。`app.js` 与 `chat.js` 都从 `nav.js` import，不走循环依赖。

- Argus 气泡带小头像（`.avatar`，方形圆角，不做人脸裁切——见下）
- 头像不做人脸裁切的原因：NPC 源图 1024×1024，**脸的位置未知**（模型不支持读图）。
  用完整角色的圆角方图，零猜测风险。要裁脸需先确认脸的坐标。
- **不做人脸裁切，也不做圆形头像**
- 上传按钮只到"选中文件显示文件名 chip"，**没有后端端点**，不传文件
- Persona 更新逻辑**尚未设计**，`.env` 的智谱 key 仍未被任何代码使用

### 品牌色：暖色体系（奶油 + 摩卡棕）

用户选定「温暖一点」。原靛紫 `#5e5ce6` 全部废弃。

| token | 亮色 | 暗色 | 角色 |
|---|---|---|---|
| `--accent` | `#8b6f47` 摩卡 | `#d2b48c` 浅奶油 | tab 图标、返回箭头、chip 文字、send 底 |
| `--bubble-me` | `#f0e0c8` 奶油 | `#4a3b2e` 深棕 | 用户气泡底 |
| `--on-bubble` | `#3a2e22` 深墨 | `#f0e0c8` 奶油 | 压在气泡上的文字 |
| `--on-accent` | `#ffffff` | `#2a2118` | 压在 `--accent` 上的文字 |
| `--glow` | 暖 rgba | 暖 rgba | NPC 光晕、图标按钮底 |
| `--npc-shadow` | 投影 | 辉光 | 一个 token 切换两种模式，省掉一条覆盖规则 |

**三条不能省的规则：**

1. **`--accent` 必须分亮暗两档。** 亮底要深（4.55:1）、暗底要浅（10.65:1），
   方向相反。单一暖色无法两边都过 AA——实测奶油 `#F5E6D3` 压亮底只有 **1.19:1**。
2. **`--on-accent` 和 `--on-bubble` 是两回事，不能合并。** send 按钮是
   「accent 底 + 白字」，气泡是「奶油底 + 深墨字」，同一个 token 装不下。
3. **不要把奶油色用作图标/小字。** NPC 身体本身就是奶油（对比 1.03:1），
   奶油当图标会同时糊在底色和角色上。奶油只做底色。

全部对比度实测：亮底 accent 4.55、气泡 10.17；暗底 accent 10.65、气泡 8.28、
send 按钮 8.01。均过 WCAG AA（文本 4.5:1）。

**不要再用 PIL 的 `ImageDraw.floodfill`** —— 实测 thresh=8 下它会把中心像素
`(250,237,221)` 也填掉（蓝通道差 34 本该拦住），整图被吞光。语义不可靠，用连通域。

## Run

```bash
source activate echo
uvicorn main:app --app-dir backend --port 7800
```

访问 `http://localhost:7800`（页面）/ `http://localhost:7800/docs`（API 文档）。

**端口 7800。** 本机同时有别的程序在跑 localhost 测试，Argus 固定占 **7800**。
历史：曾是 8010；更早的 8000 被一个遗留的 `python -m http.server 8000` 占过
（它 listen 在 IPv6 `*:8000`，会劫持 `localhost` 的 IPv6 解析，表现为收到 501）。

端口只出现在本节，**代码里没有硬编码端口**。换端口只改这一行。

### 重启后拉什么

两样，都不随开机自启：

```sh
cd /Users/riceball/Documents/Projs/Argus

# 1. 后端（7800）。隧道指向它，不起就没东西可代理
source activate echo
uvicorn main:app --app-dir backend --port 7800 &

# 2. 公网入口。隧道 + 写 KV + 校验，一步到位
sh scripts/restart.sh

# 3. 看门狗（可选）。探公网，连续 2 次失败自动重跑第 2 步
nohup sh scripts/watchdog.sh >/tmp/watchdog.log 2>&1 &
```

`restart.sh` 自己也会起 7800（检测到没监听才起），所以第 1 步可以省。
日志：`/tmp/uvicorn_7800.log`、`/tmp/quick.log`（隧道）、`/tmp/watchdog.log`（看门狗，
空 = 健康）。

## 公网访问（Cloudflare Tunnel）

不做 Workers 迁移（FastAPI + 本地文件存储 + 本机浏览器探针跑不上 Workers），
用 Cloudflare Tunnel 把本机 7800 暴露出去。

**入口域名是固定的，不随重启变**：`https://argus-proxy.luent-hat.workers.dev`
（workers.dev 子域，账号自带，免费，不需要买域名）。变的只有它背后的上游地址。

- 链路：`固定 workers.dev 域名` → `argus-proxy Worker` →（读 KV 得地址）→ `cloudflared --url` 随机 `*.trycloudflare.com` → `localhost:7800`
- **上游地址存 KV（`ORIGIN_KV` 绑定），不写死在 `worker.js`。** 换上游 = 写一次 KV，
  **不需要 `wrangler deploy`**。这是本方案能免域名的原因
- 一键重绑：`./scripts/restart.sh` = 起 7800 + 拉新 quick URL + 探测可达 + 写 KV + 校验公网 30 条。任何一步失败都在写 KV 之前退出，线上代码不受影响
- `cloudflared --url` 拿不到地址时**必须整段放弃**。早期版本继续往下走，`sed` 把
  `ORIGIN` 洗成空串并部署上线，公网入口直接瘫，且报错发生在好几步之后
- 探测和校验走 `http://127.0.0.1:8118` 代理：直连 trycloudflare 在本地网络下常超时，
  用直连当判据会把好隧道误杀
- **改 KV 是自动的**，在 `restart.sh` 里，拿地址 → 验隧道 → 写 KV → 验公网一条龙。
  手动改只在脚本**中途失败**时才需要（它会在写 KV 前退出，此时线上仍指向旧上游）
- **`workers.dev` 在本地网络下 DNS 被污染**：直连解析到 `157.240.7.8`（Facebook 的段），
  `dig @1.1.1.1` / `@8.8.8.8` 给的也全是假地址。`cloudflare.com` / `trycloudflare.com`
  解析正常，只有 `workers.dev` 整个域被污染。所以**本机直连公网入口必然失败**，
  是网络环境问题不是代码问题，换网络（手机热点）即可。验证一律走 8118 代理

- **已知做不到（2026-10-09 实测）**：不买域名无法让 Worker 直连 named tunnel。
  `UUID.cfargotunnel.com` 返回 403/1102（该子域只代理同账户内的 DNS 记录），
  Workers VPC 绑定 tunnel 在本账户报 10002。免域名的稳定上游只有 KV 这条路
- `cloudflared` 用 homebrew 装；`cert.pem` 缺失时 `tunnel list` 会报错，
  需要重新 `tunnel login`（FluentChat 走 wrangler，不共用这份授权）

### 隧道注册失败（2026-10-10 实测）

公网入口 530 = Worker 活着但取不到上游，往下查是隧道本身没建立。两种错要分清：

| 现象 | 含义 |
| --- | --- |
| `Unauthorized: Tunnel not found`（循环重试） | 拿到 URL 了但**注册没成功**，隧道不存在 |
| `failed to request quick Tunnel: context deadline exceeded` | 连 quick tunnel 都没申请到 |

第二种是**间歇性**的，不是配置问题：手工发同样的
`POST https://api.trycloudflare.com/tunnel` 每次都成功、耗时 4–5 秒，
延迟偏高，`cloudflared` 的等待窗口偶尔就错过。**重试即可，通常第 2 次就通。**
实测一轮 `restart.sh` 三次全超时、手动重试第 1 次就成了——这个随机性只能靠重试缓解，
根治要换 named tunnel，而免域名方案下那条路走不通（见上）。

注意「Tunnel not found」会伪装成好地址：`grep -oE` 照样能抓到
`https://xxx.trycloudflare.com`，**地址存在 ≠ 隧道存在**，得用
`curl -x http://127.0.0.1:8118 "$URL/api/jobs"` 实际探到数据才算数。
`restart.sh` 的重试循环因此把「拿地址」和「探测」合成一轮，三轮都探不通才放弃。

`restart.sh` 里另有一个 `set -e` 的坑：没有进程可杀时 `pkill` 返回 1，
`set -e` 会直接干掉整个脚本——第二轮开始常常就是这样（上一轮的 cloudflared
已经自己退出了）。必须 `pkill ... || true`。

### 看门狗（2026-10-10）

`scripts/watchdog.sh`，探端点、连续 2 次失败就调 `restart.sh` 换隧道。
5 分钟一探。

**不检测 DNS。** 这批实测故障里 DNS 全程正常（`api.trycloudflare.com` 正常解析到
Cloudflare 段），坏的是 `cloudflared` 注册超时和隧道进程自己退出。按 DNS 判会漏掉这两种。
真正被污染的只有 `workers.dev`，那影响本机直连，跟隧道存活是两回事。

**两个端点都要 200**：quick URL 活 = 隧道在；公网入口活 = Worker + KV 链路通。
只探一个会漏——隧道活着但 KV 写坏，公网入口照样 530。

同一个 `grep` 坑在这里是致命的另一种形态：cloudflared 申请失败时打的
`Post "https://api.trycloudflare.com/tunnel"` 会被 `grep -oE` 捞成隧道地址，
探它必然成功，**看门狗就永远健康、永远不触发**。必须排除 `^https://api\.`。

连续 2 次才动手：单次失败多半是抖动，而重启必然掉线，误触发的代价是真断线。
恢复不是瞬时的——KV 最终一致，实测从触发到公网入口 200 要 40 秒左右，中间是 530。

```sh
nohup sh scripts/watchdog.sh >/tmp/watchdog.log 2>&1 &   # 起
pkill -f "scripts/watchdog.sh"                            # 停
```

停的时候**必须带 `scripts/` 限定**：`pkill -f watchdog` 会连系统的
`/usr/libexec/watchdogd` 一起杀掉。

重启电脑后不会自启，详见 `## Run` 的「重启后拉什么」。

## 岗位详情（2026-10-09）

卡片点开进站内详情页，投递才是唯一离开本站的动作。

- **卡片仍是 `<a>`，`href` 是站内 hash `#job/<id>`**，不是外链。所以 `.jobcard` 样式
  一行没动，长按/右键行为照旧
- **岗位本体不需要新后端接口**：`jd` 全文一直存在 `data/boss_jobs.json` 里，`/api/jobs`
  本来就全量返回。`cards.js` 渲染时顺手 `remember(job)` 存进内存，深链接直接命中，
  未命中的才回落到 `/api/jobs`。（AI 解读是另一份数据，另走一个接口，见下节）
- `job` 视图必须和 Chat 一样归入「沉浸式」（隐藏 tabbar）：否则在详情页点 Jobs tab
  会撞上 `app.js` 里「已选中就 return」的短路，卡在原地回不去
- 后退优先交给 `history.back()`（iPhone 侧滑返回才对得上），直接粘链接进来的场景
  `history.state` 为 null，降级为记住来源视图的 `nav.back()`
- **JD 有康熙部首乱码**（`建⽴⽬标`），是抓取器字体解码的产物。只对命中的码位段做
  NFKC，**不能整串 NFKC** —— 那会把全角逗号也压成半角
- `normalize()` 原本丢弃了 `company_scale / company_stage / company_industry /
  welfare / boss_title / job_labels / skills` —— 抓取器一直在返回（`map_api_job`），
  只是没存。补上后需**重跑一次采集**才有数据，详情页对缺失字段整行跳过

### AI 解读（2026-10-09）

`scripts/cluster_jobs.py` 跑出的 `data/job_gaps.json`（438KB / 30 岗位 ≈ 15KB 每岗）
接进详情页，位置在 **JD 原文之后**。

**默认形态：JD 展开，解读折叠。** JD 是投递的原始依据，解读是模型的推论——
折叠起来让用户自己决定什么时候看，而不是被推着先读一段 AI 的话。折叠头只给
结论徽标（「长期储备」这类），点开才是完整解读。

**数据通道：单岗位接口，不并入 `/api/jobs`。**
`GET /api/jobs/{job_id}/analysis` → `{job_id, generated_at, model, analysis, target}`。

- 全量 `/api/gaps` 不划算：438KB 一次性下发，且岗位刷新后解读不跟着更新。
  单岗位约 15KB，懒加载，详情页 `render()` 后异步补进来
- **必须带上 `target`**（`target_base` / `target_salary`）。`intent_match` 只给
  `aligned` / `above_target` 这类状态，**没说是跟什么对齐**——不下发目标值就只能显示
  「已对齐」这种没主语的词。前端拼成「地点符合你的意向 上海」这种整句
- **`analysis` 原样透传，不在后端归一化**

**LLM 输出的键不齐，前端一律 `??` 兜底。**

| 现象 | 实测 | 处理 |
|---|---|---|
| `openning` 写成 `opening` | 1/30 岗位 | `a.openning ?? a.opening` |
| `defensive_script` 有四种键变体 | 76 条**全都**带 `mitigation_angle`，其余是重复而非替代 | 只读 `mitigation_angle` |
| `gap_details` 只有 `has_gap` | 43/293 条要求 | 缺口文案与难度都按可选渲染 |
| 引用 JD 原文带康熙部首 | 23 处 | `deRadical` 也要过解读文本，不只 JD |

**不要把这些归一化搬到后端。** 后端归一化等于把这一批的脏数据固化成 API 契约，
重跑 cluster 后还得再改一次；放前端读时兜底，重跑即自愈。

**分层：core 展开，非 core 折叠。**

- 概览卡片统计**全部**要求（分母诚实），但只列 `core` 行的明细。
  `important` / `bonus` 不影响「投不投」的判断，收进一个 `<details>`
- 每种匹配状态一张卡，带一句「凭什么」：`已证明 / 有直接对应的经历`。
  光有「已证明」三个字看不出是拿什么证明的。原来的 6px 细条 + 小字图例在手机上
  很难受，四种颜色得盯着 6px 去分辨
- **补齐行动按 `bridge_difficulty` 降序排**（难补的排前面）。行动条目通过
  `target_gap_tag` 反查要求里的难度，两边靠这个 tag 关联
- 折叠一律用原生 `<details>`：键盘与读屏行为免费，不需要自己写 accordion

**状态色都过 4.5:1（对白底）**，小字可直接用不必再套底色：
`#2e6b4f` 6.30 / `#a03d33` 6.54 / `#6b6259` 5.97 / `--accent` 4.71。

**前端领域切分**：`job.js` 只管岗位本体与路由，`analysis.js` 只管解读渲染，
`el` / `deRadical` / `fold` 提到 `dom.js` 共用——否则会形成
`analysis ← job ← analysis` 的循环依赖。

**未验证**：这套布局**没有在真机浏览器里看过**。已做的验证：后端经 `TestClient`
与重启后的 7800 实测；前端用临时 DOM shim 跑通 30 个岗位（卡片数字与数据逐岗对账、
段宽合计 100%、无 `undefined`/`[object` 泄漏、复制文案与清单一致）。
卡片的实际视觉与折叠头箭头位置仍需真机确认。

## 约定

- `StaticFiles` mount在 `/` **必须放在所有 API 路由声明之后**，否则会遮蔽它们。
- **静态资源一律 `Cache-Control: no-store`**（`main.py` 中间件）。不设这个头时浏览器
  会用 `Last-Modified` 做启发式缓存：文件刚改过（Last-Modified 是几分钟前）就仍算
  「新鲜」而继续跑旧 JS，PWA 模式下 Safari 判得更松，改完前端不生效只能强刷。
  自用开发机，牺牲缓存换「改完刷新就是新的」
- 前端所有 API 调用走相对路径 `/api/...`，由同一个 FastAPI 进程 serve，无需 CORS、无需 dev server 代理。
- **改 JS 后必须做模块图可达性检查**：`index.html` 只加载 `js/app.js`，
  其余模块靠 import 链到达。裸副作用导入 `import "./x.js"`（没有 `from`）
  最容易在重写入口文件时被漏掉——文件在磁盘上、代码看着完全合理，但浏览器不下载它。
  检查要同时匹配 `from "..."` 和 `import "..."` 两种形式。

## Crawler (2026-10-08 定稿)

- **BOSS 推荐流 `wapi/zpgeek/recommend/job/list.json` 上限约 30 条**（2 批，每批 15 条，`page=1` 且 `hasMore` 为空；第 3 批 `Network.requestWillBeSent` 无新请求，滚动 3 次重试仍 `None`，`diag_net.py` 复现）。`crawler.py` `fetch_boss_recommendations` 初始 `Page.navigate zhipin.com` 即拿 15 条，滚动仅再得 1 批；`max_batches=5` 亦止于 30。
- **全量搜索 `wapi/zpgeek/search/joblist.json` 已封 `code:37 zpData seed`**，`ScraperAPI premium+render` 44k 滑块，不可用；当前唯一真实源为推荐流，猎聘 Liepin 为回退。
- **全量 JD**：`fetch_boss_details` 复用 `vendor/boss-zhipin-scraper scrape_details` 逐条 `job_detail` 拿 `jd/skill_tags/boss_active_status`，`extract_detail_fields` 校验；`jd` 为空视为关闭过滤，不入 `boss_jobs.json`。
- **存储语义**：`data/boss_jobs.json` 为**覆盖快照**（`save_snapshot`，`data/jobs.json` 已废弃删除），物理意义=当前推荐开放中岗位，非追加；仅保留带 `jd` 的开放岗。

## 尚未决定（不要自行假设）

- Persona 的存储 schema 与 Evidence 链怎么建模
- 接哪个 LLM 做 Persona 抽取 / Gap Analysis，以及是否流式。
  （Gap Analysis 已经跑起来了，走 `common.active_chain` 的容灾链，
  这一批 30 个岗位实际分布在 gemini-3.5-flash / glm-4.7-flash / deepseek-v4-flash
  三个模型上——**逐岗位独立选模型，不是整个批次一个模型**。
  解读是否流式仍未定，目前是跑批产出 JSON 文件、页面按需读文件。）
- 前端在 Phase 1 之后是否升级为 React + Vite（引入构建链）
- 前端形态（对话流 / Persona 面板 / Gap 列表）如何对应 README 的 MVP 五个模块。
  （岗位维度的 AI 解读已接入详情页，跨岗位的 Gap 频次视图还没做——
  `gap_canonical_tag` 是为跨岗位统计设计的，数据已经就位，界面还没有。）
- `job_gaps.json` 的生命周期：目前**不入 git**（`.gitignore` 第 226 行 `data/`
  整目录忽略），重跑 cluster 是全量覆盖。重跑后页面上的解读会变，要不要版本化留档未定。
  注意这意味着**换台机器 clone 下来没有解读数据**，页面会对所有岗位显示成无解读


## Persona Schema（2026-10-03 定稿，**2026-10-04 已作废**）

> 以下设计讨论保留作历史记录。当时的落地物是 `backend/persona_model.py`（Pydantic）
> 与其导出产物 `persona.md` / `backend/persona_schema.json`，现已全部删除。
> Persona 内部不再有数据模型，就是一个 dict；字段约定的唯一来源是
> `backend/persona.py` 里的 `RESUME_TO_PERSONA` prompt。
> 导出脚本 `backend.tools.export_persona_schema` 与约束检查
> `backend.tests.run_persona_checks` / `test_persona_model.py` 一并删除，无替代。

### 五条定稿决定

1. **gaps 持久化 + 快照语义。** `current_level`/`target_level` 冗余存储
   评估当时的值，**不从 `capabilities` 反查**——反查会让 gap 状态机依赖的值被偷改。
   新鲜度看 `Gap.stale()`（capability 档案比 `evaluated_at` 新即过期）。
2. **多目标。** `targets[]`，gap 挂在 target 下并按 target 分片。
3. **interventions 顶层去重。** 完成状态按 `(干预, gap)` 逐对记在
   `gap_results`，**不能**在 intervention 上放单个完成标志——两个 target 对
   同一能力的 `target_level` 可能不同，一次「学 SQL」可能关掉 PM 的 gap
   而关不掉 DA 的。
4. **LLM 产出的 gap 初始为 `proposed`**，用户批准才转 `open`。
   对应 README 的 Human in the Loop。
5. **`level` 统一 1-5 带锚点**（`LEVEL_ANCHORS`）。gaps 的 current/target 与
   `capabilities[].level` 同尺度，否则差值无意义。

### 两个承重约束

- **`capabilities[].id` 是承重外键**，`expression` 和 `gaps` 都引用它。
  必须用 `capability_slug()` 派生稳定 slug，**不能用 UUID**——改 id 即悬空。
- **`dangling_refs()` 不自动触发**。它是显式调用方法，Pydantic 不会拦。
  增量写入时允许暂时悬空是合理的；B 片落库前必须显式检查一次。

### 相对原草稿的改动

| 原草稿 | 改动 | 原因 |
|---|---|---|
| `gaps` 在 persona 下扁平 | 移到 `targets[].gaps` | 多目标需分片 |
| `interventions` 在 target 下 | 提到顶层 + `serves_gaps` | 跨目标去重 |
| 无 gap 状态 | `proposed/open/resolved/dismissed` | README 358 行避免凭印象贴标签 |
| `development.goals/- ...` | 删除 | 与 `targets[].role` 语义重叠且未定义 |
| `development.progress` | 删除 | 与 intervention 的关系无 FK；证据回流走 `new_evidence` |
| `level` / `confidence` 裸标量 | 1-5 带锚点 + 三档枚举 | 裸数字对 LLM 无意义 |
| 无时间戳 | `occurred_at` / `evaluated_at` / `updated_at` | README 385 行"有没有变好"在数据上无法回答 |
| `strengths`/`weaknesses` 缺失 | 删除 | 可从 `gaps.importance` 推导，重复存储必然漂移 |
| `compensation` 单标量 | `{current, expected}` | 谈判需要两个值 |
| `note` 自由文本 | `preferences.notes` + LLM 禁写标注 | 自由文本是 schema 退化起点 |
| 无 Communication | `expression[]` 独立结构 | 能力≠表达，README 144 行的 gap 类型塌缩了 |

### 已知取舍

- `dangling_refs()` 只报不抛：允许增量构建中途悬空。
- `category` 与 `category_raw` 并存，等真实 JD 数据到位后再定受控词表。
- 存储（B 片）用单行 JSON 列，不建正规表。等多目标跑起来有真实数据再做迁移依据。
