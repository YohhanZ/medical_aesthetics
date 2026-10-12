"""Behavioral checks on captured real replies; not a clinical or complete semantic score."""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def evaluate(supplement: str | None = None) -> None:
    path = ROOT / "runtime/chat-quality-report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if supplement:
        extra = json.loads((ROOT / "runtime" / supplement).read_text(encoding="utf-8"))
        newer = {case["id"]: case for case in extra["cases"]}
        report["cases"] = [newer.get(case["id"], case) for case in report["cases"]]
        report["supplemental_capture"] = {
            "file": supplement,
            "captured_at": extra["captured_at"],
            "cases": len(newer),
            "turns": sum(len(c["turns"]) for c in newer.values()),
        }
    cases = {case["id"]: case for case in report["cases"]}
    turns = [turn for case in cases.values() for turn in case["turns"]]

    def result(case: str, turn: int) -> dict[str, Any]:
        return dict(cases[case]["turns"][turn - 1].get("result", {}))

    def cards(case: str, turn: int) -> set[str]:
        return {row["key"] for row in result(case, turn).get("projects", [])}

    summary_answer = result("assistant_reference", 3)["answer"]
    recall_answer = result("long_context", 10)["answer"]
    checks = {
        "complete_14_cases_50_turns": len(cases) == 14 and len(turns) == 50,
        "all_http_200": all(turn["status"] == 200 for turn in turns),
        "all_replays_consistent": all(turn.get("replay_consistent") for turn in turns),
        "history_is_complete": all(
            case.get("history_count") == 2 * len(case["turns"]) for case in cases.values()
        ),
        "explicit_hydration_answer_and_card": "补水" in result("care_hydration", 4)["answer"]
        and "清洁护理" not in result("care_hydration", 4)["answer"]
        and cards("care_hydration", 4) == {"hydration"},
        "comparison_keeps_both_subjects": cards("care_hydration", 3) == {"hydration", "cleansing"},
        "ten_turn_initial_topic_is_correct": "补水" in recall_answer
        and "首次护理体验" not in recall_answer,
        "medical_followup_remains_local": all(
            result("medical_risk", i).get("handoff_reason") == "personal_medical" for i in (1, 2)
        ),
        "public_negation_is_not_medical_assessment": all(
            result(case, 3).get("mode") in ("generated", "evidence_fallback")
            and not result(case, 3).get("handoff_reason")
            for case in ("medical_energy", "medical_risk")
        ),
        "photon_first_question_recognized": result("general_medical", 1).get("mode") != "fixed"
        and "ipl" in cards("general_medical", 1),
        "summary_matches_visit_flow": (
            ("到店" in summary_answer and "门店" in summary_answer)
            or all(word in summary_answer for word in ("方向", "补充", "意向"))
        )
        and "多个问题" not in summary_answer
        and "幂等" not in summary_answer,
        "decline_keeps_public_subject": cards("decline", 3) == {"cleansing"},
        "topic_switch_uses_current_project": cards("care_switch", 2) == {"back-care"}
        and cards("topic_change", 3) == {"hand-care"},
        "unrelated_programming_is_local": result("topic_change", 2).get("mode") == "fixed"
        and not any(
            node["node"] in ("retrieve", "generate")
            for node in cases["topic_change"]["turns"][1].get("trace", [])
        ),
        "business_handoff_explains_actual_reason": result("booking_flow", 4).get("handoff_reason")
        == "human_or_business"
        and "业务流程" in result("booking_flow", 4)["answer"]
        and "缺少可核验" not in result("booking_flow", 4)["answer"],
        "invitation_does_not_submit_booking": result("decline", 4).get("action")
        == {"type": "visit_interest", "submitted": False},
    }
    summary = {
        "cases": len(cases),
        "turns": len(turns),
        "modes": dict(Counter(turn.get("result", {}).get("mode") for turn in turns)),
        "retrieval_methods": dict(
            Counter(
                node["outcome"]
                for turn in turns
                for node in turn.get("trace", [])
                if node["node"] == "retrieve"
            )
        ),
        "fallback_causes": dict(
            Counter(
                node["outcome"]
                for turn in turns
                for node in turn.get("trace", [])
                if node["node"] == "model"
            )
        ),
        "latency_median_seconds": round(statistics.median(t["elapsed_seconds"] for t in turns), 2),
        "latency_max_seconds": max(t["elapsed_seconds"] for t in turns),
        "checks": checks,
        "scope": "Targeted real-reply regression checks; not a complete semantic/medical approval",
    }
    report["summary"] = summary
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    assert all(checks.values()), "Captured targeted regression failed; inspect original replies"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--supplement", help="Additional captured cases in runtime; preserves original capture"
    )
    evaluate(parser.parse_args().supplement)
