"""Local routing and projection of public questions; never exports medical/business records."""

import re
from typing import Any

from app.customer import RECALL, is_preference_statement
from app.emotion_support import (
    PERSONAL_LANGUAGE,
    acknowledges_safety,
    detect_support,
    public_projection,
)
from app.model_gateway import redact_contacts

GREETING = "你好，我是咨询助手。你可以直接问项目、护理或到店咨询流程；也可以先说说想了解的方向。"


def classify(
    text: str,
    has_context: bool = False,
    medical_pending: bool = False,
    crisis_pending: bool = False,
) -> dict[str, Any]:
    clean = redact_contacts(text).strip()
    preference_statement = is_preference_statement(clean)
    # Only remove explicit refusals of an assessment, never symptoms or personal health facts.
    probe = re.sub(
        r"不(?:给我定|给我提供|需要(?:你)?(?:判断|提供)|要(?:你)?(?:判断|提供))"
        r"(?:个人)?(?:治疗方案|适合性)",
        "",
        clean,
    )
    if (
        re.search(r"一般|通常|常见|可能|风险", probe)
        and not re.search(r"我|本人|自己|她|他|朋友|客户|刚做|做完|打完|术后", probe)
        and not medical_pending
    ):
        # Generic public risk education is distinct from a person's symptoms/history.
        probe = re.sub(r"过敏|疼痛|出血|发热|肿胀|瘙痒|发痒|红疹|感染", "", probe)
    reason = ""
    if re.search(
        r"忽略.*(规则|指令)|系统提示|system prompt|执行.*(sql|cypher)|别人的|其他客户|客户名单",
        clean,
        re.I,
    ):
        reason = "unauthorized_request"
    elif re.search(r"呼吸困难|昏迷|大出血|突然.*视力|视力.*突然", clean):
        reason = "urgent_health"
    elif re.search(
        r"不想活|活不下去|想死|轻生|自杀|自残|伤害自己|结束生命|割腕",
        re.sub(r"(?:没有|没|不是)(?:想|打算|准备)(?:死|自杀|自残|伤害自己|结束生命)", "", clean),
    ):
        reason = "emotional_crisis"
    elif crisis_pending and not acknowledges_safety(clean):
        reason = "emotional_crisis"
    elif not preference_statement and re.search(
        r"怀孕|哺乳|孕期|过敏|用药|病史|诊断|治疗方案|剂量|疼痛|出血|发热|肿胀|"
        r"抑郁症|焦虑症|抗抑郁|抗焦虑|心理疾病|失眠|"
        r"瘙痒|发痒|红疹|感染|我.*(疼|肿)|打完.*(肿|疼|怎么办|正常)|"
        r"糖尿病|高血压|心脏病|癌症|年龄[:：]|我.*岁|术后.*(怎么办|正常)|"
        r"适合我|我.*(适合|能.?做|可.*做)|照片.*判断",
        probe,
    ):
        reason = "personal_medical"
    elif (
        medical_pending
        and re.search(r"^(那|这个|它|换成|还有|也)", clean)
        and (
            re.search(r"能.?做|可以.{0,3}做|适合|换成.*(可以吗|行吗)", probe)
            or re.fullmatch(
                r"(?:那|这个|它|换成|还有|也).{0,12}(呢|可以吗|行吗|安全吗|合适吗)[？?]?", probe
            )
        )
    ):
        reason = "personal_medical"
    elif re.search(
        r"我叫|姓名[:：]|身份证|家庭住址|住在|银行卡|验证码|订单号|合同号|病历|医疗档案", clean
    ):
        reason = "private_record"
    elif re.search(
        r"转人工|找真人|人工客服|投诉|订单查询|我的预约|预约状态|"
        r"(帮我|我要|我想|办理|申请|现在).{0,6}(取消|退款|签合同|付款|支付)",
        clean,
    ):
        reason = "human_or_business"
    greeting = bool(re.fullmatch(r"[你好您好嗨哈喽！!。.\s]+|hello|hi", clean, re.I))
    intent, stage = "information", "awareness"
    if re.search(r"不想.*预约|不要.*预约|先不.*预约|不预约|不.*营销|不.*推销", clean):
        intent, stage = "decline", "awareness"
    elif re.search(r"帮我.*预约|我要预约|想预约|预约.*(明天|周末|今天)|确认预约", clean):
        intent, stage = "visit_interest", "visit_interest"
        reason = reason or "visit_request"
    elif re.search(r"价格|多少钱|收费|预算|贵|便宜|比较|区别|哪个|优惠", clean):
        intent, stage = "comparison", "comparison"
    elif re.search(r"想了解|关注|补水|清洁|保湿|抗衰|紧致|皮肤", clean):
        stage = "needs"
    related = has_context or bool(
        re.search(
            r"医美|美丽田园|美容|护肤|护理|项目|预约|到店|咨询|价格|收费|预算|活动|取消|隐私|门店|医生|补水|皮肤|清洁|保湿|抗衰|热玛吉|光子|光电|射频|超声|水光|微针|肉毒|玻尿酸|填充|激光|皮秒|点阵|脱毛|瘢痕|塑形|体形|秀可儿|研源|售后|回访|多久|多少钱|付款|说明书",
            clean,
        )
    )
    if greeting and not reason:
        intent = "greeting"
    elif not reason and (
        RECALL.search(clean) or re.search(r"(一开始|最初|最开始).*(方向|聊|项目)|最初聊", clean)
    ):
        intent = "recall"
    elif not reason and re.search(r"Python|排序函数|编程|写代码|股票|天气预报", clean, re.I):
        intent = "clarify"
    elif not related and not reason and intent != "decline":
        intent = "clarify"
    cue = detect_support(clean)
    projected = public_projection(clean) if not reason else ""
    if not reason and (cue or PERSONAL_LANGUAGE.search(clean)) and not projected:
        intent, stage = "support", "awareness"
    elif not reason and cue and intent == "decline" and projected:
        intent, stage = "information", "awareness"
    if (
        not reason
        and cue
        and cue.kind == "pause"
        and re.search(r"想静静|想安静|不想聊|暂停聊|先停|缓一缓", clean)
    ):
        intent, stage = "support", "awareness"
    if reason == "emotional_crisis":
        intent, stage = "support", "awareness"
    if preference_statement and not reason and intent != "decline":
        intent, stage = "recall", "awareness"
    return {
        "question": projected if not reason and projected else clean,
        "intent": intent,
        "stage": stage,
        "reason": reason,
    }


