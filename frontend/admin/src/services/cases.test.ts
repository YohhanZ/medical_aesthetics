import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { CaseInbox, type CaseApi, type VisitCase } from "./cases";
const row: VisitCase = {
  id: "case",
  appointment_id: "appointment",
  version: 1,
  simulated: true,
  initial: { name: "访客", intention: "项目未定", project_title: null },
  phone_masked: "199****0001",
  current: {
    version: 1,
    name: "访客",
    intention: "项目未定",
    reason: "初次申请",
    source: "original_application",
    project_version_id: null,
    project_title: null,
    snapshot_hash: "a".repeat(64),
    decision: null,
    confirmed_at: null,
    recorded_at: "2026-10-11T12:00:00Z",
  },
  history: [],
};
const form = {
  name: "合成访客",
  intention: "护理咨询",
  reason: "客户继续了解",
  project_version_id: null,
};
function setup() {
  const api = {
    list: vi
      .fn<CaseApi["list"]>()
      .mockResolvedValue({ items: [row], total: 1 }),
    detail: vi.fn<CaseApi["detail"]>().mockResolvedValue(structuredClone(row)),
    arrivals: vi
      .fn<CaseApi["arrivals"]>()
      .mockResolvedValue({ items: [], total: 0 }),
    options: vi.fn<CaseApi["options"]>().mockResolvedValue({ items: [] }),
    create: vi.fn<CaseApi["create"]>().mockResolvedValue(row),
    revise: vi
      .fn<CaseApi["revise"]>()
      .mockResolvedValue({
        ...row,
        version: 2,
        current: { ...row.current, ...form, version: 2 },
      }),
  };
  const inbox = new CaseInbox(api);
  inbox.bind("store-a", "token-a");
  return { api, inbox };
}
beforeEach(() =>
  vi.stubGlobal("crypto", { randomUUID: () => "synthetic-key" }),
);
describe("到店咨询档案", () => {
  it("requires explicit staff action and preserves unknown content across form changes", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    await inbox.revise(form, false);
    expect(api.revise).not.toHaveBeenCalled();
    api.revise.mockRejectedValueOnce(new ApiError("request_timeout"));
    const mutable = { ...form };
    await inbox.revise(mutable, true);
    mutable.intention = "改成另一个意向";
    await inbox.open(row.id);
    await inbox.revise(mutable, true);
    expect(api.revise).toHaveBeenCalledTimes(1);
    await inbox.retry();
    expect(api.revise.mock.calls[1][3]).toEqual(api.revise.mock.calls[0][3]);
    expect(api.revise.mock.calls[1][3].intention).toBe(form.intention);
  });
  it("does not request appointment data for a case-only reader", async () => {
    const { api, inbox } = setup();
    await inbox.load();
    expect(api.arrivals).not.toHaveBeenCalled();
    expect(inbox.items).toHaveLength(1);
  });
  it("permission revocation clears case data and pending changes", async () => {
    const { api, inbox } = setup();
    await inbox.load();
    await inbox.open(row.id);
    api.revise.mockRejectedValueOnce(
      new ApiError("store_permission_denied", "", 403),
    );
    await inbox.revise(form, true);
    expect(inbox.items).toEqual([]);
    expect(inbox.pending).toBeNull();
    expect(inbox.selected).toBeNull();
  });
  it("late edits cannot restore another store's case", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    let resolve!: (row: VisitCase) => void;
    api.revise.mockImplementationOnce(
      () => new Promise((done) => (resolve = done)),
    );
    const pending = inbox.revise(form, true);
    inbox.bind("store-b", "token-b");
    resolve(row);
    await pending;
    expect(inbox.selected).toBeNull();
    expect(inbox.items).toEqual([]);
    expect(inbox.pending).toBeNull();
  });
});
