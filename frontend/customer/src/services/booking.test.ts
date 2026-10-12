import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  Booking,
  confirmationText,
  cancelText,
  acceptChangeText,
  type BookingApi,
  type BookingState,
  type DraftForm,
} from "./booking";

beforeEach(() => {
  let count = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `booking-key-${++count}` });
});

describe("客户改约与取消", () => {
  async function withAppointment() {
    const f = fixture();
    await f.booking.bind("thread-one", "visitor-one");
    await f.booking.save(form);
    await f.booking.send(true);
    await f.booking.verify("123456");
    await f.booking.confirm(true);
    const row = f.state.appointments[0]!;
    row.version = 2;
    row.change_proposal = {
      id: "proposal-one",
      version: 2,
      snapshot_hash: "b".repeat(64),
      proposed_at: "2026-11-03T02:00:00Z",
      expires_at: "2099-12-01T02:00:00Z",
    };
    await f.booking.reload();
    return f;
  }
  it("需要客户明确选择，并绑定当前版本和提案快照", async () => {
    const { api, booking } = await withAppointment();
    await booking.respond("appointment-one", "accept", false);
    await booking.cancel("appointment-one", false);
    expect(api.respondChange).not.toHaveBeenCalled();
    expect(api.cancelAppointment).not.toHaveBeenCalled();
    await booking.respond("appointment-one", "accept", true);
    expect(api.respondChange.mock.calls[0]![2]).toMatchObject({
      expected_version: 2,
      proposal_id: "proposal-one",
      snapshot_hash: "b".repeat(64),
      decision: "accept",
      confirmation_text: acceptChangeText,
    });
  });
  it("结果未知仍重试原提案，不接受刷新后的另一个时间", async () => {
    const { api, booking, state } = await withAppointment();
    api.respondChange.mockRejectedValueOnce(new ApiError("request_timeout"));
    await booking.respond("appointment-one", "accept", true);
    const original = structuredClone(api.respondChange.mock.calls[0]![2]);
    state.appointments[0]!.version = 3;
    state.appointments[0]!.change_proposal!.id = "proposal-two";
    await booking.reload();
    await booking.cancel("appointment-one", true);
    expect(api.cancelAppointment).not.toHaveBeenCalled();
    await booking.retry();
    expect(api.respondChange.mock.calls[1]![2]).toEqual(original);
  });
  it("取消需原请求重试，版本冲突则解除未知状态等待重新审阅", async () => {
    const { api, booking } = await withAppointment();
    api.cancelAppointment.mockRejectedValueOnce(
      new ApiError("network_unavailable"),
    );
    await booking.cancel("appointment-one", true);
    const original = structuredClone(api.cancelAppointment.mock.calls[0]![2]);
    expect(original.confirmation_text).toBe(cancelText);
    api.cancelAppointment.mockRejectedValueOnce(
      new ApiError("appointment_state_conflict", 409),
    );
    await booking.retry();
    expect(api.cancelAppointment.mock.calls[1]![2]).toEqual(original);
    expect(booking.pending).toBeNull();
    expect(booking.error).toContain("预约状态已变化");
  });
  it("旧线程的改约结果不能填回新线程", async () => {
    const { api, booking, state } = await withAppointment();
    let resolve!: (row: (typeof state.appointments)[0]) => void;
    api.respondChange.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const pending = booking.respond("appointment-one", "accept", true);
    const row = state.appointments[0]!;
    state.appointments = [];
    await booking.bind("thread-two", "visitor-two");
    resolve(row);
    await pending;
    expect(booking.state?.appointments).toEqual([]);
    expect(booking.pending).toBeNull();
  });
});
afterEach(() => vi.unstubAllGlobals());

