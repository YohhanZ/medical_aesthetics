import { isDemo, session, storeId } from "../state";
import type { Knowledge, KnowledgeInput } from "../types";
import { request } from "./api";
import { demoData } from "./demo";

export function actionAllowed(
  row: Knowledge,
  action: "approve" | "reject" | "publish" | "withdraw",
  staffId: string,
) {
  if (action === "approve" || action === "reject")
    return (
      row.status === "draft" &&
      row.author_id !== staffId &&
      (action !== "approve" || row.category !== "medical")
    );
  if (action === "publish")
    return (
      row.status === "approved" &&
      row.category !== "medical" &&
      new Date(row.valid_until) > new Date()
    );
  return row.status !== "withdrawn";
}
export async function listKnowledge(offset = 0) {
  if (isDemo.value) {
    const rows = demoData[storeId.value].knowledge;
    return { items: rows.slice(offset, offset + 50), total: rows.length };
  }
  return request<{ items: Knowledge[]; total: number }>(
    `/stores/${storeId.value}/knowledge?limit=50&offset=${offset}`,
  );
}
export async function createKnowledge(data: KnowledgeInput) {
  if (isDemo.value) {
    const rows = demoData[storeId.value].knowledge;
    const version =
      Math.max(
        0,
        ...rows
          .filter((r) => r.knowledge_key === data.knowledge_key)
          .map((r) => r.version),
      ) + 1;
    rows.unshift({
      ...data,
      simulated: true,
      id: `demo-${Date.now()}`,
      version,
      author_id: session.value!.profile.id,
      status: "draft",
      created_at: new Date().toISOString(),
    });
    return;
  }
  await request(`/stores/${storeId.value}/knowledge`, {
    method: "POST",
    body: data,
  });
}
export async function knowledgeAction(
  row: Knowledge,
  action: "approve" | "reject" | "publish" | "withdraw",
  reason: string,
) {
  if (!actionAllowed(row, action, session.value!.profile.id))
    throw new Error("当前版本不允许此操作，作者不能自审，医学内容需独立核验。");
  if (isDemo.value) {
    row.status = (
      {
        approve: "approved",
        reject: "rejected",
        publish: "publishing",
        withdraw: "withdrawn",
      } as const
    )[action];
    row.review_reason = reason;
    if (action === "publish") row.projection_state = "pending";
    return;
  }
  const review = action === "approve" || action === "reject";
  await request(
    `/stores/${storeId.value}/knowledge/${row.id}/${review ? "review" : action}`,
    {
      method: "POST",
      body: review ? { approved: action === "approve", reason } : undefined,
    },
  );
}
