import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  AppointmentInbox,
  type AppointmentApi,
  type StoreAppointment,
} from "./appointments";
const row: StoreAppointment = {
  id: "appointment",
  version: 1,
  state: "pending_store_confirmation",
  simulated: true,
  name: "合成访客",
  phone_masked: "199****0001",
  intention: "先咨询",
  desired_at: "2026-10-13T06:00:00Z",
  confirmed_at: null,
  decision_reason: null,
  project_title: null,
  created_at: "2026-10-11T06:00:00Z",
  customer_confirmed_at: "2026-10-11T06:00:00Z",
  confirmation_method: "customer_button",
};
function setup() {
  const api = {
    propose: vi
      .fn<AppointmentApi["propose"]>()
      .mockResolvedValue({ ...row, version: 2 }),
    arrive: vi
      .fn<AppointmentApi["arrive"]>()
      .mockResolvedValue({ ...row, state: "arrived", version: 3 }),
    list: vi.fn<AppointmentApi["list"]>().mockResolvedValue({
      items: [{ ...row }],
      total: 1,
      counts: { pending_store_confirmation: 1 },
    }),
    detail: vi.fn<AppointmentApi["detail"]>().mockResolvedValue({ ...row }),
    decide: vi
      .fn<AppointmentApi["decide"]>()
      .mockResolvedValue({ ...row, version: 2, state: "confirmed" }),
    contact: vi
      .fn<AppointmentApi["contact"]>()
      .mockResolvedValue({ phone: "19900000001" }),
  };
  const inbox = new AppointmentInbox(api);
  inbox.bind("store-a", "token-a");
  return { api, inbox };
}
beforeEach(() => {
  vi.stubGlobal("crypto", { randomUUID: () => "synthetic-key" });
});
describe("store appointment operations", () => {
  it("proposals need availability and confirmation; retry preserves the original time", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    await inbox.propose("2026-10-14T14:00", false, true);
    await inbox.propose("2026-10-14T14:00", true, false);
    expect(api.propose).not.toHaveBeenCalled();
    api.propose.mockRejectedValueOnce(new ApiError("request_timeout"));
    await inbox.propose("2026-10-14T14:00", true, true);
    const original = structuredClone(api.propose.mock.calls[0][3]);
    await inbox.open(row.id);
    await inbox.propose("2026-10-15T14:00", true, true);
    expect(api.propose).toHaveBeenCalledTimes(1);
    await inbox.retry();
    expect(api.propose.mock.calls[1][3]).toEqual(original);
    expect(original.expected_version).toBe(1);
  });
  it("arrival requires confirmed state, identity check and no unanswered proposal", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    await inbox.arrive(true, true);
    inbox.selected = { ...row, state: "confirmed", version: 2 };
    await inbox.arrive(false, true);
    inbox.selected.change_proposal = {
      id: "proposal",
      version: 2,
      proposed_at: "time",
      expires_at: "time",
      snapshot_hash: "hash",
    };
    await inbox.arrive(true, true);
    expect(api.arrive).not.toHaveBeenCalled();
    inbox.selected.change_proposal = null;
    await inbox.arrive(true, true);
    expect(api.arrive.mock.calls[0][3]).toMatchObject({
      expected_version: 2,
      identity_checked: true,
      accepted: true,
    });
    expect(inbox.selected?.state).toBe("arrived");
  });
  it("late arrival response cannot restore a closed detail or another store", async () => {
    const { api, inbox } = setup();
    inbox.selected = { ...row, state: "confirmed", version: 2 };
    let resolve!: (row: StoreAppointment) => void;
    api.arrive.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const pending = inbox.arrive(true, true);
    inbox.bind("store-b", "token-b");
    resolve({ ...row, state: "arrived" });
    await pending;
    expect(inbox.selected).toBeNull();
    expect(inbox.pending).toBeNull();
    expect(inbox.items).toEqual([]);
  });
  it("requires explicit confirmation and availability", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    await inbox.decide("confirm", false, true, "");
    await inbox.decide("confirm", true, false, "");
    await inbox.decide("decline", true, false, "");
    expect(api.decide).not.toHaveBeenCalled();
    await inbox.decide("confirm", true, true, "");
    expect(api.decide).toHaveBeenCalledWith(
      "store-a",
      "token-a",
      row.id,
      expect.objectContaining({
        expected_version: 1,
        availability_checked: true,
        accepted: true,
      }),
    );
    expect(inbox.selected?.state).toBe("confirmed");
  });
  it("retries an unknown result using the original immutable request", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    api.decide.mockRejectedValueOnce(new ApiError("request_timeout"));
    await inbox.decide("confirm", true, true, "");
    const original = api.decide.mock.calls[0][3];
    await inbox.open(row.id);
    await inbox.decide("decline", true, false, "other");
    expect(api.decide).toHaveBeenCalledTimes(1);
    await inbox.retry();
    expect(api.decide.mock.calls[1][3]).toEqual(original);
    expect(inbox.pending).toBeNull();
  });
  it("does not overwrite a new store with late list results", async () => {
    const { api, inbox } = setup();
    let finish!: (v: Awaited<ReturnType<AppointmentApi["list"]>>) => void;
    api.list.mockImplementationOnce(
      () => new Promise((resolve) => (finish = resolve)),
    );
    const loading = inbox.load();
    inbox.bind("store-b", "token-b");
    finish({ items: [row], total: 1, counts: { confirmed: 1 } });
    await loading;
    expect(inbox.items).toEqual([]);
    expect(inbox.counts).toEqual({});
  });
  it("does not restore a contact after closing or switching scope", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    let finish!: (v: { phone: string }) => void;
    api.contact.mockImplementationOnce(
      () => new Promise((resolve) => (finish = resolve)),
    );
    const pending = inbox.contact();
    inbox.close();
    finish({ phone: "19900000001" });
    await pending;
    expect(inbox.phone).toBe("");
    expect(inbox.selected).toBeNull();
  });
  it("hides failed detail and refreshes authoritative version", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    api.list.mockRejectedValueOnce(new ApiError("network_unavailable"));
    await inbox.load();
    expect(inbox.items).toEqual([]);
    expect(inbox.selected).toBeNull();
    await inbox.load();
    api.detail.mockResolvedValueOnce({ ...row, version: 2, state: "declined" });
    await inbox.open(row.id);
    expect(inbox.selected?.version).toBe(2);
  });
  it("clears permissions and pending request on revoked access", async () => {
    const { api, inbox } = setup();
    await inbox.open(row.id);
    api.decide.mockRejectedValueOnce(
      new ApiError("store_permission_denied", "", 403),
    );
    await inbox.decide("confirm", true, true, "");
    expect(inbox.pending).toBeNull();
    expect(inbox.selected).toBeNull();
    expect(inbox.items).toEqual([]);
  });
});
