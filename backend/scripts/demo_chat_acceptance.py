"""Check captured concrete demo conversations; not clinical or full semantic approval."""

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parents[2] / "runtime" / "demo-chat-report.json"


def evaluate() -> None:
    report = json.loads(PATH.read_text("utf-8"))
    cases = {c["id"]: c for c in report["cases"]}
    turns = [t for c in cases.values() for t in c["turns"]]

    def turn(case: str, number: int) -> dict[str, Any]:
        return dict(cases[case]["turns"][number - 1])

    def answer(case: str, number: int) -> str:
        return str(turn(case, number).get("result", {}).get("answer", ""))

    def cards(case: str, number: int) -> set[str]:
        return {p["key"] for p in turn(case, number).get("result", {}).get("projects", [])}

    checks = {
        "complete_12_cases_46_turns": len(cases) == 12 and len(turns) == 46,
        "all_http_200": all(t["status"] == 200 for t in turns),
        "all_replays_consistent": all(t.get("replay_consistent") for t in turns),
        "all_histories_and_logout": all(
            c["history_status"] == 200
            and c["history_count"] == len(c["turns"]) * 2
            and c["logout_status"] == 200
            for c in cases.values()
        ),
        "no_directory_placeholder_answers": not any(
            phrase in t.get("result", {}).get("answer", "")
            for t in turns
            for phrase in (
                "仅作为了解目录",
                "无法依据目录名称",
                "缺乏门店提供的批准说明",
                "【模拟机构资料】",
            )
        ),
        "hydration_has_steps_and_duration": all(
            phrase in answer("demo_hydration", 1) for phrase in ("精华", "面膜", "60")
        ),
        "price_followup_keeps_hydration": "298" in answer("demo_hydration", 2)
        and cards("demo_hydration", 2) == {"hydration"},
        "comparison_keeps_both_care_projects": cards("demo_hydration", 4)
        == {"hydration", "cleansing"},
        "budget_has_concrete_options": all(
            price in answer("demo_budget", 1) for price in ("298", "258", "268", "188")
        ),
        "ipl_has_a_real_definition": "IPL" in answer("demo_ipl", 1)
        and "ipl" in cards("demo_ipl", 1),
        "energy_difference_is_explained": "射频" in answer("demo_energy", 1)
        and "声能" in answer("demo_energy", 1),
        "both_energy_prices_are_supported": all(
            price in answer("demo_energy", 2) for price in ("9800", "6800")
        ),
        "needle_name_is_not_confused_with_other_rf": cards("demo_needle", 1)
        == {"rf-microneedling-overview"},
        "hair_removal_is_recognized_from_first_turn": turn("demo_hair", 1)
        .get("result", {})
        .get("mode")
        in ("generated", "evidence_fallback")
        and "hair-removal-overview" in cards("demo_hair", 1),
        "new_care_topic_has_own_price": "188" in answer("demo_care_switch", 2)
        and cards("demo_care_switch", 2) == {"hand-care"},
        "initial_topic_and_return_price": "基础补水护理" in answer("demo_memory", 9)
        and "298" in answer("demo_memory", 10),
        "personal_medical_inputs_remain_local": all(
            t["result"].get("handoff_reason") == "personal_medical"
            and not any(n["node"] in ("retrieve", "generate") for n in t.get("trace", []))
            for t in cases["demo_personal_risk"]["turns"]
        ),
        "booking_interest_does_not_submit": turn("demo_choice", 3).get("result", {}).get("action")
        == {"type": "visit_interest", "submitted": False},
        "simulation_is_visible_in_api_metadata": all(
            t["result"].get("simulated") is True and "虚构" in t["result"].get("disclosure", "")
            for t in turns
            if t.get("result", {}).get("evidence_ids")
        ),
    }
    summary = {
        "cases": len(cases),
        "turns": len(turns),
        "modes": dict(Counter(t.get("result", {}).get("mode") for t in turns)),
        "latency_median_seconds": round(statistics.median(t["elapsed_seconds"] for t in turns), 2),
        "latency_max_seconds": max(t["elapsed_seconds"] for t in turns),
        "checks": checks,
        "scope": (
            "Targeted synthetic demo behavior; not medical, general language or production approval"
        ),
    }
    report["summary"] = summary
    PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    assert all(checks.values()), "Inspect failed demo behavior in original captured replies"


if __name__ == "__main__":
    evaluate()