const form: DraftForm = {
  name: "合成客户",
  phone: "19900000001",
  desired_at: "2026-11-01T02:00:00Z",
  intention: "先咨询",
  project_version_id: null,
};
function fixture() {
  let state: BookingState = {
    configured: true,
    simulated_verification: true,
    trigger_run_id: "run-one",
    draft: null,
    verification: null,
    appointments: [],
    blocked_reason: "",
  };
  const api = {
    consultation: vi.fn<BookingApi["consultation"]>(),
    decideConsultation: vi.fn<BookingApi["decideConsultation"]>(),
    followups: vi.fn<BookingApi["followups"]>(),
    respondFollowup: vi.fn<BookingApi["respondFollowup"]>(),
    cancelAppointment: vi.fn<BookingApi["cancelAppointment"]>(),
    respondChange: vi.fn<BookingApi["respondChange"]>(),
    booking: vi.fn<BookingApi["booking"]>(async () => structuredClone(state)),
    createDraft: vi.fn<BookingApi["createDraft"]>(async (_thread, body) => {
      state.draft = {
        id: "draft-one",
        ...body,
        request_key: body.request_key,
        snapshot_hash: "a".repeat(64),
        phone_masked: "199****0001",
        project_title: null,
        store_name: "模拟店",
        expires_at: "2026-12-01T02:00:00Z",
        status: "active",
        simulated: true,
        policy: {
          id: "policy-one",
          title: "模拟预约政策",
          version: 1,
          content: "门店确认",
          source: "合成",
          simulated: true,
        },
      };
      return state.draft!;
    }),
    sendCode: vi.fn<BookingApi["sendCode"]>(async (_thread, draft, body) => {
      state.verification = {
        id: "verification-one",
        request_key: body.request_key,
        draft_id: draft,
        delivery_state: "sent",
        expires_at: "2026-12-01T02:00:00Z",
        verified: false,
        simulated: true,
        attempts_remaining: 5,
      };
      return state.verification;
    }),
    verifyCode: vi.fn<BookingApi["verifyCode"]>(async () => {
      state.verification!.verified = true;
      return state.verification!;
    }),
    confirmDraft: vi.fn<BookingApi["confirmDraft"]>(
      async (_thread, _draft, body) => {
        const appointment = {
          id: "appointment-one",
          request_key: body.request_key,
          state: "pending_store_confirmation",
          simulated: true,
          created_at: "2026-11-01T02:00:00Z",
          ...form,
          phone_masked: "199****0001",
          project_title: null,
          store_name: "模拟店",
        };
        state.appointments = [appointment];
        state.draft = null;
        state.verification = null;
        state.trigger_run_id = null;
        return appointment;
      },
    ),
    discardDraft: vi.fn<BookingApi["discardDraft"]>(async () => {
      state.draft = null;
      state.verification = null;
      return { discarded: true };
    }),
  } satisfies BookingApi;
  const booking = new Booking(api);
  return {
    api,
    booking,
    state,
    setState(next: BookingState) {
      state = next;
    },
  };
}

