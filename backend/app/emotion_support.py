"""Local conversational cues, not diagnoses; project-only projection for external models."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SupportCue:
    kind: str
    pause_invitation: bool = True


PERSONAL_LANGUAGE = re.compile(
    r"心情|难过|伤心|低落|不开心|想哭|失恋|前任|男朋友|女朋友|委屈|心累|"
    r"担心|担忧|害怕|好怕|怕疼|怕痛|紧张|顾虑|不放心|不安|焦虑|压力|烦躁|烦死|生气|失望|"
    r"很累|好累|疲惫|"
    r"别推销|一直推销|别催|不耐烦|好丑|太丑|很丑|不好看|不漂亮|"
    r"不想聊|不想说|想静静|想安静|先不聊项目了|不聊了|先不说了|到此为止|"
    r"别问|先停|陪我聊|陪我说|嘲笑|嫌丑|安全了"
)
PROJECTS = re.compile(
    r"射频微针|黄金微针|激光脱毛|玻尿酸填充|透明质酸填充|基础补水护理|"
    r"清洁护理|舒缓护理|手部护理|背部护理|芳香护理|眼周护理|颈部护理|"
    r"背部|手部|眼周|颈部|身体放松|芳香|"
    r"光子嫩肤|热玛吉|超声炮|超声刀|肉毒毒素|水光|玻尿酸|肉毒|光子|"
    r"射频|超声|点阵|激光|脱毛|微针|补水|保湿|清洁|护肤"
)
PUBLIC_TASK = re.compile(
    r"多少钱|价格|收费|费用|预算|区别|比较|对比|原理|是什么|有什么|有哪些|"
    r"怎么进行|步骤|包括|包含|内容|流程|时长|多久|一般风险|风险|安全|"
    r"副作用|会疼|痛不痛|想了解|介绍|产品|精华|面膜|咨询吗|能先咨询"
)


def detect_support(text: str) -> SupportCue | None:
    probe = re.sub(
        r"(?:不再|不太|不|没有|没那么|不是很)(?:担心|害怕|紧张|难过|焦虑)", "", text
    ).replace("麻烦", "")
    if re.search(
        r"不想聊|不想说|想静静|想安静|先不聊项目了|不聊了|先不说了|到此为止|"
        r"别问|先停|暂停聊|缓一缓",
        probe,
    ):
        return SupportCue("pause")
    if re.search(r"别推销|一直推销|别催|不耐烦|烦躁|烦死|生气|失望|没听懂|说了.*不要", probe):
        return SupportCue("frustration")
    if re.search(r"好丑|太丑|很丑|不好看|不漂亮|外貌焦虑|容貌焦虑|嘲笑|嫌丑", probe):
        return SupportCue("appearance")
    if re.search(
        r"心情不好|难过|伤心|低落|不开心|想哭|失恋|委屈|心累|工作压力大|很累|好累|疲惫", probe
    ):
        return SupportCue("sadness")
    if re.search(r"陪我聊|陪我说|有人听我说|找人聊", probe):
        return SupportCue("companionship")
    if re.search(r"预算|价格|费用|太贵|买不起|负担不起", probe) and re.search(
        r"压力|担心|害怕|太贵|买不起|负担不起|纠结", probe
    ):
        return SupportCue("budget")
    if re.search(r"担心|担忧|害怕|好怕|怕疼|怕痛|紧张|顾虑|不放心|不安|焦虑", probe):
        return SupportCue("concern")
    if re.search(r"心情好多了|心情很好|感觉好多了|没那么难过了", text):
        return SupportCue("relief", pause_invitation=False)
    return None


def acknowledges_safety(text: str) -> bool:
    return bool(re.search(r"我(?:现在|目前|已经)安全了", text))


def public_projection(text: str) -> str:
    """Canonical public task only. Never ship emotional/relationship clauses or diagnoses."""
    cue = detect_support(text)
    if not cue and not PERSONAL_LANGUAGE.search(text):
        return text
    if not PUBLIC_TASK.search(text):
        return ""
    if not re.search(
        r"[？?]|多少钱|是什么|有什么|有哪些|怎么|介绍|想了解|请|区别|比较|对比|"
        r"包括|包含|步骤|流程|原理|多久|产品",
        text,
    ):
        return ""
    names = list(dict.fromkeys(PROJECTS.findall(text)))[:3]
    subject = "、".join(names) if names else "当前护理或项目"
    if re.search(r"多少钱|价格|收费|费用|预算", text):
        task = "价格与收费；区分项目费和咨询费，不提交申请"
    elif re.search(r"区别|比较|对比|一样", text):
        task = "一般服务内容与技术区别"
    elif re.search(r"风险|安全|副作用|会疼|痛不痛", text):
        task = "一般风险与面诊时可以问的问题，不作个人评估"
    elif re.search(r"咨询流程|到店流程|咨询吗|能先咨询", text):
        task = "到店咨询流程，不提交预约"
    elif re.search(r"产品|精华|面膜", text):
        task = "产品与护理步骤"
    elif re.search(r"多久|时长", text):
        task = "咨询或护理的时长"
    elif re.search(r"步骤|包括|包含|内容|过程", text):
        task = "服务内容与具体步骤"
    elif re.search(r"流程", text):
        task = "服务内容与具体步骤"
    elif re.search(r"到店|预约", text):
        task = "到店咨询流程，不提交预约"
    else:
        task = "一般介绍与原理"
    return f"请说明{subject}的{task}。"
