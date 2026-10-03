"""Career Persona 的数据模型。

设计依据 README.md 的 MVP 定义。这是唯一的 schema 来源——
persona.md 是本文件的导出产物，不要手改。

服务对象是 LLM，不是传统程序。模型只给锚点（id 引用），
里面的内容全是自由文本，由 LLM 写、LLM 读。
时间、公司、结果全写进文本，不做结构化。

锚点只有三处：
1. experiences[].id 被 capabilities[].experience_ids 引用（能力×经历多对多）。
2. capabilities[].id 被 gaps[].capability 引用。
3. targets[].id 被 gaps[].target 引用。
LLM 只出名字和文本，id 由后端派生（见 capability_slug / experience_slug）。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 4


class Base(BaseModel):
    model_config = ConfigDict(use_enum_values=True, validate_assignment=True)


# ── Profile：只留找工作有用的 ─────────────────────────────────────────


class Preferences(Base):
    location: str = ""
    expected: int | None = Field(default=None, ge=0, description="期望年薪，单位千元")
    notes: str = Field(
        default="",
        description="只放用户手写的自由文本。LLM 不得写入本字段。",
    )


class Profile(Base):
    current_roles: list[str] = []
    current_state: str = ""
    preferences: Preferences = Preferences()


# ── Experience：一段经历，全自由文本 ────────────────────────────────


class Experience(Base):
    """一段经历。id 是锚点，text 全自由文本：时间、公司、做了什么、结果全写里面。"""

    id: str
    text: str = ""


# ── Capability：只留名字 + 经历引用 ─────────────────────────────────


class Capability(Base):
    """一项能力。name 是名字，experience_ids 指到哪些经历证明了它。"""

    id: str
    name: str
    experience_ids: list[str] = Field(default=[], description="引用 Experience.id")


# ── Target 与 Gap ─────────────────────────────────────────────────────


class Target(Base):
    """一个想去的方向。数组顺序表达主次，排第一即主目标。只留 role + note。"""

    id: str
    role: str
    note: str = ""


class Gap(Base):
    """一个差距。全自由文本：target 想去哪，capability 缺什么，note 差在哪、为什么。"""

    id: str
    target: str = Field(description="引用 Target.id")
    capability: str = Field(description="引用 Capability.id")
    note: str = ""


# ── Intervention ──────────────────────────────────────────────────────


class Intervention(Base):
    """一个具体行动。action 做什么，note 为什么做、做完有什么变化。"""

    id: str
    action: str
    note: str = ""
    serves_gaps: list[str] = Field(default=[], description="引用 Gap.id，可跨 target")


# ── Persona ───────────────────────────────────────────────────────────


class Persona(Base):
    schema_version: int = SCHEMA_VERSION
    profile: Profile = Profile()
    experiences: list[Experience] = []
    capabilities: list[Capability] = []
    targets: list[Target] = []
    gaps: list[Gap] = []
    interventions: list[Intervention] = []

    # ── 一致性检查 ──

    def experience_ids(self) -> set[str]:
        return {e.id for e in self.experiences}

    def capability_ids(self) -> set[str]:
        return {c.id for c in self.capabilities}

    def target_ids(self) -> set[str]:
        return {t.id for t in self.targets}

    def dangling_refs(self) -> list[str]:
        """列出所有悬空引用。id 改名后必然出现，返回它们好过静默出错。"""
        exps, caps, targets = self.experience_ids(), self.capability_ids(), self.target_ids()
        gaps = {g.id for g in self.gaps}
        bad: list[str] = []
        for c in self.capabilities:
            for e in c.experience_ids:
                if e not in exps:
                    bad.append(f"capability.experience_ids -> {e}")
        for g in self.gaps:
            if g.target not in targets:
                bad.append(f"gap.target -> {g.target}")
            if g.capability not in caps:
                bad.append(f"gap.capability -> {g.capability}")
        for i in self.interventions:
            for s in i.serves_gaps:
                if s not in gaps:
                    bad.append(f"intervention.serves_gaps -> {s}")
        return bad


def _slug(text: str, fallback: str = "x") -> str:
    parts = re.split(r"[\s/]+", text.strip().lower())
    slug = "-".join(p for p in parts if p)
    return slug or fallback


def capability_slug(name: str) -> str:
    """从 name 派生稳定外键。改 id 会让所有引用悬空。LLM 只出 name，后端派生 id。"""
    return _slug(name, fallback="cap")


def experience_slug(text: str) -> str:
    """从经历文本前 12 字派生稳定外键。同上，LLM 只出 text，后端派生 id。"""
    return _slug(text[:12])
