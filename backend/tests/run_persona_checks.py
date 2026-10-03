"""pytest 不可用时的等价跑法：同一批用例，手写最小 harness（v4）。

断言语义与 backend/tests/test_persona_model.py 一一对应。
pytest 装上后以那份为准，这份只是过渡。
"""

import sys

from pydantic import ValidationError

from backend.persona_model import (
    Capability,
    Experience,
    Gap,
    Intervention,
    Persona,
    Preferences,
    Target,
    capability_slug,
    experience_slug,
)

results = []


def case(label):
    def deco(fn):
        try:
            fn()
            results.append((True, label, ""))
        except AssertionError as e:
            results.append((False, label, f"断言失败: {e or '(无消息)'}"))
        except Exception as e:
            results.append((False, label, f"{type(e).__name__}: {e}"))
        return fn

    return deco


def rejects(fn):
    try:
        fn()
    except ValidationError:
        return
    raise AssertionError("本该抛 ValidationError 却通过了")


@case("capability.experience_ids 悬空检出")
def _():
    p = Persona(capabilities=[Capability(id="sql", name="SQL", experience_ids=["ghost"])])
    assert any("capability.experience_ids" in b for b in p.dangling_refs()), p.dangling_refs()


@case("capability.experience_ids 正常")
def _():
    p = Persona(
        experiences=[Experience(id="e1", text="2025 年做了 ETL")],
        capabilities=[Capability(id="sql", name="SQL", experience_ids=["e1"])],
    )
    assert p.dangling_refs() == [], p.dangling_refs()


@case("gap 双引用悬空检出")
def _():
    p = Persona(
        capabilities=[Capability(id="sql", name="SQL")],
        gaps=[Gap(id="g", target="ghost-t", capability="ghost-c", note="缺")],
    )
    bad = p.dangling_refs()
    assert any("gap.target" in b for b in bad), bad
    assert any("gap.capability" in b for b in bad), bad


@case("serves_gaps 悬空检出")
def _():
    p = Persona(interventions=[Intervention(id="i", action="a", serves_gaps=["ghost"])])
    assert any("serves_gaps" in b for b in p.dangling_refs()), p.dangling_refs()


@case("完整图无悬空")
def _():
    p = Persona(
        experiences=[Experience(id="e1", text="做过看板")],
        capabilities=[Capability(id="sql", name="SQL", experience_ids=["e1"])],
        targets=[Target(id="t", role="DA")],
        gaps=[Gap(id="g", target="t", capability="sql", note="没独立做过")],
        interventions=[Intervention(id="i", action="做一次复盘", serves_gaps=["g"])],
    )
    assert p.dangling_refs() == [], p.dangling_refs()


@case("experience 只要 id")
def _():
    assert Experience(id="e1").text == ""


@case("gap note 可空")
def _():
    assert Gap(id="g", target="t", capability="c").note == ""


@case("expected 负数应被拒")
def _():
    rejects(lambda: Preferences(expected=-5))


@case("JSON 往返一致")
def _():
    p = Persona(
        experiences=[Experience(id="e1", text="2025 年做了 ETL")],
        capabilities=[Capability(id="sql", name="SQL", experience_ids=["e1"])],
        gaps=[Gap(id="g", target="t", capability="sql", note="缺")],
    )
    assert Persona.model_validate_json(p.model_dump_json()) == p


@case("接受 LLM 裸 dict")
def _():
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


@case("capability_slug 稳定")
def _():
    assert capability_slug("SQL") == capability_slug("sql")
    assert capability_slug("   ") == "cap"


@case("experience_slug 取前 12 字")
def _():
    assert experience_slug("2025 年在电商公司做 ETL" + "x" * 50) == experience_slug("2025 年在电商公司做 ETL" + "y" * 50)
    assert "/" not in experience_slug("A/B Testing 做过")


if __name__ == "__main__":
    width = max(len(label) for _, label, _ in results)
    for ok, label, msg in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<{width}}  {msg if not ok else ''}")
    failed = sum(1 for ok, _, _ in results if not ok)
    print(f"\n{'=' * 52}\n{len(results) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
