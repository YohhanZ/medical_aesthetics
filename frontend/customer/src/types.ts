export interface Project {
  id: string;
  key: string;
  category: "care" | "medical";
  title: string;
  summary: string;
  description: string;
  topics: string[];
  image_url: string;
  image_alt: string;
  image_provenance: string;
  detail_url: string;
  source: string;
  version: number;
  simulated: boolean;
  valid_until: string;
}
export interface VisitorSession {
  visitor_id: string;
  store_id: string;
  store_code: string;
  store_name: string;
  simulated: boolean;
  csrf_token: string;
}
export interface PublicStore {
  code: string;
  name: string;
  simulated: boolean;
  city?: string;
  address?: string;
  latitude?: number | null;
  longitude?: number | null;
  coordinate_system?: "WGS84";
}
export interface Thread {
  thread_id: string;
  created_at: string;
  title?: string;
}
export interface Answer {
  message_id: string;
  run_id: string;
  thread_id: string;
  answer: string;
  public_answer?: string;
  intent: string;
  funnel_stage: string;
  mode: string;
  simulated?: boolean;
  disclosure?: string;
  projects: Project[];
  evidence: {
    id: string;
    title: string;
    source: string;
    version: number;
    simulated: boolean;
    review_scope?: "standard" | "demo_education";
  }[];
  handoff_reason: string;
  handoff: { ticket_id: string; status: string; connected: boolean } | null;
  action: { type: "visit_interest"; submitted: false } | null;
}
export interface HistoryMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  message_id: string;
  run_id: string;
  status: "running" | "failed" | "completed";
  result: Answer | null;
}
export interface Message {
  id: string;
  message_id: string;
  role: "user" | "assistant";
  text: string;
  result?: Answer;
  /** Presentation hint for a newly received reply; never persisted with history. */
  animate?: boolean;
}
export interface PendingMessage {
  message_id: string;
  question: string;
}
