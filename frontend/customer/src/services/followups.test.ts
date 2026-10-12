import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  FollowupReview,
  followupTexts,
  type CustomerFollowupApi,
  type Followup,
} from "./followups";
const row: Followup = {
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
};
function setup() {
  const api = {
    followups: vi
      .fn<CustomerFollowupApi["followups"]>()
      .mockResolvedValue({ items: [structuredClone(row)] }),
    respondFollowup: vi
      .fn<CustomerFollowupApi["respondFollowup"]>()
      .mockResolvedValue({ ...row, version: 2, state: "scheduled" }),
  };
  return { api, review: new FollowupReview(api) };
}
beforeEach(() =>
  vi.stubGlobal("crypto", { randomUUID: () => "test-request-key" }),
);
afterEach(() => vi.unstubAllGlobals());
describe("站内回访本人处理", () => {
  it("requires review and binds confirmation to this plan and version", async () => {
    const { api, review } = setup();
    await review.bind("thread", "appointment", "visitor");
    await review.respond(review.items[0]!, "accept", false);
    expect(api.respondFollowup).not.toHaveBeenCalled();
    await review.respond(review.items[0]!, "accept", true);
    expect(api.respondFollowup.mock.calls[0]![3]).toMatchObject({
      expected_version: 1,
      snapshot_hash: row.snapshot_hash,
      confirmation_text: followupTexts.accept,
    });
    expect(review.items[0]?.state).toBe("scheduled");
  });
  it("an unknown feedback result retains the original content despite reload", async () => {
    const { api, review } = setup();
    await review.bind("thread", "appointment", "visitor");
    api.respondFollowup.mockRejectedValueOnce(new ApiError("request_timeout"));
    await review.respond(
      review.items[0]!,
      "feedback",
      true,
      "need_help",
      "想继续了解流程",
    );
    api.followups.mockResolvedValue({
      items: [{ ...row, version: 4, state: "scheduled" }],
    });
    await review.load();
    await review.respond(review.items[0]!, "cancel", true);
    expect(api.respondFollowup).toHaveBeenCalledTimes(1);
    await review.retry();
    expect(api.respondFollowup.mock.calls[1]![3]).toEqual(
      api.respondFollowup.mock.calls[0]![3],
    );
    expect(api.respondFollowup.mock.calls[1]![3].feedback).toBe(
      "想继续了解流程",
    );
  });
  it("a denied scope clears pending feedback and old records", async () => {
    const { api, review } = setup();
    await review.bind("thread", "appointment", "visitor");
    api.respondFollowup.mockRejectedValueOnce(
      new ApiError("unauthenticated", 401),
    );
    await review.respond(review.items[0]!, "accept", true);
    expect(review.items).toEqual([]);
    expect(review.pending).toBeNull();
  });
  it("a late response cannot populate another visitor or thread", async () => {
    const { api, review } = setup();
    await review.bind("thread", "appointment", "visitor");
    let done!: (value: Followup) => void;
    api.respondFollowup.mockImplementationOnce(
      () => new Promise((resolve) => (done = resolve)),
    );
    const pending = review.respond(review.items[0]!, "accept", true);
    review.reset();
    await review.bind("other", "other-appointment", "other-visitor");
    done({ ...row, id: "late", version: 2 });
    await pending;
    expect(review.items[0]!.id).toBe("task");
    expect(review.pending).toBeNull();
  });
});
