export type Permission =
  | "knowledge_author"
  | "knowledge_review"
  | "knowledge_publish"
  | "appointment_read"
  | "appointment_manage"
  | "appointment_contact"
  | "customer_read"
  | "customer_manage";
export interface Store {
  id: string;
  name: string;
  simulated: boolean;
  permissions: Permission[];
}
export interface Profile {
  id: string;
  username: string;
  simulated: boolean;
  stores: Store[];
}
export interface Session {
  mode: "live" | "demo";
  token: string;
  profile: Profile;
}
export type KnowledgeStatus =
  | "draft"
  | "approved"
  | "rejected"
  | "publishing"
  | "published"
  | "withdrawn";
export interface Knowledge {
  id: string;
  knowledge_key: string;
  version: number;
  category: "operational" | "communication" | "medical";
  title: string;
  content: string;
  source: string;
  author_id: string;
  simulated: boolean;
  valid_until: string;
  created_at: string;
  status: KnowledgeStatus;
  review_reason?: string | null;
  projection_state?: string | null;
}
export interface KnowledgeInput {
  knowledge_key: string;
  category: Knowledge["category"];
  title: string;
  content: string;
  source: string;
  simulated: boolean;
  valid_until: string;
}
export type BookingStatus =
  | "pending_store_confirmation"
  | "confirmed"
  | "arrived"
  | "declined"
  | "cancelled";
export interface Booking {
  id: string;
  customer: string;
  intent: string;
  expected: string;
  confirmed: string;
  status: BookingStatus;
  source: string;
  events: string[];
}
export interface Customer {
  id: string;
  name: string;
  stage: string;
  initialIntent: string;
  currentIntent: string;
  history: { time: string; text: string }[];
}
export interface Project {
  id: string;
  title: string;
  category: string;
  introduction: string;
  active: boolean;
}
