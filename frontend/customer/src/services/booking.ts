import { ApiError, errorText } from "./api";
import type { CustomerCaseApi } from "./cases";
import type { CustomerFollowupApi } from "./followups";

export const confirmationText = "确认提交预约申请，等待门店确认";
export const cancelText = "确认取消本次预约";
export const acceptChangeText = "确认接受新的到店时间";
export const rejectChangeText = "保留原安排，拒绝此次改约";
export interface ChangeProposal {
  id: string;
  version: number;
  snapshot_hash: string;
  proposed_at: string;
  expires_at: string;
}
export interface CancelAppointment {
  request_key: string;
  expected_version: number;
  accepted: boolean;
  confirmation_text: string;
}
export interface RespondChange extends CancelAppointment {
  proposal_id: string;
  snapshot_hash: string;
  decision: "accept" | "reject";
}
export interface BookingDraft {
  id: string;
  request_key: string;
  snapshot_hash: string;
  name: string;
  phone_masked: string;
  intention: string;
  desired_at: string;
  project_title: string | null;
  store_name: string;
  expires_at: string;
  status: string;
  simulated: boolean;
  trigger_run_id: string;
  policy: {
    id: string;
    title: string;
    version: number;
    content: string;
    source: string;
    simulated: boolean;
  };
}
export interface Verification {
  id: string;
  request_key: string;
  draft_id: string;
  delivery_state: "sent" | "unknown" | "rejected";
  expires_at: string;
  verified: boolean;
  simulated: boolean;
  attempts_remaining: number;
  simulated_code?: string;
}
export interface Appointment {
  change_proposal?: ChangeProposal | null;
  arrived_at?: string | null;
  version?: number;
  confirmed_at?: string | null;
  decision_reason?: string | null;
  id: string;
  request_key: string;
  state: string;
  simulated: boolean;
  created_at: string;
  name: string;
  phone_masked: string;
  desired_at: string;
  intention: string;
  project_title: string | null;
  store_name: string;
}
export interface BookingState {
  configured: boolean;
  simulated_verification?: boolean;
  trigger_run_id: string | null;
  draft: BookingDraft | null;
  verification: Verification | null;
  appointments: Appointment[];
  blocked_reason: string;
}
export interface DraftForm {
  name: string;
  phone: string;
  desired_at: string;
  intention: string;
  project_version_id: string | null;
}
export interface CreateDraft extends DraftForm {
  request_key: string;
  trigger_run_id: string;
}
export interface SendCode {
  request_key: string;
  sms_consent: boolean;
}
export interface ConfirmDraft {
  request_key: string;
  snapshot_hash: string;
  verification_id: string;
  accepted: boolean;
  confirmation_text: string;
}
export interface BookingApi extends CustomerCaseApi, CustomerFollowupApi {
  booking(thread: string): Promise<BookingState>;
  createDraft(thread: string, body: CreateDraft): Promise<BookingDraft>;
  sendCode(
    thread: string,
    draft: string,
    body: SendCode,
  ): Promise<Verification>;
  verifyCode(
    thread: string,
    verification: string,
    body: { code: string },
  ): Promise<Verification>;
  confirmDraft(
    thread: string,
    draft: string,
    body: ConfirmDraft,
  ): Promise<Appointment>;
  discardDraft(thread: string, draft: string): Promise<{ discarded: boolean }>;
  cancelAppointment(
    thread: string,
    id: string,
    body: CancelAppointment,
  ): Promise<Appointment>;
  respondChange(
    thread: string,
    id: string,
    body: RespondChange,
  ): Promise<Appointment>;
}
type Operation =
  | { kind: "draft"; thread: string; body: CreateDraft }
  | { kind: "sms"; thread: string; draft: string; body: SendCode }
  | {
      kind: "verify";
      thread: string;
      verification: string;
      body: { code: string };
    }
  | { kind: "confirm"; thread: string; draft: string; body: ConfirmDraft }
  | { kind: "discard"; thread: string; draft: string }
  | { kind: "cancel"; thread: string; id: string; body: CancelAppointment }
  | { kind: "respond"; thread: string; id: string; body: RespondChange };

