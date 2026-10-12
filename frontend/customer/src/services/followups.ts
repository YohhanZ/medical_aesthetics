import { ApiError, errorText } from "./api";
export const followupTexts = {
  accept: "同意本次站内回访计划",
  reject: "拒绝回访并暂停这份档案的邀请",
  cancel: "取消回访并暂停这份档案的邀请",
  feedback: "确认提交本次回访反馈",
  resume: "恢复这份档案的站内回访邀请",
} as const;
export type FollowupAction = keyof typeof followupTexts;
export type FollowupState =
  | "awaiting_confirmation"
  | "scheduled"
  | "completed"
  | "declined"
  | "cancelled";
export const followupLabels: Record<FollowupState, string> = {
  awaiting_confirmation: "等待客户同意",
  scheduled: "客户已同意计划",
  completed: "客户反馈已保存",
  declined: "客户已拒绝",
  cancelled: "计划已取消",
};
export interface Followup {
  id: string;
  case_id: string;
  case_version: number;
  source_current: boolean;
  version: number;
  state: FollowupState;
  due_at: string;
  message: string;
  snapshot_hash: string;
  opted_out: boolean;
  simulated: boolean;
  channel: "in_app";
  history: {
    version: number;
    kind: string;
    actor_kind: string;
    recorded_at: string;
    text: string;
    result: "resolved" | "need_help" | null;
    feedback: string;
    confirmation_text: string;
  }[];
}
export interface FollowupResponse {
  request_key: string;
  expected_version: number;
  accepted: boolean;
  snapshot_hash: string;
  action: FollowupAction;
  confirmation_text: string;
  result: "resolved" | "need_help" | null;
  feedback: string;
}
export interface CustomerFollowupApi {
  followups(
    thread: string,
    appointment: string,
  ): Promise<{ items: Followup[] }>;
  respondFollowup(
    thread: string,
    appointment: string,
    task: string,
    body: FollowupResponse,
  ): Promise<Followup>;
}
export class FollowupReview {
  items: Followup[] = [];
  busy = false;
  error = "";
  pending: { id: string; body: FollowupResponse } | null = null;
  private scope = "";
  private thread = "";
  private appointment = "";
  private epoch = 0;
  constructor(private api: CustomerFollowupApi) {}
  reset() {
    this.epoch++;
    this.scope = this.thread = this.appointment = "";
    this.items = [];
    this.pending = null;
    this.busy = false;
    this.error = "";
  }
  async bind(thread: string, appointment: string, visitor: string) {
    const scope = `${visitor}/${thread}/${appointment}`;
    if (scope !== this.scope) {
      this.reset();
      this.scope = scope;
      this.thread = thread;
      this.appointment = appointment;
    }
    await this.load();
  }
  private failed(error: unknown) {
    this.error = errorText(error);
    this.items = [];
    if (error instanceof ApiError && [401, 403, 404].includes(error.status))
      this.pending = null;
  }
  async load() {
    if (this.busy || !this.thread) return;
    const epoch = this.epoch;
    this.busy = true;
    this.error = "";
    this.items = [];
    try {
      const result = await this.api.followups(this.thread, this.appointment);
      if (epoch === this.epoch) this.items = result.items;
    } catch (error) {
      if (epoch === this.epoch) this.failed(error);
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  async respond(
    row: Followup,
    action: FollowupAction,
    accepted: boolean,
    result: "resolved" | "need_help" | null = null,
    feedback = "",
  ) {
    if (
      this.busy ||
      this.pending ||
      !accepted ||
      !this.items.some((x) => x.id === row.id && x.version === row.version)
    )
      return;
    this.pending = {
      id: row.id,
      body: {
        request_key: crypto.randomUUID(),
        expected_version: row.version,
        snapshot_hash: row.snapshot_hash,
        action,
        accepted,
        confirmation_text: followupTexts[action],
        result,
        feedback,
      },
    };
    await this.retry();
  }
  async retry() {
    if (this.busy || !this.pending) return;
    const epoch = this.epoch,
      op = this.pending;
    this.busy = true;
    this.error = "";
    try {
      const row = await this.api.respondFollowup(
        this.thread,
        this.appointment,
        op.id,
        { ...op.body },
      );
      if (epoch === this.epoch) {
        this.items = this.items.some((x) => x.id === row.id)
          ? this.items.map((x) => (x.id === row.id ? row : x))
          : [row];
        this.pending = null;
      }
    } catch (error) {
      if (epoch === this.epoch) {
        if (error instanceof ApiError && error.status > 0 && error.status < 500)
          this.pending = null;
        this.failed(error);
      }
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
}
