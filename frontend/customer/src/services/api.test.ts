import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, errorText } from "./api";
import { answer, session } from "../tests/fixtures";

describe("客户 API 出口", () => {
  it("历史会话分页使用当前客户 Cookie，不传递访客身份参数", async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockImplementation(
        async () => new Response(JSON.stringify({ items: [] })),
      );
    const api = new ApiClient(transport);
    await api.threads(20);
    expect(transport.mock.calls[0]![0]).toBe("/api/threads?offset=20");
    expect(transport.mock.calls[0]![1]?.credentials).toBe("same-origin");
  });
  it("客户登录后使用轮换的 CSRF，不将密码放入持久存储", async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(session)))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "rotated", restored: true })),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "accepted" })),
      );
    const api = new ApiClient(transport);
    await api.current();
    await api.customerAuth("alice", "test-only-password", false, false);
    await api.recordBehavior("category_view", "care");
    expect(transport.mock.calls[1]![0]).toBe("/api/customer-sessions");
    expect(JSON.parse(transport.mock.calls[1]![1]!.body as string)).toEqual({
      username: "alice",
      password: "test-only-password",
      bind_current: false,
    });
    expect(transport.mock.calls[2]![1]!.headers).toEqual({
      "Content-Type": "application/json",
      "X-CSRF-Token": "rotated",
    });
  });
  it("可选行为记录失败不会刷新身份或阻塞浏览", async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ code: "csrf_invalid" }), { status: 403 }),
      );
    await expect(
      new ApiClient(transport).recordBehavior("category_view", "care"),
    ).resolves.toBeUndefined();
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it("默认浏览器 fetch 绑定全局对象，避免 Illegal invocation", async () => {
    vi.stubGlobal("fetch", function (this: unknown) {
      expect(this).toBe(globalThis);
      return Promise.resolve(new Response(JSON.stringify({ items: [] })));
    });
    try {
      expect(await new ApiClient().stores()).toEqual([]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("使用同源 Cookie 与 CSRF，没有员工授权头或模型参数", async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(JSON.stringify(session)))
      .mockResolvedValueOnce(new Response(JSON.stringify(answer)));
    const api = new ApiClient(transport);
    await api.current();
    await api.send("thread-one", {
      message_id: "key",
      question: "公开咨询问题",
    });
    const options = transport.mock.calls[1]![1]!;
    expect(options.credentials).toBe("same-origin");
    expect(options.headers).toEqual({
      "Content-Type": "application/json",
      "X-CSRF-Token": "synthetic-csrf",
    });
    expect(JSON.parse(options.body as string)).toEqual({
      message_id: "key",
      question: "公开咨询问题",
    });
  });
  it("服务失败不自动重试消息，也不回显任意服务正文", async () => {
    const transport = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "agent_unavailable",
          safe_message: "SENSITIVE-provider-body",
        }),
        { status: 503 },
      ),
    );
    const api = new ApiClient(transport);
    const error = await api
      .send("thread-one", { message_id: "key", question: "公开咨询问题" })
      .catch((value) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(errorText(error)).not.toContain("SENSITIVE");
  });
  it("仅 CSRF 前置拒绝时刷新一次，重试保持原消息键", async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ code: "csrf_invalid" }), { status: 403 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(session)))
      .mockResolvedValueOnce(new Response(JSON.stringify(answer)));
    await new ApiClient(transport).send("thread-one", {
      message_id: "same-key",
      question: "同一问题",
    });
    expect(transport).toHaveBeenCalledTimes(3);
    expect(transport.mock.calls[0]![1]!.body).toEqual(
      transport.mock.calls[2]![1]!.body,
    );
    expect(transport.mock.calls[2]![1]!.headers).toEqual({
      "Content-Type": "application/json",
      "X-CSRF-Token": "synthetic-csrf",
    });
  });
});