def public_question(text: str) -> str:
    if RECALL.search(text) or is_preference_statement(text):
        from app.model_gateway import GatewayError

        raise GatewayError("consultation_export_denied")
    policy = classify(text, True)
    if policy["reason"] or re.search(r"Python|排序函数|编程|写代码|股票|天气预报", text, re.I):
        from app.model_gateway import GatewayError

        raise GatewayError("consultation_export_denied")
    if policy["intent"] == "support":
        from app.model_gateway import GatewayError

        raise GatewayError("consultation_export_denied")
    return str(policy["question"])


def handoff_answer(reason: str) -> str:
    if reason == "emotional_crisis":
        return (
            "听起来你正在承受很大的痛苦，先把自己的安全放在第一位。"
            "请联系一个能陪在你身边的可信任的人，暂时远离可能伤害自己的物品；"
            "如果已经受伤或有立即伤害自己的危险，请马上联系当地急救或医疗机构。"
            "这里不能替代紧急帮助，转接请求已记录，人工尚未接通。"
        )
    if reason == "urgent_health":
        return "这涉及可能紧急的健康情况，请立即联系当地急救或医疗机构。人工咨询尚未接通。"
    if reason == "personal_medical":
        return (
            "这个问题需要专业人员结合面诊评估，在线咨询无法判断个人适合性或提供治疗方案。"
            "已记录转接请求，人工尚未接通。"
        )
    if reason == "private_record":
        return "普通咨询无需提供身份或业务记录，请去除这些信息后继续提问。人工尚未接通。"
    if reason == "visit_request":
        return (
            "已记录你想预约咨询的意愿。人工尚未接通，目前还没有提交或确认到店预约；"
            "你可以继续了解项目与咨询流程。"
        )
    if reason == "unauthorized_request":
        return "我可以回答公开咨询问题，无法访问其他客户的信息或执行系统操作。人工尚未接通。"
    if reason == "evidence_changed":
        return "相关资料已更新或失效，当前无法继续引用。已记录转接请求，人工尚未接通。"
    if reason == "human_or_business":
        return (
            "这项请求需要门店人员或对应的业务流程处理。预约调整或取消请在预约记录中核实并明确确认；"
            "聊天本身不会改变预约或产生付款。已记录转接请求，人工尚未接通。"
        )
    return "目前缺少可核验的资料来回答这个问题。已记录转接请求，人工尚未接通。"
