import type {
  Answer,
  HistoryMessage,
  PendingMessage,
  Project,
  PublicStore,
  Thread,
  VisitorSession,
} from "../types";
import type {
  BookingState,
  BookingDraft,
  Verification,
  Appointment,
  CreateDraft,
  SendCode,
  ConfirmDraft,
  CancelAppointment,
  RespondChange,
} from "./booking";
import type { CaseDecision, VisitCase } from "./cases";
import type { Followup, FollowupResponse } from "./followups";
import type { CustomerIdentity } from "./customer";

export class ApiError extends Error {
  constructor(
    public code: string,
    public status = 0,
    public requestId = "",
  ) {
    super(code);
  }
}
export interface ConsultationApi {
  stores(): Promise<PublicStore[]>;
  current(): Promise<VisitorSession>;
  createSession(code: string): Promise<void>;
  customerSession(): Promise<CustomerIdentity>;
  threads(offset?: number): Promise<Thread[]>;
  newThread(): Promise<string>;
  history(thread: string, offset?: number): Promise<HistoryMessage[]>;
  send(thread: string, message: PendingMessage): Promise<Answer>;
  projects(): Promise<Project[]>;
  project(id: string): Promise<Project>;
}
export class ApiClient implements ConsultationApi {
  private csrf = "";
  constructor(private transport: typeof fetch = fetch.bind(globalThis)) {}
  private async request<T>(
    path: string,
    body?: unknown,
    retryCsrf = true,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      body && path.endsWith("/messages") ? 45000 : 15000,
    );
    try {
      const response = await this.transport(`/api${path}`, {
        method: body === undefined ? "GET" : "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        headers:
          body === undefined
            ? {}
            : { "Content-Type": "application/json", "X-CSRF-Token": this.csrf },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        if (
          response.status === 403 &&
          error.code === "csrf_invalid" &&
          retryCsrf
        ) {
          await this.current();
          return this.request<T>(path, body, false);
        }
        throw new ApiError(
          error.code ?? "service_unavailable",
          response.status,
          error.request_id ?? "",
        );
      }
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        controller.signal.aborted ? "request_timeout" : "network_unavailable",
      );
    } finally {
      clearTimeout(timer);
    }
  }
  async stores() {
    return (await this.request<{ items: PublicStore[] }>("/public/stores"))
      .items;
  }
  customerSession() {
    return this.request<CustomerIdentity>("/customer/session");
  }
  async customerAuth(
    username: string,
    password: string,
    register: boolean,
    bindCurrent: boolean,
    enableMemory?: boolean,
  ) {
    const result = await this.request<{
      csrf_token: string;
      restored: boolean;
    }>(register ? "/customer-accounts" : "/customer-sessions", {
      username,
      password,
      bind_current: bindCurrent,
      ...(enableMemory === undefined ? {} : { enable_memory: enableMemory }),
    });
    this.csrf = result.csrf_token;
    return result;
  }
  async customerLogout() {
    await this.request("/visitor-sessions/logout", {});
    this.csrf = "";
  }
  async recordBehavior(
    event: "project_view" | "category_view",
    target: string,
  ) {
    // Analytics must never interrupt browsing or trigger an identity retry.
    try {
      await this.request("/customer/behaviors", { event, target }, false);
    } catch {
      /* Optional. */
    }
  }
  async current() {
    const session = await this.request<VisitorSession>(
      "/visitor-sessions/current",
    );
    this.csrf = session.csrf_token;
    return session;
  }
  async createSession(code: string) {
    const session = await this.request<{ csrf_token: string }>(
      "/visitor-sessions",
      { store_code: code },
    );
    this.csrf = session.csrf_token;
  }
  async threads(offset = 0) {
    return (
      await this.request<{ items: Thread[] }>(
        offset ? `/threads?offset=${offset}` : "/threads",
      )
    ).items;
  }
  async newThread() {
    return (await this.request<{ thread_id: string }>("/threads", {}))
      .thread_id;
  }
  async history(thread: string, offset = 0) {
    return (
      await this.request<{ items: HistoryMessage[] }>(
        `/threads/${encodeURIComponent(thread)}/messages?recent=true&limit=100&offset=${offset}`,
      )
    ).items;
  }
  send(thread: string, message: PendingMessage) {
    return this.request<Answer>(
      `/threads/${encodeURIComponent(thread)}/messages`,
      message,
    );
  }
  async projects() {
    return (await this.request<{ items: Project[] }>("/catalog/projects"))
      .items;
  }
  project(id: string) {
    return this.request<Project>(`/catalog/projects/${encodeURIComponent(id)}`);
  }
  booking(thread: string) {
    return this.request<BookingState>(
      `/threads/${encodeURIComponent(thread)}/booking`,
    );
  }
  consultation(thread: string, appointment: string) {
    return this.request<VisitCase | null>(
      `/threads/${encodeURIComponent(thread)}/appointments/${encodeURIComponent(appointment)}/consultation`,
    );
  }
  followups(thread: string, appointment: string) {
    return this.request<{ items: Followup[] }>(
      `/threads/${encodeURIComponent(thread)}/appointments/${encodeURIComponent(appointment)}/followups`,
    );
  }
  respondFollowup(
    thread: string,
    appointment: string,
    task: string,
    body: FollowupResponse,
  ) {
    return this.request<Followup>(
      `/threads/${encodeURIComponent(thread)}/appointments/${encodeURIComponent(appointment)}/followups/${encodeURIComponent(task)}/response`,
      body,
    );
  }
  decideConsultation(thread: string, appointment: string, body: CaseDecision) {
    return this.request<VisitCase>(
      `/threads/${encodeURIComponent(thread)}/appointments/${encodeURIComponent(appointment)}/consultation/decision`,
      body,
    );
  }
  createDraft(thread: string, body: CreateDraft) {
    return this.request<BookingDraft>(
      `/threads/${encodeURIComponent(thread)}/appointment-drafts`,
      body,
    );
  }
  sendCode(thread: string, draft: string, body: SendCode) {
    return this.request<Verification>(
      `/threads/${encodeURIComponent(thread)}/appointment-drafts/${encodeURIComponent(draft)}/verification`,
      body,
    );
  }
  verifyCode(thread: string, verification: string, body: { code: string }) {
    return this.request<Verification>(
      `/threads/${encodeURIComponent(thread)}/contact-verifications/${encodeURIComponent(verification)}/verify`,
      body,
    );
  }
  confirmDraft(thread: string, draft: string, body: ConfirmDraft) {
    return this.request<Appointment>(
      `/threads/${encodeURIComponent(thread)}/appointment-drafts/${encodeURIComponent(draft)}/confirm`,
      body,
    );
  }
  discardDraft(thread: string, draft: string) {
    return this.request<{ discarded: boolean }>(
      `/threads/${encodeURIComponent(thread)}/appointment-drafts/${encodeURIComponent(draft)}/discard`,
      {},
    );
  }
  cancelAppointment(thread: string, id: string, body: CancelAppointment) {
    return this.request<Appointment>(
      `/threads/${encodeURIComponent(thread)}/appointments/${encodeURIComponent(id)}/cancel`,
      body,
    );
  }
  respondChange(thread: string, id: string, body: RespondChange) {
    return this.request<Appointment>(
      `/threads/${encodeURIComponent(thread)}/appointments/${encodeURIComponent(id)}/change-response`,
      body,
    );
  }
}
const descriptions: Record<string, string> = {
  customer_login_required: "请先登录客户账号。",
  customer_already_logged_in: "当前身份已登录或已绑定，请刷新页面后重试。",
  customer_name_unavailable: "这个账号名暂不可用，请换一个。",
  binding_consent_required: "请确认将当前门店的匿名咨询记录绑定到你的账号。",
  memory_consent_required: "注册前请勾选允许保存咨询偏好。",
  invalid_credentials: "账号或密码不正确。",
  login_throttled: "尝试次数较多，请 15 分钟后再试。",
  followup_not_found: "回访计划不存在或不属于当前对话。",
  followup_state_conflict: "回访状态已变化，请刷新后重新审阅。",
  followup_source_changed: "咨询意向已变化，请由门店重新安排回访。",
  followup_plan_expired: "计划时间已过，请门店重新安排；您仍可拒绝邀请。",
  followup_snapshot_changed: "回访内容已变化，请刷新核实。",
  followup_author_unavailable: "回访人员的权限已变化，请联系门店核实。",
  followup_key_conflict: "原回访请求内容不一致，请核实，勿重复提交。",
  consultation_not_found: "到店咨询记录不存在或不属于当前对话。",
  consultation_state_conflict:
    "咨询记录已更新或已经回应，请刷新后审阅最新版本。",
  consultation_snapshot_changed: "咨询内容已改变，请重新审阅。",
  consultation_key_conflict: "确认内容与原请求不一致，请先核实记录。",
  consultation_author_unavailable: "记录人员的权限已变化，请联系门店重新核实。",
  appointment_state_conflict: "预约状态已变化，请刷新预约记录后重新审阅。",
  change_proposal_invalid: "改约提案已失效或被替换，请刷新核实最新时间。",
  change_proposer_unavailable:
    "提出改约的门店人员权限已变化，请联系门店重新核实。",
  appointment_not_found: "预约不存在或不属于当前对话。",
  appointment_time_invalid: "新时间已失效，请与门店重新沟通。",
  verification_not_configured: "联系方式核验尚未配置，请等待机构接入。",
  booking_policy_unavailable:
    "当前门店的预约政策尚未有效发布，暂不能提交申请。",
  booking_policy_changed: "预约政策已更新，请重新生成草稿、核验并确认。",
  booking_offer_changed: "咨询意愿已改变，请重新表达预约意愿后审阅新草稿。",
  draft_expired_or_replaced: "草稿已过期或被替换，请重新填写并核验。",
  draft_snapshot_changed: "预约草稿已改变，请重新审阅确认。",
  booking_time_invalid: "请选择 15 分钟之后、90 天以内的期望到店时间。",
  booking_intention_requires_human:
    "此意向包含需人工处理的信息，请仅填写公开咨询方向。",
  contact_verification_required: "请先核验这份草稿的联系方式。",
  verification_code_invalid: "验证码不正确，请核实后重新输入。",
  verification_expired_or_locked: "验证码已过期或达到尝试上限，请重新获取。",
  verification_rate_limited: "验证码请求过于频繁，请至少等待一分钟后再试。",
  verification_delivery_unknown:
    "上次短信发送结果未知，请先查看短信；本次不会重复发送。",
  customer_confirmation_required: "请审阅当前草稿并明确确认提交。",
  booking_already_submitted: "这次预约意愿已提交，请核实申请状态。",
  booking_key_conflict: "提交内容与原请求不一致，请核实最新记录。",
  booking_rate_limited: "预约草稿操作较频繁，请稍后再试。",
  unauthenticated: "咨询凭据已失效，当前会话已停止。请重新开始。",
  thread_not_found: "这段对话无法访问，请选择自己的对话或新建对话。",
  project_unavailable: "项目资料已更新、撤回或不属于当前门店，请重新查看目录。",
  store_unavailable: "当前门店暂不可用，请选择有效门店。",
  conversation_busy: "这条消息仍在处理，请稍后用原消息重试。",
  recovery_required: "上一条消息尚未恢复，请先核实并重试原消息。",
  conversation_rate_limited: "咨询频率较高，请稍后继续。",
  conversation_limit: "这段对话已达到消息上限，请新建对话。",
  request_timeout: "等待超时，结果可能仍在处理。请核实历史或重试原消息。",
  network_unavailable: "暂时无法连接咨询服务，请检查网络后重试。",
  database_unavailable: "数据服务暂不可用，请稍后核实。",
  origin_denied: "当前页面地址未获服务端授权。",
  no_public_store: "暂时没有可用的公开门店，请稍后再试。",
};
export function errorText(error: unknown): string {
  if (error instanceof ApiError)
    return `${descriptions[error.code] ?? "咨询暂未完成，请核实后重试。"}${error.requestId ? ` 请求编号：${error.requestId}` : ""}`;
  return "咨询暂未完成，请稍后重试。";
}
