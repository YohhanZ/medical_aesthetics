import { ApiError, errorText, request } from "./api";
import type {
  Followup,
  FollowupState,
} from "../../../customer/src/services/followups";
export type { FollowupState };
export interface StaffFollowup extends Followup {
  name: string;
  phone_masked: string;
}
export const followupLabels: Record<FollowupState, string> = {
  awaiting_confirmation: "等待客户同意",
  scheduled: "客户已同意计划",
  completed: "客户反馈已保存",
  declined: "客户已拒绝",
  cancelled: "计划已取消",
};
export interface Candidate {
  id: string;
  version: number;
  name: string;
  phone_masked: string;
}
export interface FollowupCreate {
  request_key: string;
  accepted: boolean;
  case_id: string;
  expected_case_version: number;
  due_at: string;
  message: string;
}
export interface StaffAction {
  request_key: string;
  accepted: boolean;
  expected_version: number;
  action: "note" | "cancel";
  note: string;
}
export interface FollowupApi {
  list(
    store: string,
    token: string,
    state: string,
    offset: number,
  ): Promise<{
    items: StaffFollowup[];
    total: number;
    counts: Partial<Record<FollowupState, number>>;
  }>;
  candidates(
    store: string,
    token: string,
    offset: number,
  ): Promise<{ items: Candidate[]; total: number }>;
  detail(store: string, token: string, id: string): Promise<StaffFollowup>;
  create(
    store: string,
    token: string,
    body: FollowupCreate,
  ): Promise<StaffFollowup>;
  act(
    store: string,
    token: string,
    id: string,
    body: StaffAction,
  ): Promise<StaffFollowup>;
}
export const followupApi: FollowupApi = {
  list: (store, token, state, offset) =>
    request(
      `/stores/${store}/followups?limit=25&offset=${offset}${state ? `&state=${encodeURIComponent(state)}` : ""}`,
      { token },
    ),
  candidates: (store, token, offset) =>
    request(`/stores/${store}/followup-cases?limit=25&offset=${offset}`, {
      token,
    }),
  detail: (store, token, id) =>
    request(`/stores/${store}/followups/${id}`, { token }),
  create: (store, token, body) =>
    request(`/stores/${store}/followups`, { token, method: "POST", body }),
  act: (store, token, id, body) =>
    request(`/stores/${store}/followups/${id}/actions`, {
      token,
      method: "POST",
      body,
    }),
};
type Operation =
  | { kind: "create"; body: FollowupCreate }
  | { kind: "act"; id: string; body: StaffAction };
export class FollowupInbox {
  store = "";
  token = "";
  busy = false;
  error = "";
  epoch = 0;
  items: StaffFollowup[] = [];
  total = 0;
  counts: Partial<Record<FollowupState, number>> = {};
  candidates: Candidate[] = [];
  candidateTotal = 0;
  selected: StaffFollowup | null = null;
  pending: Operation | null = null;
  constructor(private api: FollowupApi) {}
  bind(store: string, token: string) {
    this.epoch++;
    this.store = store;
    this.token = token;
    this.busy = false;
    this.error = "";
    this.items = [];
    this.total = 0;
    this.counts = {};
    this.candidates = [];
    this.candidateTotal = 0;
    this.selected = null;
    this.pending = null;
  }
  private failed(error: unknown) {
    this.error = errorText(error);
    this.selected = null;
    this.items = [];
    this.total = 0;
    this.counts = {};
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      this.items = [];
      this.total = 0;
      this.counts = {};
      this.candidates = [];
      this.candidateTotal = 0;
      this.pending = null;
    }
  }
  async load(state = "", offset = 0, candidateOffset = 0) {
    if (this.busy || !this.store || !this.token) return;
    const epoch = this.epoch,
      id = this.selected?.id;
    this.busy = true;
    this.error = "";
    this.items = [];
    this.counts = {};
    this.total = 0;
    this.selected = null;
    this.candidates = [];
    this.candidateTotal = 0;
    try {
      const [queue, candidates] = await Promise.all([
        this.api.list(this.store, this.token, state, offset),
        this.api.candidates(this.store, this.token, candidateOffset),
      ]);
      if (epoch !== this.epoch) return;
      this.items = queue.items;
      this.total = queue.total;
      this.counts = queue.counts;
      this.candidates = candidates.items;
      this.candidateTotal = candidates.total;
      if (id) {
        const row = await this.api.detail(this.store, this.token, id);
        if (epoch === this.epoch) this.selected = row;
      }
    } catch (error) {
      if (epoch === this.epoch) this.failed(error);
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  async open(id: string) {
    if (this.busy) return;
    const epoch = this.epoch;
    this.busy = true;
    this.selected = null;
    this.error = "";
    try {
      const row = await this.api.detail(this.store, this.token, id);
      if (epoch === this.epoch) this.selected = row;
    } catch (error) {
      if (epoch === this.epoch) this.failed(error);
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  close() {
    this.epoch++;
    this.selected = null;
    this.busy = false;
  }
  async create(
    candidate: Candidate,
    due_at: string,
    message: string,
    accepted: boolean,
  ) {
    if (this.busy || this.pending || !accepted) return;
    this.pending = {
      kind: "create",
      body: {
        request_key: crypto.randomUUID(),
        accepted,
        case_id: candidate.id,
        expected_case_version: candidate.version,
        due_at,
        message,
      },
    };
    await this.retry();
  }
  async act(action: "note" | "cancel", note: string, accepted: boolean) {
    if (this.busy || this.pending || !accepted || !this.selected) return;
    this.pending = {
      kind: "act",
      id: this.selected.id,
      body: {
        request_key: crypto.randomUUID(),
        accepted,
        expected_version: this.selected.version,
        action,
        note,
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
      const row =
        op.kind === "create"
          ? await this.api.create(this.store, this.token, { ...op.body })
          : await this.api.act(this.store, this.token, op.id, { ...op.body });
      if (epoch === this.epoch) {
        this.selected = row;
        this.pending = null;
        this.items = [];
        this.total = 0;
        this.counts = {};
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
