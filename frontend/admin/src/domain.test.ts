import { afterEach, describe, expect, it, vi } from "vitest";
import {
  can,
  clearSession,
  currentStore,
  demoAvailable,
  session,
  setSession,
  storeId,
} from "./state";
import { request } from "./services/api";
import { demoProfile, transitionBooking } from "./services/demo";
import { actionAllowed } from "./services/knowledge";
import type { Booking, Knowledge } from "./types";

afterEach(() => {
  clearSession();
  vi.unstubAllGlobals();
});
const booking = (): Booking => ({
  id: "synthetic-test",
  customer: "合成客户",
  intent: "项目未定",
  expected: "2030-01-01 14:00",
  confirmed: "",
  status: "pending_store_confirmation",
  source: "合成",
  events: [],
});
const knowledge = (changes: Partial<Knowledge> = {}): Knowledge => ({
  id: "synthetic-test",
  knowledge_key: "test",
  version: 1,
  category: "operational",
  title: "合成资料",
  content: "测试",
  source: "合成",
  author_id: "author",
  simulated: true,
  valid_until: "2099-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  status: "draft",
  ...changes,
});

describe("前端权限和演练边界", () => {
  it("生产不开放演练入口", () => {
    expect(demoAvailable(false)).toBe(false);
    expect(demoAvailable(true)).toBe(true);
  });
  it("没有明确授权门店时不授予知识能力", () => {
    setSession({
      mode: "live",
      token: "synthetic",
      profile: {
        id: "admin",
        username: "平台管理员",
        simulated: true,
        stores: [],
      },
    });
    expect(currentStore.value).toBeUndefined();
    expect(can("knowledge_publish")).toBe(false);
  });
  it("切换到非授权门店不能获得能力", () => {
    setSession({ mode: "demo", token: "", profile: demoProfile });
    expect(can("knowledge_review")).toBe(true);
    storeId.value = "not-granted";
    expect(can("knowledge_review")).toBe(false);
  });
  it("演练不能发送真实 API 请求", async () => {
    setSession({ mode: "demo", token: "", profile: demoProfile });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(request("/staff/me")).rejects.toThrow(
      "demo_cannot_call_live_api",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it("真实登录过期时清理内存凭据", async () => {
    setSession({ mode: "live", token: "synthetic", profile: demoProfile });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          status: 401,
          json: async () => ({ code: "unauthenticated" }),
        }),
    );
    await expect(request("/staff/me")).rejects.toThrow("unauthenticated");
    expect(session.value).toBeNull();
    expect(storeId.value).toBe("");
  });
});
describe("预约状态与明确核实", () => {
  it("未核实不能确认申请", () => {
    const row = booking();
    expect(() =>
      transitionBooking(row, "confirm", row.expected, false),
    ).toThrow();
    expect(row.status).toBe("pending_store_confirmation");
  });
  it("核实后可确认并登记到店，但不能跳过确认", () => {
    const row = booking();
    expect(() => transitionBooking(row, "arrive", "", true)).toThrow();
    transitionBooking(row, "confirm", row.expected, true);
    expect(row.status).toBe("confirmed");
    expect(() => transitionBooking(row, "arrive", "", false)).toThrow();
    transitionBooking(row, "arrive", "", true);
    expect(row.status).toBe("arrived");
    expect(row.events).toHaveLength(2);
  });
  it("终态不能再次确认或拒绝", () => {
    const row = booking();
    transitionBooking(row, "decline", "", true);
    expect(() =>
      transitionBooking(row, "confirm", row.expected, true),
    ).toThrow();
    expect(() => transitionBooking(row, "decline", "", true)).toThrow();
  });
});
describe("知识审核动作", () => {
  it("作者不能通过或驳回自己的版本", () => {
    expect(actionAllowed(knowledge(), "approve", "author")).toBe(false);
    expect(actionAllowed(knowledge(), "reject", "author")).toBe(false);
  });
  it("医学占位不能模拟批准，但独立审核员可以驳回", () => {
    expect(
      actionAllowed(knowledge({ category: "medical" }), "approve", "reviewer"),
    ).toBe(false);
    expect(
      actionAllowed(knowledge({ category: "medical" }), "reject", "reviewer"),
    ).toBe(true);
  });
  it("未通过或过期不能发布", () => {
    expect(actionAllowed(knowledge(), "publish", "reviewer")).toBe(false);
    expect(
      actionAllowed(
        knowledge({ status: "approved", valid_until: "2020-01-01" }),
        "publish",
        "reviewer",
      ),
    ).toBe(false);
    expect(
      actionAllowed(knowledge({ status: "approved" }), "publish", "reviewer"),
    ).toBe(true);
  });
  it("撤回版本不能再次发布", () => {
    expect(
      actionAllowed(knowledge({ status: "withdrawn" }), "publish", "reviewer"),
    ).toBe(false);
  });
});
