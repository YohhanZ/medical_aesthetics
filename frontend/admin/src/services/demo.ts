import { reactive } from "vue";
import type {
  Booking,
  BookingStatus,
  Customer,
  Knowledge,
  Profile,
  Project,
} from "../types";

export const demoProfile: Profile = {
  id: "demo-reviewer",
  username: "运营演练账号",
  simulated: true,
  stores: [
    {
      id: "demo-shanghai",
      name: "模拟上海体验店",
      simulated: true,
      permissions: [
        "knowledge_author",
        "knowledge_review",
        "knowledge_publish",
      ],
    },
    {
      id: "demo-hangzhou",
      name: "模拟杭州体验店",
      simulated: true,
      permissions: [
        "knowledge_author",
        "knowledge_review",
        "knowledge_publish",
      ],
    },
  ],
};
const stamp = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
};
const day = (days: number) => stamp(days).slice(0, 10);
function createData(second = false) {
  const bookings: Booking[] = second
    ? []
    : [
        {
          id: "DEMO-A001",
          customer: "体验客户 A",
          intent: "先到店咨询，项目未定",
          expected: `${day(1)} 14:00`,
          confirmed: "",
          status: "pending_store_confirmation",
          source: "对话咨询 · 演练",
          events: ["客户已确认申请内容（合成记录）", "等待门店确认时间"],
        },
        {
          id: "DEMO-A002",
          customer: "体验客户 B",
          intent: "水润护理",
          expected: `${day(0)} 15:30`,
          confirmed: `${day(0)} 15:30`,
          status: "confirmed",
          source: "对话咨询 · 演练",
          events: [
            "客户已确认申请内容（合成记录）",
            "门店确认到店时间（演练）",
          ],
        },
        {
          id: "DEMO-A003",
          customer: "体验客户 C",
          intent: "肤质咨询",
          expected: `${day(0)} 11:00`,
          confirmed: `${day(0)} 11:00`,
          status: "arrived",
          source: "对话咨询 · 演练",
          events: ["客户已确认申请内容（合成记录）", "客户到店登记（演练）"],
        },
      ];
  const customers: Customer[] = second
    ? []
    : [
        {
          id: "DEMO-C001",
          name: "体验客户 A",
          stage: "待到店咨询",
          initialIntent: "暂不确定项目",
          currentIntent: "先了解护理体验",
          history: [
            { time: "咨询开始", text: "最初意向：暂不确定项目。" },
            {
              time: "后续追问",
              text: "想先了解日常护理体验，尚无最终项目确认。",
            },
          ],
        },
        {
          id: "DEMO-C002",
          name: "体验客户 B",
          stage: "已确认到店时间",
          initialIntent: "了解水润护理",
          currentIntent: "水润护理咨询",
          history: [
            { time: "咨询开始", text: "最初意向：了解水润护理。" },
            {
              time: "门店确认",
              text: "已确认到店时间，具体项目待到店进一步了解。",
            },
          ],
        },
        {
          id: "DEMO-C003",
          name: "体验客户 C",
          stage: "已到店",
          initialIntent: "肤质咨询",
          currentIntent: "需要专业人员进一步咨询",
          history: [
            { time: "咨询开始", text: "最初意向：肤质咨询。" },
            {
              time: "到店",
              text: "现场补充咨询需求，尚未产生客户最终项目确认。",
            },
          ],
        },
      ];
  const projects: Project[] = [
    {
      id: "DEMO-P001",
      title: "水润护理",
      category: "美容护理",
      introduction:
        "了解日常保湿护理体验。模拟目录，具体供给与报价需机构核验。",
      active: true,
    },
    {
      id: "DEMO-P002",
      title: "肤质管理咨询",
      category: "医疗美容咨询",
      introduction:
        "先由专业人员沟通需求与适用边界。模拟目录，不构成治疗方案。",
      active: true,
    },
    {
      id: "DEMO-P003",
      title: "亮泽护理",
      category: "美容护理",
      introduction: "了解温和护理方向。模拟目录，不提供疗效或报价承诺。",
      active: false,
    },
  ];
  const knowledge: Knowledge[] = [
    {
      id: "demo-k1",
      knowledge_key: "booking-process",
      version: 1,
      category: "operational",
      title: "到店咨询与预约流程",
      content:
        "【模拟资料】在线提交咨询申请，门店确认时间后才是已确认预约。具体项目可以到店后再确定。",
      source: "本地合成运营资料",
      author_id: "demo-author",
      simulated: true,
      valid_until: stamp(90),
      created_at: stamp(-1),
      status: "draft",
    },
    {
      id: "demo-k2",
      knowledge_key: "respect-refusal",
      version: 1,
      category: "communication",
      title: "尊重客户的预约意愿",
      content:
        "【合成沟通策略】先回答问题；客户暂不预约时停止邀请，不用外貌焦虑或限时承诺推动决定。",
      source: "合成沟通策略",
      author_id: "demo-author",
      simulated: true,
      valid_until: stamp(90),
      created_at: stamp(-2),
      status: "publishing",
      projection_state: "pending",
    },
    {
      id: "demo-k3",
      knowledge_key: "medical-placeholder",
      version: 1,
      category: "medical",
      title: "医学资料待审核占位",
      content: "尚无权威医学证据，仅演练待审流程，禁止对客使用。",
      source: "待实际医学资料与审核人员核验",
      author_id: "demo-author",
      simulated: true,
      valid_until: stamp(90),
      created_at: stamp(-2),
      status: "draft",
    },
  ];
  return { bookings, customers, projects, knowledge };
}
export const demoData = reactive<Record<string, ReturnType<typeof createData>>>(
  { "demo-shanghai": createData(), "demo-hangzhou": createData(true) },
);
export const bookingLabels: Record<BookingStatus, string> = {
  pending_store_confirmation: "待门店确认",
  confirmed: "已确认",
  arrived: "已到店",
  declined: "已婉拒",
  cancelled: "已取消",
};
export const knowledgeLabels = {
  draft: "待审核",
  approved: "审核通过",
  rejected: "审核未通过",
  publishing: "等待投影",
  published: "已发布",
  withdrawn: "已撤回",
};
export function transitionBooking(
  row: Booking,
  action: "confirm" | "arrive" | "decline",
  confirmed = "",
  checked = false,
) {
  if (
    action === "confirm" &&
    row.status === "pending_store_confirmation" &&
    confirmed &&
    checked
  ) {
    row.status = "confirmed";
    row.confirmed = confirmed;
    row.events.push(`门店确认时间：${confirmed}（演练）`);
    return;
  }
  if (action === "arrive" && row.status === "confirmed" && checked) {
    row.status = "arrived";
    row.events.push("已登记到店（演练）");
    return;
  }
  if (
    action === "decline" &&
    row.status === "pending_store_confirmation" &&
    checked
  ) {
    row.status = "declined";
    row.events.push("门店暂无法接受申请（演练）");
    return;
  }
  throw new Error("请核实当前状态、到店时间并明确确认操作。");
}
