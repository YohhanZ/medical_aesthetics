import { clearSession, session } from "../state";

export class ApiError extends Error {
  constructor(
    public code: string,
    public requestId = "",
    public status = 0,
  ) {
    super(code);
  }
}
export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string } = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  const token = options.token ?? session.value?.token;
  if (session.value?.mode === "demo")
    throw new ApiError("demo_cannot_call_live_api");
  try {
    const response = await fetch(`/api${path}`, {
      method: options.method ?? "GET",
      signal: controller.signal,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      credentials: "omit",
      cache: "no-store",
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      if (response.status === 401 && session.value?.mode === "live")
        clearSession();
      throw new ApiError(
        error.code ?? "service_unavailable",
        error.request_id ?? "",
        response.status,
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      error instanceof DOMException && error.name === "AbortError"
        ? "request_timeout"
        : "network_unavailable",
    );
  } finally {
    clearTimeout(timer);
  }
}
const descriptions: Record<string, string> = {
  demo_materials_unavailable: "当前环境或门店没有开放演示资料。",
  followup_not_found: "回访计划不存在或不在当前授权门店。",
  followup_state_conflict: "回访版本或状态已变化，请刷新核实。",
  followup_source_changed: "当前咨询版本尚未由客户确认，请重新核实。",
  followup_plan_invalid: "请填写回访说明及未来90天以内的计划时间。",
  followup_opted_out: "客户已暂停此档案的回访邀请，只有客户本人可以恢复。",
  followup_already_open: "该档案已有未结束的回访计划，请先查看原记录。",
  followup_key_conflict: "原回访请求内容不一致，请核实，勿重复提交。",
  consultation_not_found: "咨询档案不存在或不在当前授权门店。",
  consultation_already_exists: "这份到店预约已有档案，请刷新后查看原记录。",
  consultation_state_conflict: "档案版本已变化，请刷新后审阅当前内容。",
  consultation_key_conflict: "原请求内容不一致，请核实档案，勿重复提交。",
  appointment_time_unchanged: "新时间与原安排一致，无需发起改约。",
  arrival_confirmation_required: "请先核实客户身份及实际到店，并明确登记。",
  customer_confirmation_required: "请审阅当前操作并明确确认。",
  appointment_not_found: "申请不存在或不在当前授权门店。",
  appointment_state_conflict: "申请已由其他人员处理或版本变化，请刷新核实。",
  appointment_time_invalid: "期望时间已失效，需与客户重新确认后发起申请。",
  store_confirmation_required: "请核实接待安排并明确确认；婉拒需选择原因。",
  booking_key_conflict: "原请求内容不一致，请核实记录，勿重复提交。",
  booking_policy_changed: "预约政策已更新，需客户重新确认申请。",
  booking_policy_unavailable: "当前预约政策已失效，请核实知识发布。",
  project_unavailable: "申请所选项目已失效，请联系客户重新确认。",
  invalid_credentials: "账号或密码不正确。",
  login_throttled: "登录尝试过多，请稍后再试。",
  unauthenticated: "登录已失效，请重新登录。",
  store_permission_denied: "你没有这个门店的操作权限。",
  independent_review_required: "这条知识需要另一位授权人员审核，作者不能自审。",
  medical_verification_required:
    "医学资质核验尚未接入，这条内容需继续等待医学审核。",
  real_content_requires_real_review: "模拟审核不能批准真实机构资料。",
  publication_not_allowed: "知识未通过审核或已经过期，暂不能发布。",
  review_state_conflict: "知识状态已变化，请刷新后重试。",
  simulation_disabled: "当前环境不允许使用模拟资料。",
  invalid_input: "请检查表单内容和有效日期。",
  origin_denied: "当前前端地址未获服务端授权，请检查本地来源配置。",
  database_unavailable: "数据服务暂不可用，请稍后重试。",
  network_unavailable: "无法连接服务，请检查 API 是否已启动。",
  request_timeout: "请求超时。请刷新核实结果后再操作。",
};
export function errorText(error: unknown) {
  if (error instanceof ApiError)
    return `${descriptions[error.code] ?? "操作未完成，请刷新核实后重试。"}${error.requestId ? ` 请求编号：${error.requestId}` : ""}`;
  return error instanceof Error ? error.message : "操作未完成。";
}
