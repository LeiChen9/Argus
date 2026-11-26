"""用户认证：注册 / 登录 / 登出，用户表落 R2 的 users.json。

**密码按用户要求明文存**：最多 5 个自己人用的私有工具，不引入哈希/盐/JWT 这套
东西——users.json 一眼可查，出问题也不用 debug。代价是 R2 里的密码可还原，
所以这个 bucket 只能私有、users.json 绝不经任何 API 回吐。

会话身份靠随机 token cookie（argus_user_v2=<token>）：登录时签发并写 R2，
登出时删除；浏览器每次请求自动带上，一年后过期。
"""

import json, re, secrets, time

from workers import Response

USERS_KEY = "users.json"
# **会话 cookie**（一年）：存的是随机 token，不是用户名。Cookie 名带版本号是
# 故意的：上一版存的是用户名，换个名字等于把所有人立刻踢回未登录。登出会删
# 掉 R2 里的 token，并显式写一个空的过期 cookie。
COOKIE = "argus_user_v2"

# 职位库和职能地图是**共享资产**（crawler 抓来的岗位侧数据，不含任何个人信息），
# 新用户注册时从种子用户拷一份到自己名下，否则新账号进来是一片空白，看着像坏了。
# 简历和 persona 绝不拷——那是他自己的东西。
SEED_USER = "lbb"
SEED_FILES = ("careers.json", "boss_jobs.json")

# 用户名约束：R2 key 是路径，斜杠会把命名空间劈开；留白/怪字符会让 cookie 和
# key 都难用。够用即可，不是安全边界（真正的边界是密码）。
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,23}$")
MIN_PASSWORD = 1

_env = None


def bind_r2(env) -> None:
    """entrypoint 加载时注入 users.json 的 R2 环境。"""
    global _env
    _env = env


async def _issue(name: str) -> str:
    token = secrets.token_urlsafe(32)
    await _env.DATA.put(f"_sessions/{token}.json", json.dumps({"user": name, "exp": time.time() + 31536000}))
    return token


async def resolve(token: str) -> str:
    try:
        obj = await _env.DATA.get(f"_sessions/{token}.json")
        row = json.loads(await obj.text()) if obj else {}
    except Exception:
        return ""
    if not isinstance(row, dict):
        return ""
    try:
        exp = float(row.get("exp") or 0)
    except (TypeError, ValueError):
        return ""
    return row.get("user", "") if exp > time.time() else ""


class Bad(Exception):
    def __init__(self, detail: str, status: int = 400):
        self.detail = detail
        self.status = status


async def load_users() -> dict:
    """读整张用户表。没建过就是空表（首次部署、注册第一个用户时）。"""
    if _env is None:
        return {}
    obj = await _env.DATA.get(USERS_KEY)
    if obj is None:
        return {}
    try:
        users = json.loads(await obj.text())
    except Exception as e:
        raise RuntimeError("用户表读取失败，拒绝覆盖写入") from e
    if not isinstance(users, dict):
        raise RuntimeError("用户表格式不对，拒绝覆盖写入")
    return users


async def save_users(users: dict) -> None:
    await _env.DATA.put(USERS_KEY, json.dumps(users, ensure_ascii=False, indent=2) + "\n")


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


async def register(body: dict) -> Response:
    name = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not valid_name(name):
        raise Bad("用户名只能用字母数字和 - _，长度 1-24")
    if len(password) < MIN_PASSWORD:
        raise Bad("密码不能为空")
    users = await load_users()
    if name in users:
        raise Bad("这个用户名已经被注册了", status=409)
    users[name] = password
    await save_users(users)
    await _seed_shared(name)
    return Response.json({"ok": True, "user": name}, headers=_cookie_header(await _issue(name)))


async def _seed_shared(name: str) -> None:
    """把共享的职位库/职能地图拷进新用户的命名空间。种子用户没这些文件就跳过。"""
    for filename in SEED_FILES:
        src = await _env.DATA.get(f"{SEED_USER}/{filename}")
        if src is not None:
            await _env.DATA.put(f"{name}/{filename}", await src.text())


async def login(body: dict) -> Response:
    name = (body.get("username") or "").strip()
    password = body.get("password") or ""
    users = await load_users()
    if name not in users:
        # 用户名不存在与密码错误同一个口径：别替别人确认了哪个用户名注册过。
        raise Bad("用户名或密码不对", status=401)
    if users[name] != password:
        raise Bad("用户名或密码不对", status=401)
    return Response.json({"ok": True, "user": name}, headers=_cookie_header(await _issue(name)))


async def logout(token: str) -> Response:
    try:
        await _env.DATA.delete(f"_sessions/{token}.json")
    except Exception:
        pass
    return Response.json({"ok": True}, headers=_cookie_header(""))


def _cookie_header(value: str) -> dict:
    """Set-Cookie。SameSite=Lax：同源站点用，够用；Secure+HttpOnly 让 JS 读不到
    身份、也防明文传输（公网本来就是 https）。Max-Age 一年：登录后常驻，不用
    每次重开浏览器都登。logout 传空值 + Max-Age=0 即当场过期。"""
    max_age = 31536000 if value else 0
    cookie = f"{COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax"
    return {"set-cookie": cookie}