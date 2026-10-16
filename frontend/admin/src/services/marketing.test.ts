import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  MarketingSubmission,
  type MarketingInput,
  type MarketingJob,
} from "./marketing";

const input: Omit<MarketingInput, "request_key"> = {
  brand: "演示品牌",
  kind: "image",
  title: "日常护理",
  prompt: "自然光护理空间",
  caption: "演示文案",
  aspect: "portrait",
  project_id: null,
  video_cost_acknowledged: false,
};
const job = { id: "job-one", state: "queued" } as MarketingJob;
beforeEach(() => {
  let sequence=0;
  vi.stubGlobal("crypto", {randomUUID:()=>`request-${++sequence}`});
});
afterEach(()=>vi.unstubAllGlobals());
describe("营销生成提交", () => {
  it("网络结果未知时保留相同正文和请求键，重试不会创建重复任务", async () => {
    const create = vi
      .fn<(data: MarketingInput) => Promise<MarketingJob>>()
      .mockRejectedValueOnce(new ApiError("request_timeout"))
      .mockResolvedValue(job);
    const submit = new MarketingSubmission(create);
    await expect(submit.send(input)).rejects.toThrow();
    expect(submit.pending).not.toBeNull();
    await submit.send({ ...input, title: "用户后来修改的标题" });
    expect(create.mock.calls[0]).toEqual(create.mock.calls[1]);
    expect(submit.pending).toBeNull();
  });
  it("明确被拒绝后解除原请求，允许修正内容再次提交", async () => {
    const create = vi
      .fn<(data: MarketingInput) => Promise<MarketingJob>>()
      .mockRejectedValueOnce(new ApiError("invalid_input", "", 422))
      .mockResolvedValue(job);
    const submit = new MarketingSubmission(create);
    await expect(submit.send(input)).rejects.toThrow();
    expect(submit.pending).toBeNull();
    await submit.send({ ...input, title: "修正的标题" });
    expect(create.mock.calls[1]![0].request_key).not.toBe(
      create.mock.calls[0]![0].request_key,
    );
    expect(create.mock.calls[1]![0].title).toBe("修正的标题");
  });
  it("快速重复点击只发送一次", async () => {
    let finish!: (result: MarketingJob) => void;
    const create = vi.fn(
      () =>
        new Promise<MarketingJob>((resolve) => {
          finish = resolve;
        }),
    );
    const submit = new MarketingSubmission(create);
    const first = submit.send(input);
    await submit.send(input);
    expect(create).toHaveBeenCalledTimes(1);
    finish(job);
    await first;
    expect(submit.busy).toBe(false);
  });
});
