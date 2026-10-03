"""导出 Persona 的 JSON Schema 和示例实例。

persona.md 是本文件的生成产物。改了模型就重跑：
    conda run -n echo python -m backend.tools.export_persona_schema
"""

import json
from pathlib import Path

from backend.persona_model import (
    SCHEMA_VERSION,
    Capability,
    Experience,
    Gap,
    Intervention,
    Persona,
    Preferences,
    Profile,
    Target,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "persona.md"

EXAMPLE = Persona(
    profile=Profile(
        current_roles=["数据分析师"],
        current_state="在职，考虑转型",
        preferences=Preferences(location="上海", expected=300),
    ),
    experiences=[
        Experience(
            id="e-tmall-dashboard",
            text="2025 年在电商公司搭建日活看板，每日 ETL + 看板维护，日活查询从 2 小时降到 10 分钟。",
        ),
        Experience(
            id="e-ab-test",
            text="自述做过 A/B 实验，仅对话提及，未验证。",
        ),
    ],
    capabilities=[
        Capability(id="sql", name="SQL", experience_ids=["e-tmall-dashboard"]),
        Capability(id="interview-expression", name="面试表达", experience_ids=[]),
    ],
    targets=[
        Target(id="t-data-analyst", role="Data Analyst", note="互联网 senior"),
        Target(id="t-product-analyst", role="Product Analyst"),
    ],
    gaps=[
        Gap(
            id="g-experiment",
            target="t-data-analyst",
            capability="sql",
            note="能独立跑查询，但没有独立设计过 A/B 实验。critical，先补。",
        ),
    ],
    interventions=[
        Intervention(
            id="i-ab-test",
            action="独立完成一次 A/B 实验设计到复盘",
            note="critical gap 且有明确项目载体",
            serves_gaps=["g-experiment"],
        ),
    ],
)


def _scalar(v: object) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return f'"{v}"'


def _yaml(value: object, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out.append(_yaml(v, indent + 1))
            elif isinstance(v, dict):
                out.append(f"{pad}{k}: {{}}")
            elif isinstance(v, list):
                out.append(f"{pad}{k}: []")
            else:
                out.append(f"{pad}{k}: {_scalar(v)}")
        return "\n".join(out)
    if isinstance(value, list):
        if not value:
            return "[]"
        out = []
        for item in value:
            if isinstance(item, dict):
                body = _yaml(item, indent + 1).lstrip()
                out.append(f"{pad}- {body}")
            else:
                out.append(f"{pad}- {_scalar(item)}")
        return "\n".join(out)
    return f'"{value}"'


def render() -> str:
    schema = Persona.model_json_schema()
    example = EXAMPLE.model_dump(mode="json", exclude_defaults=False)
    dangling = EXAMPLE.dangling_refs()

    def props(node: dict, depth: int = 0) -> list[str]:
        lines = []
        for name, p in sorted(node.get("properties", {}).items()):
            ref = p.get("$ref") or p.get("allOf", [{}])[0].get("$ref", "")
            typ = ref.rsplit("/", 1)[-1] if ref else p.get("type", "any")
            req = "*" if name in node.get("required", []) else ""
            desc = (p.get("description") or "").replace("\n", " ")
            lines.append(f"| `{name}`{req} | {typ} | {desc[:90]} |")
        return lines

    top = props(schema)
    tbl = [
        "## 顶层字段",
        "",
        "| 字段 | 类型 | 说明 |",
        "|---|---|---|",
        *top,
        "",
    ]

    return "\n".join(
        [
            "# Persona Data Structure",
            "",
            "> **本文件由 `backend/persona_model.py` 生成，勿手改。**",
            "> 重新生成：`conda run -n echo python -m backend.tools.export_persona_schema`",
            "",
            f"schema_version: {SCHEMA_VERSION}",
            "",
            "## 设计：只给锚点，内容全自由文本",
            "",
            "服务对象是 LLM，不是传统程序。三处锚点：",
            "1. `capabilities[].experience_ids` 引用 `experiences[].id`（能力×经历多对多）。",
            "2. `gaps[].capability` 引用 `capabilities[].id`。",
            "3. `gaps[].target` 引用 `targets[].id`。",
            "LLM 只出名字和文本，id 由后端派生。时间、公司、结果全写进文本。",
            "",
            "## 顶层字段",
            "",
            "| 字段 | 类型 | 说明 |",
            "|---|---|---|",
            *top,
            "",
            "## 示例实例",
            "",
            "```yaml",
            _yaml(example),
            "```",
            "",
            "## 一致性检查",
            "",
            "`Persona.dangling_refs()` 列出所有悬空引用。",
            f"当前示例：**{dangling or '无悬空引用'}**。",
            "",
        ]
    )


def main() -> None:
    schema_path = ROOT / "backend" / "persona_schema.json"
    schema_path.write_text(
        json.dumps(Persona.model_json_schema(), ensure_ascii=False, indent=2)
        + "\n"
    )
    OUT.write_text(render())
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"wrote {schema_path.relative_to(ROOT)}")
    bad = EXAMPLE.dangling_refs()
    print(f"dangling refs: {bad or 'none'}")


if __name__ == "__main__":
    main()
