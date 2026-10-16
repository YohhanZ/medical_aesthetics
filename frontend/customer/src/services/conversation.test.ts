import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ConsultationApi } from "./api";
import { Conversation } from "./conversation";
import { answer, project, session } from "../tests/fixtures";
import type { HistoryMessage, Thread } from "../types";

function fixture() {
  const api = {
    stores: vi.fn(async () => [
      { code: "store-one", name: "模拟门店", simulated: true },
    ]),
    current: vi.fn(async () => ({ ...session })),
    customerSession: vi.fn(
      async (): Promise<{ customer: { username: string } | null }> => ({
        customer: { username: "alice" },
      }),
    ),
    createSession: vi.fn(async () => {}),
    threads: vi.fn(
      async (_offset?: number): Promise<Thread[]> => [
        { thread_id: "thread-one", created_at: "2026-10-11T00:00:00Z" },
      ],
    ),
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
  it("只有首次匿名连接且没有指定门店时，才允许自动匹配附近门店", async () => {
    const restored = fixture();
    await restored.chat.initialize();
    expect(restored.chat.freshSession).toBe(false);
    for (const entryStore of [undefined, "store-one"]) {
      const { api, chat } = fixture();
      api.current.mockRejectedValueOnce(new ApiError("unauthenticated", 401));
      api.customerSession.mockResolvedValue({ customer: null });
      await chat.initialize(entryStore);
      expect(chat.freshSession).toBe(!entryStore);
      chat.clearIdentity();
      expect(chat.freshSession).toBe(false);
    }
  });
  it("切换会话恢复对应消息且失败时保留当前内容，不重复创建会话", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    api.history.mockResolvedValueOnce([
      {
        id: "old",
        message_id: "old-key",
        run_id: "old-run",
        role: "user",
        content: "旧对话问题",
        status: "completed",
        result: null,
      },
    ]);
    await chat.selectThread("old-thread");
    expect(chat.thread).toBe("old-thread");
    expect(chat.messages.map((row) => row.text)).toEqual(["旧对话问题"]);
    api.history.mockRejectedValueOnce(new ApiError("network_unavailable"));
    await chat.selectThread("another-thread");
    expect(chat.thread).toBe("old-thread");
    expect(chat.messages[0]?.text).toBe("旧对话问题");
    api.history.mockRejectedValueOnce(new ApiError("thread_not_found", 404));
    await chat.selectThread("missing-thread");
    expect(chat.ready).toBe(true);
    expect(chat.customer?.username).toBe("alice");
    expect(chat.thread).toBe("old-thread");
    expect(api.newThread).not.toHaveBeenCalled();
  });
  it("历史分页追加更早会话，切换身份后丢弃迟到的列表响应", async () => {
    const { api, chat } = fixture();
    const rows = Array.from({ length: 20 }, (_, index) => ({
      thread_id: `thread-${index}`,
      created_at: "2026-10-15T00:00:00Z",
      title: `咨询 ${index}`,
    }));
    api.threads.mockResolvedValue(rows);
    await chat.initialize();
    let finish!: (rows: Thread[]) => void;
    api.threads.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const request = chat.moreThreads();
    expect(api.threads).toHaveBeenLastCalledWith(20);
    finish([{ thread_id: "older", created_at: "2026-10-11T00:00:00Z" }]);
    await request;
    expect(chat.threads).toHaveLength(21);
    expect(chat.hasMoreThreads).toBe(false);
    api.threads.mockResolvedValue(rows);
    await chat.initialize();
    api.threads.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const stale = chat.moreThreads();
    chat.clearIdentity();
    finish([{ thread_id: "private-old", created_at: "2026-10-11T00:00:00Z" }]);
    await stale;
    expect(chat.threads).toEqual([]);
    expect(chat.loadingThreads).toBe(false);
  });
  it("第一条问题命名会话，新建成功后列表刷新失败仍保留新 ID", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    await chat.send("想了解基础补水护理");
    expect(chat.threads[0]?.title).toBe("想了解基础补水护理");
    await chat.send("护理多久一次？");
    expect(chat.threads[0]?.title).toBe("想了解基础补水护理");
    api.threads.mockRejectedValueOnce(new ApiError("network_unavailable"));
    await chat.newConversation();
    expect(chat.thread).toBe("thread-two");
    expect(chat.threads[0]?.thread_id).toBe("thread-two");
    expect(chat.ready).toBe(true);
    expect(chat.threadListError).toContain("已创建");
    expect(chat.messages).toEqual([]);
    expect(api.newThread).toHaveBeenCalledTimes(1);
  });
  it("每次进入都恢复服务器最新会话，同账号的旧浏览器引用不能覆盖它", async () => {
    const { api, chat, records } = fixture();
    records.set(
      "ma-consultation-reference",
      JSON.stringify({ visitor_id: "visitor-one", thread_id: "old-thread" }),
    );
    api.threads.mockResolvedValue([
      { thread_id: "latest-thread", created_at: "2026-10-15T00:00:00Z" },
      { thread_id: "old-thread", created_at: "2026-10-11T00:00:00Z" },
    ]);
    await chat.initialize();
    expect(chat.thread).toBe("latest-thread");
    expect(api.history).toHaveBeenCalledWith("latest-thread");
    expect(api.newThread).not.toHaveBeenCalled();
    await chat.initialize();
    expect(api.history).toHaveBeenLastCalledWith("latest-thread");
    expect(api.newThread).not.toHaveBeenCalled();
  });
  it("首次无会话才创建，开启新对话使用独立 ID，重进时恢复这一段", async () => {
    const { api, chat } = fixture();
    api.threads.mockResolvedValueOnce([]);
    api.newThread
      .mockResolvedValueOnce("first-session")
      .mockResolvedValueOnce("next-session");
    await chat.initialize();
    expect(chat.thread).toBe("first-session");
    await chat.send("你好");
    await chat.newConversation();
    expect(chat.thread).toBe("next-session");
    expect(chat.messages).toEqual([]);
    expect(chat.pending).toBeNull();
    expect(api.newThread).toHaveBeenCalledTimes(2);
    api.threads.mockResolvedValue([
      { thread_id: "next-session", created_at: "2026-10-15T00:00:00Z" },
    ]);
    await chat.initialize();
    expect(chat.thread).toBe("next-session");
    expect(api.newThread).toHaveBeenCalledTimes(2);
  });
  it("读取期间会话已失效时重新获取最新列表，不反复请求失效会话", async () => {
    const { api, chat } = fixture();
    api.threads.mockResolvedValueOnce([
      { thread_id: "gone", created_at: "2026-10-15T00:00:00Z" },
    ]);
    api.history.mockRejectedValueOnce(new ApiError("thread_not_found", 404));
    await chat.initialize();
    expect(api.history).toHaveBeenNthCalledWith(1, "gone");
    expect(api.history).toHaveBeenNthCalledWith(2, "thread-one");
    expect(chat.thread).toBe("thread-one");
    expect(chat.ready).toBe(true);
  });
  it("只给刚接收的回答添加动画标记，历史恢复不重播", async () => {
    const { api, chat } = fixture();
    api.history.mockResolvedValueOnce([
      {
        id: "historical-answer",
        role: "assistant",
        content: "已保存的回答",
        message_id: "old-message",
        run_id: "old-run",
        status: "completed",
        result: null,
      },
    ]);
    await chat.initialize();
    expect(chat.messages[0]?.animate).toBeUndefined();
    await chat.send("你好");
    expect(chat.messages.at(-1)?.animate).toBe(true);
    expect(chat.messages.at(-1)?.text).toBe(answer.answer);
  });
  it("未登录只建立登录连接，不读取目录、历史或创建咨询线程", async () => {
    const { api, chat, records } = fixture();
    api.customerSession.mockResolvedValueOnce({ customer: null });
    await chat.initialize();
    expect(chat.customer).toBeNull();
    expect(chat.session?.visitor_id).toBe("visitor-one");
    expect(chat.ready).toBe(false);
    expect(api.projects).not.toHaveBeenCalled();
    expect(api.threads).not.toHaveBeenCalled();
    expect(api.newThread).not.toHaveBeenCalled();
    expect(records.size).toBe(0);
  });
  it("有效客户登录态直接恢复咨询，不再次注册或建立匿名身份", async () => {
    const { api, chat } = fixture();
    await chat.initialize();
    expect(chat.customer?.username).toBe("alice");
    expect(chat.ready).toBe(true);
    expect(api.createSession).not.toHaveBeenCalled();
    expect(api.customerSession).toHaveBeenCalledTimes(1);
  });
  it("退出身份立即清除旧消息与引用，重新登录只加载新身份历史", async () => {
    const { api, chat, records } = fixture();
    await chat.initialize();
    await chat.send("基础补水护理");
    expect(chat.messages.length).toBeGreaterThan(0);
    chat.clearIdentity();
    expect(chat.ready).toBe(false);
    expect(chat.messages).toEqual([]);
    expect(chat.session).toBeNull();
    expect(chat.projects).toEqual([]);
    expect(records.has("ma-consultation-reference")).toBe(false);
    api.current.mockResolvedValueOnce({
      ...session,
      visitor_id: "customer-other",
    });
    await chat.reloadIdentity();
    expect(chat.ready).toBe(true);
    expect(chat.session?.visitor_id).toBe("customer-other");
    expect(chat.messages).toEqual([]);
  });
  it("凭据过期后先建立登录连接，不保留消息或凭据到浏览器存储", async () => {
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
  it("已存引用的凭据过期时返回登录入口，不读取旧会话", async () => {
    const { api, chat, records } = fixture();
    records.set(
      "ma-consultation-reference",
      JSON.stringify({ visitor_id: "visitor-one", thread_id: "thread-one" }),
    );
    api.current.mockRejectedValueOnce(new ApiError("unauthenticated", 401));
    api.customerSession.mockResolvedValueOnce({ customer: null });
    await chat.initialize();
    expect(chat.ready).toBe(false);
    expect(chat.customer).toBeNull();
    expect(api.createSession).toHaveBeenCalledWith("store-one");
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
  it("切换门店返回登录入口，清除原门店对话与项目", async () => {
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
    expect(chat.thread).toBe("");
    expect(chat.customer).toBeNull();
    expect(chat.ready).toBe(false);
    expect(chat.messages).toEqual([]);
    expect(chat.projects).toEqual([]);
  });
});
