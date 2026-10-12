import { request, errorText } from "./api";

export interface DemoMaterialsPack {
  pack_id: string;
  title: string;
  version: string;
  simulated: true;
  disclosure: string;
  created_on: string;
  valid_until: string;
  rag_status: "presentation_only_not_published";
  institution: { name: string; actual_verification: string };
  store: {
    id: string;
    code: string;
    name: string;
    city: string;
    address: string;
    hours: string;
    rooms: number;
    area_m2: number;
    manager: string;
    contact: string;
    daily_consultation_capacity: number;
    capacity_note: string;
  };
  personnel: Array<{
    id: string;
    name: string;
    role: string;
    experience_setting: string;
    shift: string;
    specialty: string;
    qualification_status: string;
  }>;
  services: Array<{
    id: string;
    name: string;
    category: string;
    minutes: number;
    list_price_cny: number;
    demo_price_cny: number;
    unit: string;
    included: string;
    price_note: string;
    actual_supply_status: string;
  }>;
  policies: Array<{ id: string; title: string; content: string; flow: string }>;
  suppliers: Array<{
    id: string;
    name: string;
    kind: string;
    scope: string;
    integration: string;
    actual_status: string;
    required: string[];
  }>;
  review_records: Array<{
    id: string;
    supplier_id: string;
    prepared_by: string;
    reviewed_by: string;
    reviewed_at: string;
    demo_result: string;
    actual_result: string;
    evidence_reference: string;
    evidence_type: string;
  }>;
  scripts: Array<{
    id: string;
    topic: string;
    customer_question: string;
    suggested_reply: string;
  }>;
  journeys: Array<{
    id: string;
    title: string;
    customer_alias: string;
    steps: string[];
    expected: string;
    record_type: string;
  }>;
}
export type DemoMaterialsReader = (
  store: string,
  token: string,
) => Promise<DemoMaterialsPack>;
export const readDemoMaterials: DemoMaterialsReader = (store, token) =>
  request(`/stores/${encodeURIComponent(store)}/demo-materials`, { token });

export class DemoMaterialsView {
  pack: DemoMaterialsPack | null = null;
  error = "";
  busy = false;
  private store = "";
  private token = "";
  private epoch = 0;
  constructor(private read: DemoMaterialsReader = readDemoMaterials) {}
  bind(store: string, token: string) {
    this.epoch++;
    this.store = store;
    this.token = token;
    this.pack = null;
    this.error = "";
    this.busy = false;
  }
  async load() {
    if (!this.store || !this.token || this.busy) return;
    const epoch = this.epoch;
    this.busy = true;
    this.pack = null;
    this.error = "";
    try {
      const pack = await this.read(this.store, this.token);
      if (epoch === this.epoch) this.pack = pack;
    } catch (error) {
      if (epoch === this.epoch) this.error = errorText(error);
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
}
