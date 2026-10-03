"""Persona 模型的约束测试（v4：只给锚点，内容全自由文本）。

跑：conda run -n echo python -m pytest backend/tests/test_persona_model.py -q
"""

import pytest
from pydantic import ValidationError

from backend.persona_model import (
    Capability,
    Experience,
    Gap,
    Intervention,
    Persona,
    Target,
    capability_slug,
    experience_slug,
)


def _persona(**kw) -> Persona:
    return Persona(**kw)


# ── 锚点引用 ──


def test_capability_experience_dangling_detected():
    p = _persona(capabilities=[Capability(id="sql", name="SQL", experience_ids=["ghost"])])
    assert any("capability.experience_ids" in b for b in p.dangling_refs())


def test_capability_experience_ok():
    p = _persona(
        experiences=[Experience(id="e1", text="2025 年做了 ETL")],
        capabilities=[Capability(id="sql", name="SQL", experience_ids=["e1"])],
    )
    assert p.dangling_refs() == []


def test_gap_refs_detected():
    p = _persona(
        capabilities=[Capability(id="sql", name="SQL")],
        gaps=[Gap(id="g", target="ghost-t", capability="ghost-c", note="缺")],
    )
    bad = p.dangling_refs()
    assert any("gap.target" in b for b in bad)
    assert any("gap.capability" in b for b in bad)


def test_serves_gaps_dangling_detected():
    p = _persona(interventions=[Intervention(id="i", action="a", serves_gaps=["ghost"])])
    assert any("serves_gaps" in b for b in p.dangling_refs())


def test_full_graph_no_dangling():
    p = _persona(
        experiences=[Experience(id="e1", text="做过看板")],
        capabilities=[Capability(id="sql", name="SQL", experience_ids=["e1"])],
        targets=[Target(id="t", role="DA")],
        gaps=[Gap(id="g", target="t", capability="sql", note="没独立做过")],
        interventions=[Intervention(id="i", action="做一次复盘", serves_gaps=["g"])],
    )
    assert p.dangling_refs() == []


# ── 自由文本：缺字段也能过 ──


def test_experience_needs_only_id():
    assert Experience(id="e1").text == ""


def test_gap_needs_no_note():
    assert Gap(id="g", target="t", capability="c").note == ""


def test_expected_salary_non_negative():
    from backend.persona_model import Preferences

    with pytest.raises(ValidationError):
        Preferences(expected=-5)


# ── 序列化 ──


def test_json_roundtrip_preserves_everything():
    p = _persona(
        experiences=[Experience(id="e1", text="2025 年做了 ETL")],
        capabilities=[Capability(id="sql", name="SQL", experience_ids=["e1"])],
        gaps=[Gap(id="g", target="t", capability="sql", note="缺")],
    )
    assert Persona.model_validate_json(p.model_dump_json()) == p


def test_validates_from_llm_style_dict():
    """LLM 只出名字和文本，id 由后端派生也能灌进来。"""
    p = Persona.model_validate(
        {
            "experiences": [{"id": "e1", "text": "2025 年在电商公司做 ETL"}],
            "capabilities": [{"id": "sql", "name": "SQL", "experience_ids": ["e1"]}],
            "targets": [{"id": "t", "role": "DA", "note": "互联网"}],
            "gaps": [{"id": "g", "target": "t", "capability": "sql", "note": "没独立做过"}],
        }
    )
    assert p.capabilities[0].name == "SQL"
    assert p.gaps[0].note == "没独立做过"


# ── slug ──


def test_capability_slug_stable():
    assert capability_slug("SQL") == capability_slug("sql")
    assert capability_slug("   ") == "cap"


def test_experience_slug_from_first_chars():
    assert experience_slug("2025 年在电商公司做 ETL" + "x" * 50) == experience_slug("2025 年在电商公司做 ETL" + "y" * 50)
    assert "/" not in experience_slug("A/B Testing 做过")
