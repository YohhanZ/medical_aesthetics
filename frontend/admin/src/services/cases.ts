import { ApiError, errorText, request } from "./api";
import { appointmentApi, type StoreAppointment } from "./appointments";
import type { VisitCase } from "../../../customer/src/services/cases";
export type { VisitCase };
export interface CaseForm {
  name: string;
  intention: string;
  reason: string;
  project_version_id: string | null;
}
export interface CreateCase {
  request_key: string;
  accepted: boolean;
  appointment_id: string;
  expected_appointment_version: number;
}
export interface ReviseCase extends CaseForm {
  request_key: string;
  accepted: boolean;
  expected_version: number;
}
export interface CaseApi {
  list(
    store: string,
    token: string,
    offset: number,
  ): Promise<{ items: VisitCase[]; total: number }>;
  detail(store: string, token: string, id: string): Promise<VisitCase>;
  arrivals(
    store: string,
    token: string,
    offset: number,
  ): Promise<{ items: StoreAppointment[]; total: number }>;
  options(
    store: string,
    token: string,
  ): Promise<{ items: { id: string; title: string; simulated: boolean }[] }>;
  create(store: string, token: string, body: CreateCase): Promise<VisitCase>;
  revise(
    store: string,
    token: string,
    id: string,
    body: ReviseCase,
  ): Promise<VisitCase>;
}
export const caseApi: CaseApi = {
  list: (store, token, offset) =>
    request(`/stores/${store}/consultations?limit=25&offset=${offset}`, {
      token,
    }),
  detail: (store, token, id) =>
    request(`/stores/${store}/consultations/${id}`, { token }),
  arrivals: (store, token, offset) =>
    appointmentApi.list(store, token, "arrived", offset),
  options: (store, token) =>
    request(`/stores/${store}/consultation-options`, { token }),
  create: (store, token, body) =>
    request(`/stores/${store}/consultations`, { token, method: "POST", body }),
  revise: (store, token, id, body) =>
    request(`/stores/${store}/consultations/${id}/revisions`, {
      token,
      method: "POST",
      body,
    }),
};
type Operation =
  | { kind: "create"; body: CreateCase }
  | { kind: "revise"; id: string; body: ReviseCase };
export class CaseInbox {
  store = "";
  token = "";
  busy = false;
  error = "";
  epoch = 0;
  items: VisitCase[] = [];
  total = 0;
  arrivals: StoreAppointment[] = [];
  arrivalTotal = 0;
  options: { id: string; title: string; simulated: boolean }[] = [];
  selected: VisitCase | null = null;
  pending: Operation | null = null;
  constructor(private api: CaseApi) {}
  bind(store: string, token: string) {
    this.epoch++;
    this.store = store;
    this.token = token;
    this.busy = false;
    this.error = "";
    this.items = [];
    this.total = 0;
    this.arrivals = [];
    this.arrivalTotal = 0;
    this.options = [];
    this.selected = null;
    this.pending = null;
  }
  private failed(error: unknown) {
    this.error = errorText(error);
    this.selected = null;
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      this.items = [];
      this.total = 0;
      this.arrivals = [];
      this.arrivalTotal = 0;
      this.options = [];
      this.pending = null;
    }
  }
  async load(offset = 0, arrivalsOffset = 0, includeArrivals = false) {
    if (this.busy || !this.token || !this.store) return;
    const epoch = this.epoch,
      id = this.selected?.id;
    this.busy = true;
    this.error = "";
    this.items = [];
    this.total = 0;
    this.arrivals = [];
    this.arrivalTotal = 0;
    this.selected = null;
    this.options = [];
    try {
      const [cases, options, arrivals] = await Promise.all([
        this.api.list(this.store, this.token, offset),
        this.api.options(this.store, this.token),
        includeArrivals
          ? this.api.arrivals(this.store, this.token, arrivalsOffset)
          : Promise.resolve({ items: [], total: 0 }),
      ]);
      if (epoch !== this.epoch) return;
      this.items = cases.items;
      this.total = cases.total;
      this.arrivals = arrivals.items;
      this.arrivalTotal = arrivals.total;
      this.options = options.items;
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
  async create(row: StoreAppointment, accepted: boolean) {
    if (this.busy || this.pending || !accepted || row.state !== "arrived")
      return;
    this.pending = {
      kind: "create",
      body: {
        request_key: crypto.randomUUID(),
        accepted,
        appointment_id: row.id,
        expected_appointment_version: row.version,
      },
    };
    await this.retry();
  }
  async revise(form: CaseForm, accepted: boolean) {
    if (this.busy || this.pending || !accepted || !this.selected) return;
    this.pending = {
      kind: "revise",
      id: this.selected.id,
      body: {
        ...form,
        request_key: crypto.randomUUID(),
        accepted,
        expected_version: this.selected.version,
      },
    };
    await this.retry();
  }
  async retry() {
    if (this.busy || !this.pending) return;
    const op = this.pending,
      epoch = this.epoch;
    this.busy = true;
    this.error = "";
    try {
      const row =
        op.kind === "create"
          ? await this.api.create(this.store, this.token, { ...op.body })
          : await this.api.revise(this.store, this.token, op.id, {
              ...op.body,
            });
      if (epoch === this.epoch) {
        this.selected = row;
        this.pending = null;
        if (this.items.some((x) => x.id === row.id))
          this.items = this.items.map((x) => (x.id === row.id ? row : x));
        else {
          this.items = [];
          this.total = 0;
        } // A new record requires authoritative pagination refresh.
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
