import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  CaseReview,
  caseAcceptText,
  type CustomerCaseApi,
  type VisitCase,
} from "./cases";
const row: VisitCase = {
  id: "case",
  appointment_id: "appointment",
  version: 2,
  simulated: true,
  initial: { name: "合成访客", intention: "项目未定", project_title: null },
  phone_masked: "199****0001",
  current: {
    version: 2,
    name: "合成访客",
    intention: "护理咨询",
    reason: "到店后沟通",
    source: "staff_record",
    project_version_id: null,
    project_title: null,
    snapshot_hash: "b".repeat(64),
    recorded_at: "2026-10-11T12:00:00Z",
    decision: null,
    confirmed_at: null,
  },
  history: [],
};
function setup() {
  const api = {
    consultation: vi
      .fn<CustomerCaseApi["consultation"]>()
      .mockResolvedValue(structuredClone(row)),
    decideConsultation: vi
      .fn<CustomerCaseApi["decideConsultation"]>()
      .mockResolvedValue({
        ...structuredClone(row),
        current: {
          ...row.current,
          decision: "accept",
          confirmed_at: "2026-10-11T13:00:00Z",
        },
      }),
  };
  return { api, review: new CaseReview(api) };
}
beforeEach(() =>
  vi.stubGlobal("crypto", { randomUUID: () => "synthetic-key" }),
);
describe("客户到店意向确认", () => {
  it("requires personal acknowledgement of the current immutable version", async () => {
    const { api, review } = setup();
    await review.bind("thread", "appointment", "visitor");
    await review.decide("accept", false);
    expect(api.decideConsultation).not.toHaveBeenCalled();
    await review.decide("accept", true);
    expect(api.decideConsultation.mock.calls[0][2]).toMatchObject({
      expected_version: 2,
      snapshot_hash: "b".repeat(64),
      confirmation_text: caseAcceptText,
    });
    await review.decide("reject", true);
    expect(api.decideConsultation).toHaveBeenCalledTimes(1);
  });
  it("unknown confirmation retries the original revision after a newer version arrives", async () => {
    const { api, review } = setup();
    await review.bind("thread", "appointment", "visitor");
    api.decideConsultation.mockRejectedValueOnce(
      new ApiError("network_unavailable"),
    );
    await review.decide("accept", true);
    const original = structuredClone(api.decideConsultation.mock.calls[0][2]);
    api.consultation.mockResolvedValueOnce({
      ...structuredClone(row),
      version: 3,
      current: { ...row.current, version: 3, snapshot_hash: "c".repeat(64) },
    });
    await review.load();
    await review.decide("reject", true);
    expect(api.decideConsultation).toHaveBeenCalledTimes(1);
    await review.retry();
    expect(api.decideConsultation.mock.calls[1][2]).toEqual(original);
  });
  it("version conflicts clear the pending mutation and hide stale review content", async () => {
    const { api, review } = setup();
    await review.bind("thread", "appointment", "visitor");
    api.decideConsultation.mockRejectedValueOnce(
      new ApiError("consultation_state_conflict", 409),
    );
    await review.decide("accept", true);
    expect(review.pending).toBeNull();
    expect(review.row).toBeNull();
    expect(review.error).toContain("最新版本");
  });
  it("old visitor responses cannot restore a new visitor's case", async () => {
    const { api, review } = setup();
    let resolve!: (row: VisitCase | null) => void;
    api.consultation.mockImplementationOnce(
      () => new Promise((done) => (resolve = done)),
    );
    const pending = review.bind("old-thread", "old-appointment", "old-visitor");
    api.consultation.mockResolvedValueOnce(null);
    await review.bind("new-thread", "new-appointment", "new-visitor");
    resolve(row);
    await pending;
    expect(review.row).toBeNull();
    expect(review.pending).toBeNull();
  });
});
