import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ConsultationApi } from "./api";
import { Conversation } from "./conversation";
import { answer, project, session } from "../tests/fixtures";
import type { HistoryMessage } from "../types";

function fixture() {
  const api = {
    stores: vi.fn(async () => [
      { code: "store-one", name: "模拟门店", simulated: true },
    ]),
    current: vi.fn(async () => ({ ...session })),
    createSession: vi.fn(async () => {}),
    threads: vi.fn(async () => [
      { thread_id: "thread-one", created_at: "2026-10-11T00:00:00Z" },
    ]),
    newThread: vi.fn(async () => "thread-two"),
    history: vi.fn(async (): Promise<HistoryMessage[]> => []),
    send: vi.fn(async (_thread, pending) => ({
      ...answer,
      message_id: pending.message_id,
    })),
    projects: vi.fn(async () => [{ ...project }]),
    project: vi.fn(async () => ({ ...project })),
  } satisfies ConsultationApi;
  const records = new Map<string, string>();
  const storage = {
    getItem: (key: string) => records.get(key) ?? null,
    setItem: (key: string, value: string) => {
      records.set(key, value);
    },
    removeItem: (key: string) => {
      records.delete(key);
    },
  };
  return { api, records, chat: new Conversation(api, storage) };
}
beforeEach(() => {
  let counter = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `message-${++counter}` });
});
afterEach(() => vi.unstubAllGlobals());
describe("真实咨询客户端状态", () => {
  it("无登录页面建立匿名凭据，不保留消息或凭据到浏览器存储", async () => {
    const { api, chat, records } = fixture();
    api.current.mockRejectedValueOnce(new ApiError("unauthenticated", 401));
    await chat.initialize();
    expect(chat.ready).toBe(true);
    expect(api.createSession).toHaveBeenCalledWith("store-one");
    await chat.send("想了解基础补水护理");
    expect(chat.messages).toHaveLength(2);
    const persisted = [...records.values()].join("");
    expect(persisted).not.toContain("补水");
    expect(persisted).not.toContain("synthetic-csrf");
    expect(JSON.parse(persisted)).toEqual({
      visitor_id: "visitor-one",
      thread_id: "thread-one",
    });
  });
  it("未知提交结果重试保持同一消息键和正文，不创建重复用户行", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    api.send.mockRejectedValueOnce(new ApiError("request_timeout"));
    await chat.send("想了解基础补水护理");
    expect(chat.pending).not.toBeNull();
    expect(chat.messages).toHaveLength(1);
    await chat.send("另一条问题");
    expect(api.send).toHaveBeenCalledTimes(1);
    await chat.retry();
    expect(api.send.mock.calls[0]).toEqual(api.send.mock.calls[1]);
    expect(chat.messages).toHaveLength(2);
    expect(chat.pending).toBeNull();
  });
  it("刷新后从持久用户消息恢复失败运行并使用原键", async () => {
    const { api, chat } = fixture();
    api.history.mockResolvedValue([
      {
        id: "stored-user",
        role: "user",
        content: "到店流程是什么",
        message_id: "original-key",
        run_id: "stored-run",
        status: "failed",
        result: null,
      },
    ]);
    await chat.initialize();
    await chat.retry();
    expect(api.send).toHaveBeenCalledWith("thread-one", {
      message_id: "original-key",
      question: "到店流程是什么",
    });
    expect(chat.messages).toHaveLength(2);
  });
  it("凭据在发送期间失效时清除旧消息及卡片，不回退示例回复", async () => {
    const { api, chat, records } = fixture();
    await chat.initialize();
    api.send.mockRejectedValueOnce(new ApiError("unauthenticated", 401));
    await chat.send("到店咨询流程");
    expect(chat.ready).toBe(false);
    expect(chat.messages).toEqual([]);
    expect(chat.projects).toEqual([]);
    expect(records.size).toBe(0);
    expect(chat.error).toContain("失效");
    expect(api.createSession).not.toHaveBeenCalled();
  });
  it("旧访客引用与当前凭据不匹配时不恢复旧会话", async () => {
    const { api, chat, records } = fixture();
    records.set(
      "ma-consultation-reference",
      JSON.stringify({
        visitor_id: "another-visitor",
        thread_id: "other-thread",
      }),
    );
    await chat.initialize();
    expect(api.history).toHaveBeenCalledWith("thread-one");
  });
  it("发送发现线程已不属于当前凭据时移除旧主体的缓存", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    await chat.send("基础补水护理");
    api.send.mockRejectedValueOnce(new ApiError("thread_not_found", 404));
    await chat.send("到店流程");
    expect(chat.ready).toBe(false);
    expect(chat.messages).toEqual([]);
    expect(chat.projects).toEqual([]);
  });
  it("已存引用的凭据过期时先提示，不能静默创建新访客", async () => {
    const { api, chat, records } = fixture();
    records.set(
      "ma-consultation-reference",
      JSON.stringify({ visitor_id: "visitor-one", thread_id: "thread-one" }),
    );
    api.current.mockRejectedValueOnce(new ApiError("unauthenticated", 401));
    await chat.initialize();
    expect(chat.ready).toBe(false);
    expect(api.createSession).not.toHaveBeenCalled();
  });
  it("提交结果已落库后核实历史，不再自动重发", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    api.send.mockRejectedValueOnce(new ApiError("network_unavailable"));
    await chat.send("基础补水护理");
    const key = chat.pending!.message_id;
    api.history.mockResolvedValue([
      {
        id: "user",
        role: "user",
        content: "基础补水护理",
        message_id: key,
        run_id: "run",
        status: "completed",
        result: { ...answer, message_id: key },
      },
      {
        id: "assistant",
        role: "assistant",
        content: answer.answer,
        message_id: key,
        run_id: "run",
        status: "completed",
        result: { ...answer, message_id: key },
      },
    ]);
    await chat.refresh();
    expect(chat.pending).toBeNull();
    expect(chat.messages).toHaveLength(2);
    expect(api.send).toHaveBeenCalledTimes(1);
  });
  it("核实失败时移除未重新授权的卡片和旧回答正文", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    await chat.send("基础补水护理");
    api.history.mockRejectedValueOnce(new ApiError("network_unavailable"));
    await chat.refresh();
    expect(chat.projects).toEqual([]);
    expect(chat.messages[1]?.result).toBeUndefined();
    expect(chat.messages[1]?.text).toContain("重新校验");
  });
  it("其他标签页替换访客后停止旧线程，不混合两个门店状态", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    await chat.send("基础补水护理");
    api.current.mockResolvedValueOnce({
      ...session,
      visitor_id: "new-visitor",
      store_code: "other-store",
    });
    await chat.refresh();
    expect(chat.ready).toBe(false);
    expect(chat.messages).toEqual([]);
  });
  it("切换门店新建访客及线程，清除原门店项目", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    await chat.send("基础补水护理");
    api.current.mockResolvedValueOnce({
      ...session,
      visitor_id: "new-visitor",
      store_code: "other-store",
    });
    api.projects.mockResolvedValueOnce([]);
    await chat.switchStore("other-store");
    expect(api.createSession).toHaveBeenCalledWith("other-store");
    expect(chat.thread).toBe("thread-two");
    expect(chat.messages).toEqual([]);
    expect(chat.projects).toEqual([]);
  });
});