export class Booking {
  state: BookingState | null = null;
  busy = false;
  loading = false;
  editing = false;
  error = "";
  pending: Operation | null = null;
  private scope = "";
  private thread = "";
  private epoch = 0;
  constructor(private api: BookingApi) {}
  reset() {
    this.epoch++;
    this.scope = "";
    this.thread = "";
    this.state = null;
    this.pending = null;
    this.error = "";
    this.editing = false;
    this.loading = this.busy = false;
  }
  async bind(thread: string, visitor: string) {
    const scope = `${visitor}/${thread}`;
    if (scope !== this.scope) {
      this.reset();
      this.scope = scope;
      this.thread = thread;
    }
    if (this.busy || this.loading || !thread || !visitor) return;
    await this.reload();
  }
  private failed(error: unknown) {
    this.error = errorText(error);
    if (
      error instanceof ApiError &&
      (error.status === 401 ||
        error.code === "thread_not_found" ||
        error.code === "store_unavailable")
    ) {
      this.state = null;
      this.pending = null;
      this.editing = false;
    }
  }
  async reload() {
    if (!this.thread || this.loading) return;
    const epoch = this.epoch;
    this.loading = true;
    try {
      const state = await this.api.booking(this.thread);
      if (epoch !== this.epoch) return;
      this.state = state;
      const op = this.pending;
      if (
        op &&
        ((op.kind === "draft" &&
          state.draft?.request_key === op.body.request_key) ||
          (op.kind === "sms" &&
            state.verification?.request_key === op.body.request_key) ||
          (op.kind === "confirm" &&
            state.appointments.some(
              (row) => row.request_key === op.body.request_key,
            )) ||
          (op.kind === "verify" &&
            state.verification?.id === op.verification &&
            state.verification.verified) ||
          (op.kind === "discard" && !state.draft))
      ) {
        this.pending = null;
        this.error = "";
        this.editing = false;
      }
    } catch (error) {
      if (epoch === this.epoch) {
        this.state = null;
        this.failed(error);
      }
    } finally {
      if (epoch === this.epoch) this.loading = false;
    }
  }
  private async execute(op: Operation) {
    if (this.busy || this.loading) return;
    const epoch = this.epoch;
    this.pending = op;
    this.busy = true;
    this.error = "";
    try {
      switch (op.kind) {
        case "draft":
          await this.api.createDraft(op.thread, op.body);
          break;
        case "sms":
          await this.api.sendCode(op.thread, op.draft, op.body);
          break;
        case "verify":
          await this.api.verifyCode(op.thread, op.verification, op.body);
          break;
        case "confirm":
          await this.api.confirmDraft(op.thread, op.draft, op.body);
          break;
        case "discard":
          await this.api.discardDraft(op.thread, op.draft);
          break;
        case "cancel":
          await this.api.cancelAppointment(op.thread, op.id, op.body);
          break;
        case "respond":
          await this.api.respondChange(op.thread, op.id, op.body);
          break;
      }
      if (epoch !== this.epoch) return;
      this.pending = null;
      this.editing = false;
      await this.reload();
    } catch (error) {
      if (epoch !== this.epoch) return;
      if (error instanceof ApiError && error.status > 0 && error.status < 500)
        this.pending = null;
      this.failed(error);
      // Unknown writes retain their original body/key. Refresh may reconcile a committed result.
      await this.reload();
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  async retry() {
    if (this.pending) await this.execute(this.pending);
  }
  async cancel(id: string, accepted: boolean) {
    const row = this.state?.appointments.find((x) => x.id === id);
    if (
      this.pending ||
      !accepted ||
      !row?.version ||
      !["pending_store_confirmation", "confirmed"].includes(row.state)
    )
      return;
    await this.execute({
      kind: "cancel",
      thread: this.thread,
      id,
      body: {
        request_key: crypto.randomUUID(),
        expected_version: row.version,
        accepted,
        confirmation_text: cancelText,
      },
    });
  }
  async respond(id: string, decision: "accept" | "reject", accepted: boolean) {
    const row = this.state?.appointments.find((x) => x.id === id);
    const proposal = row?.change_proposal;
    if (
      this.pending ||
      !accepted ||
      !row?.version ||
      !proposal ||
      new Date(proposal.expires_at).getTime() <= Date.now()
    )
      return;
    await this.execute({
      kind: "respond",
      thread: this.thread,
      id,
      body: {
        request_key: crypto.randomUUID(),
        expected_version: row.version,
        accepted,
        proposal_id: proposal.id,
        snapshot_hash: proposal.snapshot_hash,
        decision,
        confirmation_text:
          decision === "accept" ? acceptChangeText : rejectChangeText,
      },
    });
  }
  async save(form: DraftForm) {
    if (this.pending || !this.state?.configured || !this.state.trigger_run_id)
      return;
    await this.execute({
      kind: "draft",
      thread: this.thread,
      body: {
        ...form,
        request_key: crypto.randomUUID(),
        trigger_run_id: this.state.trigger_run_id,
      },
    });
  }
  async send(consent: boolean) {
    if (
      this.pending ||
      !this.state?.draft ||
      this.state.blocked_reason ||
      !consent
    )
      return;
    await this.execute({
      kind: "sms",
      thread: this.thread,
      draft: this.state.draft.id,
      body: { request_key: crypto.randomUUID(), sms_consent: consent },
    });
  }
  async verify(code: string) {
    if (this.pending || !this.state?.verification || this.state.blocked_reason)
      return;
    await this.execute({
      kind: "verify",
      thread: this.thread,
      verification: this.state.verification.id,
      body: { code },
    });
  }
  async confirm(accepted: boolean) {
    const state = this.state;
    if (
      this.pending ||
      !state?.draft ||
      !state.verification?.verified ||
      state.blocked_reason ||
      !accepted
    )
      return;
    await this.execute({
      kind: "confirm",
      thread: this.thread,
      draft: state.draft.id,
      body: {
        request_key: crypto.randomUUID(),
        snapshot_hash: state.draft.snapshot_hash,
        verification_id: state.verification.id,
        accepted,
        confirmation_text: confirmationText,
      },
    });
  }
  async discard() {
    if (this.pending || !this.state?.draft) return;
    await this.execute({
      kind: "discard",
      thread: this.thread,
      draft: this.state.draft.id,
    });
  }
}