describe("预约确认与未知结果恢复", () => {
  it("先核验，再明确客户确认，快照与凭证随原键提交", async () => {
    const { api, booking } = fixture();
    await booking.bind("thread-one", "visitor-one");
    await booking.save(form);
    await booking.send(false);
    await booking.confirm(true);
    expect(api.sendCode).not.toHaveBeenCalled();
    expect(api.confirmDraft).not.toHaveBeenCalled();
    await booking.send(true);
    await booking.verify("123456");
    await booking.confirm(false);
    expect(api.confirmDraft).not.toHaveBeenCalled();
    await booking.confirm(true);
    expect(api.confirmDraft.mock.calls[0]![2]).toMatchObject({
      accepted: true,
      snapshot_hash: "a".repeat(64),
      verification_id: "verification-one",
      confirmation_text: confirmationText,
    });
    expect(booking.state?.appointments[0]?.state).toBe(
      "pending_store_confirmation",
    );
    expect(booking.state?.draft).toBeNull();
  });
  it("提交结果未知时保持原键与快照，核实前不发新申请", async () => {
    const { api, booking } = fixture();
    await booking.bind("thread-one", "visitor-one");
    await booking.save(form);
    await booking.send(true);
    await booking.verify("123456");
    const original = api.confirmDraft.getMockImplementation()!;
    api.confirmDraft.mockRejectedValueOnce(new ApiError("network_unavailable"));
    await booking.confirm(true);
    expect(booking.pending?.kind).toBe("confirm");
    await booking.confirm(true);
    expect(api.confirmDraft).toHaveBeenCalledTimes(1);
    api.confirmDraft.mockImplementation(original);
    await booking.retry();
    expect(api.confirmDraft.mock.calls[0]![2]).toEqual(
      api.confirmDraft.mock.calls[1]![2],
    );
    expect(booking.pending).toBeNull();
  });
  it("写后网络失败通过权威请求键核实，不再次提交", async () => {
    const { api, booking } = fixture();
    await booking.bind("thread-one", "visitor-one");
    await booking.save(form);
    await booking.send(true);
    await booking.verify("123456");
    const original = api.confirmDraft.getMockImplementation()!;
    api.confirmDraft.mockImplementationOnce(async (...args) => {
      await original(...args);
      throw new ApiError("network_unavailable");
    });
    await booking.confirm(true);
    expect(booking.pending).toBeNull();
    expect(booking.error).toBe("");
    expect(api.confirmDraft).toHaveBeenCalledTimes(1);
    expect(booking.state?.appointments).toHaveLength(1);
  });
  it("未知草稿重试不随表单更改而改变原始业务内容", async () => {
    const { api, booking } = fixture();
    await booking.bind("thread-one", "visitor-one");
    api.createDraft.mockRejectedValueOnce(new ApiError("request_timeout"));
    const mutable = { ...form };
    await booking.save(mutable);
    mutable.phone = "19900000002";
    await booking.retry();
    expect(api.createDraft.mock.calls[0]![1]).toEqual(
      api.createDraft.mock.calls[1]![1],
    );
    expect(api.createDraft.mock.calls[1]![1].phone).toBe("19900000001");
  });
  it("旧草稿被医疗/拒绝意愿或政策更新阻断时不能提交", async () => {
    const { api, booking, state } = fixture();
    await booking.bind("thread-one", "visitor-one");
    await booking.save(form);
    await booking.send(true);
    await booking.verify("123456");
    state.blocked_reason = "booking_offer_changed";
    await booking.reload();
    await booking.confirm(true);
    await booking.send(true);
    expect(api.confirmDraft).not.toHaveBeenCalled();
    expect(api.sendCode).toHaveBeenCalledTimes(1);
  });
  it("切换访客/线程立即清理业务缓存，忽略旧异步结果", async () => {
    const { api, booking } = fixture();
    let resolve!: (state: BookingState) => void;
    api.booking.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const loading = booking.bind("old-thread", "old-visitor");
    await booking.bind("new-thread", "new-visitor");
    resolve({
      configured: true,
      trigger_run_id: "old-run",
      draft: null,
      verification: null,
      appointments: [],
      blocked_reason: "",
    });
    await loading;
    expect(booking.state?.trigger_run_id).toBe("run-one");
    expect(api.booking.mock.calls.at(-1)?.[0]).toBe("new-thread");
  });
  it("凭据失效清理草稿、核验和未知写入，不能用缓存确认", async () => {
    const { api, booking } = fixture();
    await booking.bind("thread-one", "visitor-one");
    await booking.save(form);
    api.booking.mockRejectedValueOnce(new ApiError("unauthenticated", 401));
    await booking.reload();
    await booking.confirm(true);
    expect(booking.state).toBeNull();
    expect(booking.pending).toBeNull();
    expect(api.confirmDraft).not.toHaveBeenCalled();
  });
  it("重新读取失败隐藏旧业务内容，等待重新核实", async () => {
    const { api, booking } = fixture();
    await booking.bind("thread-one", "visitor-one");
    await booking.save(form);
    api.booking.mockRejectedValueOnce(new ApiError("network_unavailable"));
    await booking.reload();
    expect(booking.state).toBeNull();
    expect(booking.error).toContain("无法连接");
  });
});
