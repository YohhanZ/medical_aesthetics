import { ApiError, errorText, request } from "./api";

export interface StoreAppointment {
  arrived_at?: string | null;
  change_proposal?: {
    id: string;
    version: number;
    proposed_at: string;
    expires_at: string;
    snapshot_hash: string;
  } | null;
  id: string;
  version: number;
  state: string;
  simulated: boolean;
  name: string;
  phone_masked: string;
  intention: string;
  desired_at: string;
  confirmed_at: string | null;
  decision_reason: string | null;
  project_title: string | null;
  created_at: string;
  customer_confirmed_at: string;
  confirmation_method: string;
  events?: {
    event: string;
    occurred_at: string;
    version: number;
    reason: string | null;
  }[];
}
export interface Inbox {
  items: StoreAppointment[];
  total: number;
  counts: Record<string, number>;
}
export interface Decision {
  request_key: string;
  expected_version: number;
  action: "confirm" | "decline";
  accepted: boolean;
  availability_checked: boolean;
  reason: string | null;
}
export interface AppointmentApi {
  propose(
    store: string,
    token: string,
    id: string,
    body: Propose,
  ): Promise<StoreAppointment>;
  arrive(
    store: string,
    token: string,
    id: string,
    body: Arrival,
  ): Promise<StoreAppointment>;
  list(
    store: string,
    token: string,
    state: string,
    offset: number,
  ): Promise<Inbox>;
  detail(store: string, token: string, id: string): Promise<StoreAppointment>;
  decide(
    store: string,
    token: string,
    id: string,
    data: Decision,
  ): Promise<StoreAppointment>;
  contact(store: string, token: string, id: string): Promise<{ phone: string }>;
}
export interface Arrival {
  request_key: string;
  expected_version: number;
  accepted: boolean;
  identity_checked: boolean;
}
export interface Propose {
  request_key: string;
  expected_version: number;
  accepted: boolean;
  proposed_at: string;
  availability_checked: boolean;
}
type Operation =
  | { kind: "decision"; id: string; data: Decision }
  | { kind: "propose"; id: string; data: Propose }
  | { kind: "arrive"; id: string; data: Arrival };
