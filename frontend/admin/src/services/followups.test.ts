import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  FollowupInbox,
  type FollowupApi,
  type StaffFollowup,
} from "./followups";
const row: StaffFollowup = {
  id: "task",
  case_id: "case",
  case_version: 2,
  source_current: true,
  version: 1,
  state: "awaiting_confirmation",
  due_at: "2099-11-01T02:00:00Z",
  message: "继续沟通",
  snapshot_hash: "a".repeat(64),
  opted_out: false,
  simulated: true,
  channel: "in_app",
  history: [],
  name: "合成访客",
  phone_masked: "199****0001",
};
const candidate = {
  id: "case",
  version: 2,
  name: row.name,
  phone_masked: row.phone_masked,
};
function setup() {
  const api = {
    list: vi
      .fn<FollowupApi["list"]>()
      .mockResolvedValue({
        items: [row],
        total: 1,
        counts: { awaiting_confirmation: 1 },
      }),
    candidates: vi
      .fn<FollowupApi["candidates"]>()
      .mockResolvedValue({ items: [candidate], total: 1 }),
    detail: vi.fn<FollowupApi["detail"]>().mockResolvedValue(row),
    create: vi.fn<FollowupApi["create"]>().mockResolvedValue(row),
    act: vi.fn<FollowupApi["act"]>().mockResolvedValue({ ...row, version: 2 }),
  };
  const inbox = new FollowupInbox(api);
  inbox.bind("store-a", "token-a");
  return { api, inbox };
}
beforeEach(() =>
  vi.stubGlobal("crypto", { randomUUID: () => "test-request-key" }),
);
afterEach(() => vi.unstubAllGlobals());
describe("门店回访记录", () => {
  it("requires explicit proposal and keeps the original source and due time on unknown results", async () => {
    const { api, inbox } = setup();
    await inbox.create(candidate, row.due_at, "原计划", false);
    expect(api.create).not.toHaveBeenCalled();
    api.create.mockRejectedValueOnce(new ApiError("request_timeout"));
    await inbox.create(candidate, row.due_at, "原计划", true);
    await inbox.load();
    await inbox.create(
      { ...candidate, version: 5 },
      "2099-12-01T02:00:00Z",
      "改后的说明",
      true,
    );
    expect(api.create).toHaveBeenCalledTimes(1);
    await inbox.retry();
    expect(api.create.mock.calls[1]![2]).toEqual(api.create.mock.calls[0]![2]);
  });
  it("an unknown internal note cannot be replaced with a cancellation", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    api.act.mockRejectedValueOnce(new ApiError("request_timeout"));
    await inbox.act("note", "原跟进记录", true);
    await inbox.open(row.id);
    await inbox.act("cancel", "新的取消原因", true);
    expect(api.act).toHaveBeenCalledTimes(1);
    await inbox.retry();
    expect(api.act.mock.calls[1]![3]).toEqual(api.act.mock.calls[0]![3]);
  });
  it("revoked access clears tasks, candidates and unfinished requests", async () => {
    const { api, inbox } = setup();
    await inbox.load();
    await inbox.open(row.id);
    api.act.mockRejectedValueOnce(
      new ApiError("store_permission_denied", "", 403),
    );
    await inbox.act("note", "内部记录", true);
    expect(inbox.items).toEqual([]);
    expect(inbox.candidates).toEqual([]);
    expect(inbox.pending).toBeNull();
  });
  it("late store results are discarded", async () => {
    const { api, inbox } = setup();
    let done!: (value: StaffFollowup) => void;
    api.create.mockImplementationOnce(
      () => new Promise((resolve) => (done = resolve)),
    );
    const pending = inbox.create(candidate, row.due_at, "原计划", true);
    inbox.bind("store-b", "token-b");
    done(row);
    await pending;
    expect(inbox.items).toEqual([]);
    expect(inbox.selected).toBeNull();
    expect(inbox.pending).toBeNull();
  });
});
