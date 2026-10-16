import { request, ApiError } from "./api";
import { session, clearSession } from "../state";

export type MediaKind = "image" | "video";
export type Aspect = "portrait" | "square" | "landscape";
export interface MarketingJob {
  brand: string;
  id: string;
  kind: MediaKind;
  state:
    | "queued"
    | "submitting"
    | "running"
    | "succeeded"
    | "failed"
    | "unknown"
    | "cancelled";
  title: string;
  prompt: string;
  caption: string;
  aspect: Aspect;
  model: string;
  simulated: boolean;
  created_at: string;
  error_code: string | null;
  asset_mime: string | null;
  asset_bytes: number | null;
  can_reconcile: boolean;
}
export interface MarketingOptions {
  image_ready: boolean;
  video_ready: boolean;
  image_model: string;
  video_model: string;
  daily_limit: number;
  projects: {
    id: string;
    title: string;
    description: string;
    simulated: boolean;
  }[];
}
export interface MarketingInput {
  brand: string;
  request_key: string;
  kind: MediaKind;
  title: string;
  prompt: string;
  caption: string;
  aspect: Aspect;
  project_id: string | null;
  video_cost_acknowledged: boolean;
}
export const stateNames: Record<MarketingJob["state"], string> = {
  queued: "排队中",
  submitting: "正在提交",
  running: "生成处理中",
  succeeded: "已完成",
  failed: "未完成",
  unknown: "结果待核实",
  cancelled: "已取消",
};
export const mediaErrors: Record<string, string> = {
  provider_auth: "接口凭据无效或没有模型权限，请检查配置。",
  provider_quota: "供应商额度不足，请在供应商控制台查看。",
  provider_rate_limit: "供应商暂时限流，请稍后再试。",
  provider_rejected: "供应商未接受本次请求，请核对模型权限与画面描述。",
  provider_task_failed:
    "供应商任务未成功，可能与额度、内容审核或服务状态有关。",
  provider_unconfigured: "接口尚未配置或已关闭。",
  submission_unknown: "提交结果未知，系统不会自动重复生成，避免重复消耗额度。",
  provider_response_invalid: "供应商返回格式异常，需核实原任务。",
  provider_poll_timeout: "等待时间较长，可核实原任务，不会重新提交生成。",
  provider_poll_failed: "暂时无法查询供应商状态，可核实原任务。",
  asset_download_failed: "素材转存暂未完成，可核实原任务继续下载。",
  asset_host_denied: "素材下载域名尚未获准，请联系管理员核对媒体域名配置。",
  asset_format_invalid: "素材格式不符合预期，未保存为可下载作品。",
  asset_too_large: "素材超过当前大小限制，未完成转存。",
  permission_revoked: "原操作人员的门店权限已失效，任务已停止。",
};
export function marketingApi(store: string) {
  const base = `/stores/${store}/marketing`;
  return {
    options: () => request<MarketingOptions>(`${base}/options`),
    list: (offset = 0) =>
      request<{ items: MarketingJob[] }>(`${base}/jobs?offset=${offset}`),
    create: (data: MarketingInput) =>
      request<MarketingJob>(`${base}/jobs`, { method: "POST", body: data }),
    cancel: (id: string) =>
      request<MarketingJob>(`${base}/jobs/${id}/cancel`, { method: "POST" }),
    reconcile: (id: string) =>
      request<MarketingJob>(`${base}/jobs/${id}/reconcile`, { method: "POST" }),
  };
}
export async function marketingAsset(store: string, id: string): Promise<Blob> {
  const token = session.value?.token;
  if (!token || session.value?.mode !== "live")
    throw new ApiError("unauthenticated");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(
      `/api/stores/${store}/marketing/jobs/${id}/asset`,
      {
        headers: { Authorization: `Bearer ${token}` },
        credentials: "omit",
        cache: "no-store",
        signal: controller.signal,
      },
    );
    if (!response.ok) {
      if (response.status === 401 && session.value?.token === token)
        clearSession();
      throw new ApiError("marketing_asset_unavailable");
    }
    return await response.blob();
  } finally {
    clearTimeout(timer);
  }
}

/** Keeps the identical request key/body when a response was lost. */
export class MarketingSubmission {
  pending: MarketingInput | null = null;
  busy = false;
  constructor(
    private create: (input: MarketingInput) => Promise<MarketingJob>,
  ) {}
  async send(
    input: Omit<MarketingInput, "request_key">,
  ): Promise<MarketingJob | undefined> {
    if (this.busy) return;
    this.pending ??= { ...input, request_key: crypto.randomUUID() };
    this.busy = true;
    try {
      const result = await this.create(this.pending);
      this.pending = null;
      return result;
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500 &&
        error.status !== 408
      )
        this.pending = null;
      throw error;
    } finally {
      this.busy = false;
    }
  }
}
