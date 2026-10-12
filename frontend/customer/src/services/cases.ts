import { ApiError, errorText } from "./api";
export const caseAcceptText = "确认本次咨询意向（不代表治疗或合同同意）";
export const caseRejectText = "暂不确认，继续沟通";
export interface CaseVersion {
  version: number;
  name: string;
  intention: string;
  reason: string;
  source: string;
  project_version_id: string | null;
  project_title: string | null;
  snapshot_hash: string;
  recorded_at: string;
  decision: "accept" | "reject" | null;
  confirmed_at: string | null;
}
export interface VisitCase {
  id: string;
  appointment_id: string;
  version: number;
  simulated: boolean;
  initial: { name: string; intention: string; project_title: string | null };
  phone_masked: string;
  current: CaseVersion;
  history: CaseVersion[];
}
export interface CaseDecision {
  request_key: string;
  expected_version: number;
  accepted: boolean;
  snapshot_hash: string;
  decision: "accept" | "reject";
  confirmation_text: string;
}
export interface CustomerCaseApi {
  consultation(thread: string, appointment: string): Promise<VisitCase | null>;
  decideConsultation(
    thread: string,
    appointment: string,
    body: CaseDecision,
  ): Promise<VisitCase>;
}
export class CaseReview {
  row: VisitCase | null = null;
  busy = false;
  error = "";
  pending: CaseDecision | null = null;
  private thread = "";
  private appointment = "";
  private scope = "";
  private epoch = 0;
  constructor(private api: CustomerCaseApi) {}
  reset() {
    this.epoch++;
    this.row = null;
    this.pending = null;
    this.busy = false;
    this.error = "";
    this.scope = this.thread = this.appointment = "";
  }
  async bind(thread: string, appointment: string, visitor: string) {
    const scope = `${visitor}/${thread}/${appointment}`;
    if (this.scope !== scope) {
      this.reset();
      this.scope = scope;
      this.thread = thread;
      this.appointment = appointment;
    }
    await this.load();
  }
  private failed(error: unknown) {
    this.error = errorText(error);
    this.row = null;
    if (error instanceof ApiError && [401, 403, 404].includes(error.status))
      this.pending = null;
  }
  async load() {
    if (this.busy || !this.thread) return;
    const epoch = this.epoch;
    this.busy = true;
    this.row = null;
    try {
      const row = await this.api.consultation(this.thread, this.appointment);
      if (epoch === this.epoch) this.row = row;
    } catch (error) {
      if (epoch === this.epoch) this.failed(error);
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  async decide(decision: "accept" | "reject", accepted: boolean) {
    if (
      this.busy ||
      this.pending ||
      !this.row ||
      this.row.current.decision ||
      !accepted
    )
      return;
    this.pending = {
      request_key: crypto.randomUUID(),
      expected_version: this.row.version,
      snapshot_hash: this.row.current.snapshot_hash,
      decision,
      accepted,
      confirmation_text:
        decision === "accept" ? caseAcceptText : caseRejectText,
    };
    await this.retry();
  }
  async retry() {
    if (this.busy || !this.pending) return;
    const epoch = this.epoch,
      body = { ...this.pending };
    this.busy = true;
    this.error = "";
    try {
      const row = await this.api.decideConsultation(
        this.thread,
        this.appointment,
        body,
      );
      if (epoch === this.epoch) {
        this.row = row;
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