export const appointmentApi: AppointmentApi = {
  propose: (store, token, id, body) =>
    request(`/stores/${store}/appointments/${id}/change-proposals`, {
      token,
      method: "POST",
      body,
    }),
  arrive: (store, token, id, body) =>
    request(`/stores/${store}/appointments/${id}/arrive`, {
      token,
      method: "POST",
      body,
    }),
  list: (store, token, state, offset) =>
    request(
      `/stores/${store}/appointments?limit=25&offset=${offset}${state ? `&state=${state}` : ""}`,
      { token },
    ),
  detail: (store, token, id) =>
    request(`/stores/${store}/appointments/${id}`, { token }),
  decide: (store, token, id, body) =>
    request(`/stores/${store}/appointments/${id}/decision`, {
      token,
      method: "POST",
      body,
    }),
  contact: (store, token, id) =>
    request(`/stores/${store}/appointments/${id}/contact`, {
      token,
      method: "POST",
    }),
};
export const appointmentLabels: Record<string, string> = {
  pending_store_confirmation: "待门店确认",
  confirmed: "门店已确认",
  declined: "门店未接受",
  arrived: "已到店",
  completed: "已完成",
  cancelled: "已取消",
  no_show: "未到店",
  change_proposed: "门店提出新时间",
  change_accepted: "客户接受新时间",
  change_rejected: "客户拒绝改约，保留原安排",
};
export const reasonLabels: Record<string, string> = {
  no_availability: "期望时间暂无接待安排",
  unable_to_contact: "暂未能联系确认",
  other: "门店暂无法接待，请进一步沟通",
};
export class AppointmentInbox {
  store = "";
  token = "";
  epoch = 0;
  busy = false;
  error = "";
  items: StoreAppointment[] = [];
  total = 0;
  counts: Record<string, number> = {};
  selected: StoreAppointment | null = null;
  phone = "";
  pending: Operation | null = null;
  constructor(private api: AppointmentApi) {}
  bind(store: string, token: string) {
    this.epoch++;
    this.store = store;
    this.token = token;
    this.busy = false;
    this.items = [];
    this.total = 0;
    this.counts = {};
    this.selected = null;
    this.phone = "";
    this.pending = null;
    this.error = "";
  }
  private failed(error: unknown) {
    this.error = errorText(error);
    if (
      error instanceof ApiError &&
      (error.status === 401 || error.code === "store_permission_denied")
    ) {
      this.items = [];
      this.selected = null;
      this.phone = "";
      this.pending = null;
      this.counts = {};
      this.total = 0;
    }
  }
  async load(state = "", offset = 0) {
    if (this.busy || !this.store || !this.token) return;
    const epoch = this.epoch;
    this.busy = true;
    this.error = "";
    const selectedId = this.selected?.id;
    this.items = [];
    this.counts = {};
    this.total = 0;
    this.phone = "";
    this.selected = null;
    try {
      const result = await this.api.list(this.store, this.token, state, offset);
      if (epoch === this.epoch) {
        this.items = result.items;
        this.total = result.total;
        this.counts = result.counts;
        if (selectedId) {
          const row = await this.api.detail(this.store, this.token, selectedId);
          if (epoch === this.epoch) this.selected = row;
        }
      }
    } catch (error) {
      if (epoch === this.epoch) {
        this.selected = null;
        this.failed(error);
      }
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  async open(id: string) {
    if (this.busy) return;
    const epoch = this.epoch;
    this.busy = true;
    this.error = "";
    this.selected = null;
    this.phone = "";
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
    this.busy = false;
    this.selected = null;
    this.phone = "";
  }
  async contact() {
    if (this.busy || !this.selected) return;
    const epoch = this.epoch,
      id = this.selected.id;
    this.busy = true;
    this.phone = "";
    try {
      const value = await this.api.contact(this.store, this.token, id);
      if (epoch === this.epoch && this.selected?.id === id)
        this.phone = value.phone;
    } catch (error) {
      if (epoch === this.epoch) this.failed(error);
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  async decide(
    action: Decision["action"],
    accepted: boolean,
    availability: boolean,
    reason: string,
  ) {
    if (
      this.busy ||
      this.pending ||
      !this.selected ||
      !accepted ||
      this.selected.state !== "pending_store_confirmation" ||
      !!this.selected.change_proposal ||
      (action === "confirm" && !availability) ||
      (action === "decline" && !reason)
    )
      return;
    this.pending = {
      kind: "decision",
      id: this.selected.id,
      data: {
        request_key: crypto.randomUUID(),
        expected_version: this.selected.version,
        action,
        accepted,
        availability_checked: action === "confirm" && availability,
        reason: action === "decline" ? reason : null,
      },
    };
    await this.retry();
  }
  async propose(time: string, availability: boolean, accepted: boolean) {
    const row = this.selected;
    if (
      this.busy ||
      this.pending ||
      !row ||
      !accepted ||
      !availability ||
      !["pending_store_confirmation", "confirmed"].includes(row.state)
    )
      return;
    const date = new Date(time);
    if (Number.isNaN(date.getTime())) {
      this.error = "请填写有效的新到店时间。";
      return;
    }
    this.pending = {
      kind: "propose",
      id: row.id,
      data: {
        request_key: crypto.randomUUID(),
        expected_version: row.version,
        accepted,
        proposed_at: date.toISOString(),
        availability_checked: availability,
      },
    };
    await this.retry();
  }
  async arrive(identity: boolean, accepted: boolean) {
    const row = this.selected;
    if (
      this.busy ||
      this.pending ||
      !row ||
      !accepted ||
      !identity ||
      row.state !== "confirmed" ||
      row.change_proposal
    )
      return;
    this.pending = {
      kind: "arrive",
      id: row.id,
      data: {
        request_key: crypto.randomUUID(),
        expected_version: row.version,
        accepted,
        identity_checked: identity,
      },
    };
    await this.retry();
  }
  async retry() {
    if (this.busy || !this.pending) return;
    const operation = this.pending,
      epoch = this.epoch;
    this.busy = true;
    this.error = "";
    this.phone = "";
    try {
      const row =
        operation.kind === "decision"
          ? await this.api.decide(this.store, this.token, operation.id, {
              ...operation.data,
            })
          : operation.kind === "propose"
            ? await this.api.propose(this.store, this.token, operation.id, {
                ...operation.data,
              })
            : await this.api.arrive(this.store, this.token, operation.id, {
                ...operation.data,
              });
      if (epoch === this.epoch) {
        this.selected = row;
        this.pending = null;
        this.items = this.items.map((x) => (x.id === row.id ? row : x));
      }
    } catch (error) {
      if (epoch === this.epoch) {
        if (error instanceof ApiError && error.status > 0 && error.status < 500)
          this.pending = null;
        this.selected = null;
        this.failed(error);
      }
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
}
