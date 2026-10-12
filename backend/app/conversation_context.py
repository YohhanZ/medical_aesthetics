"""Bounded public topic references, resolved only against the current scoped catalog."""

import re
from typing import Any

from app.agent_policy import classify, public_question
from app.model_gateway import GatewayError

TOPIC_ALIASES = {
    "hydration": ["补水", "保湿", "水润"],
    "cleansing": ["清洁"],
    "relaxation": ["舒缓"],
    "assessment": ["皮肤检测", "皮肤状态"],
    "ipl": ["光子嫩肤", "光子"],
    "rf": ["热玛吉", "射频"],
    "ultrasound": ["超声", "超声刀", "超声炮"],
    "skin-injection": ["水光"],
    "filler": ["玻尿酸填充", "透明质酸填充", "填充", "玻尿酸"],
    "botulinum": ["肉毒", "肉毒毒素"],
    "aroma-care": ["芳香"],
    "back-care": ["背部护理"],
    "hand-care": ["手部护理"],
    "laser-overview": ["激光", "皮秒"],
    "fractional-overview": ["点阵"],
    "microneedling-overview": ["微针"],
    "rf-microneedling-overview": ["射频微针", "黄金微针"],
    "hair-removal-overview": ["激光脱毛", "脱毛"],
    "contouring-overview": ["体形", "塑形"],
    "pigment-consultation": ["色素", "色斑"],
    "scar-consultation": ["瘢痕"],
    "texture-consultation": ["肤质"],
    "fine-line-consultation": ["细纹"],
    "makeup-cleanse": ["卸妆"],
}
OPERATIONAL = re.compile(
    r"准备|收费|价格|多少钱|预约|付款|门店|流程|隐私|来源|品牌|说明书|资料|取消"
)
HISTORY_REFERENCE = re.compile(r"刚才.*(步骤|提到|总结)|第二.*步骤|总结.*(刚才|流程)|一句话.*流程")
TOPIC_DETAIL = re.compile(r"多少钱|价格|收费|步骤|包括|产品|时长|多久|区别|比较|体验|效果|风险")
STORE_FLOW = re.compile(r"预约|营业|地址|门店.*(在哪|时间)|取消|付款|隐私")


class PublicTopics:
    def __init__(self, projects: list[dict[str, Any]]) -> None:
        self.projects = {p["key"]: p for p in projects}

    def match(self, text: str) -> list[str]:
        spans: list[tuple[str, int, int]] = []
        for key, project in self.projects.items():
            name = re.sub(r"^(模拟目录[:：]|模拟了解目录[:：])", "", project["title"])
            short = re.sub(r"(项目了解|体验了解|方向咨询|了解|项目)$", "", name)
            aliases = TOPIC_ALIASES.get(key, []) + [name, short]
            for alias in set(aliases):
                if len(alias) >= 2:
                    spans.extend(
                        (key, m.start(), m.end()) for m in re.finditer(re.escape(alias), text)
                    )
        matches = []
        for key, start, end in spans:
            if any(
                other != key and left <= start and right >= end and right - left > end - start
                for other, left, right in spans
            ):
                continue
            if key not in matches:
                matches.append(key)
        return matches[:3]

    def resolve(self, memory: dict[str, Any], field: str) -> dict[str, Any] | None:
        record = memory.get(field)
        if not isinstance(record, dict):
            return None
        source = memory.get("_topic_sources", {}).get(record.get("source_run_id"))
        if not source:
            return None
        try:
            question = public_question(source["content"])
        except GatewayError:
            policy = classify(source["content"], True)
            if policy["reason"] or policy["intent"] != "support":
                return None
            # Emotion-only turns may name a public topic. Resolve the owned reference locally;
            # only its scoped project labels become context, never the source feelings.
            question = "请介绍" + "、".join(self.labels(self.match(source["content"]))) + "。"
        keys = [key for key in record.get("keys", []) if key in self.match(source["content"])]
        return {**record, "keys": keys, "question": question} if keys else None

    def labels(self, keys: list[str]) -> list[str]:
        return [self.projects[key]["title"] for key in keys if key in self.projects]

    def record(self, keys: list[str], run_id: str, message_id: str) -> dict[str, Any]:
        return {"keys": keys[:3], "source_run_id": run_id, "source_message_id": message_id}

    def query(self, question: str, keys: list[str], explicit: list[str]) -> str:
        if (
            keys
            and not explicit
            and TOPIC_DETAIL.search(question)
            and not STORE_FLOW.search(question)
        ):
            return "、".join(self.labels(keys)) + "\n" + question
        if explicit or OPERATIONAL.search(question) or not keys:
            return question
        return "、".join(self.labels(keys)) + "\n" + question

    def rank(
        self,
        question: str,
        keys: list[str],
        evidence: list[dict[str, Any]],
        current: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if re.search(r"咨询.*流程|流程.*咨询|第一次到店.*顺序", question):
            flow = [r for r in current.values() if r.get("knowledge_key") == "consultation-process"]
            return list({str(r["id"]): r for r in flow + evidence}.values())[:3]
        if not keys or (
            OPERATIONAL.search(question)
            and (not TOPIC_DETAIL.search(question) or STORE_FLOW.search(question))
        ):
            return evidence[:3]
        scoped = [
            current[p["id"]] for key in keys if (p := self.projects.get(key)) and p["id"] in current
        ]
        # Explicit current topics outrank a stale comparison topic, including during fallback.
        unrelated = {p["id"] for key, p in self.projects.items() if key not in keys}
        rest = [row for row in evidence if str(row["id"]) not in unrelated]
        unique = {str(row["id"]): row for row in scoped + rest}
        return list(unique.values())[:3]
