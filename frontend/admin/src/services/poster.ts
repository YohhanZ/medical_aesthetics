import type { Aspect } from "./marketing";

export interface PosterContent {
  brand: string;
  title: string;
  caption: string;
  aspect: Aspect;
  sample: boolean;
  simulated: boolean;
}
const sizes: Record<Aspect, [number, number]> = {
  portrait: [1080, 1440],
  square: [1080, 1080],
  landscape: [1440, 810],
};
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function renderPoster(
  content: PosterContent,
  source: string,
): Promise<Blob> {
  const canvas = document.createElement("canvas");
  [canvas.width, canvas.height] = sizes[content.aspect];
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("当前浏览器不支持海报导出");
  const image = new Image();
  image.src = source;
  await image.decode();
  const w = canvas.width,
    h = canvas.height;
  ctx.fillStyle = "#f3f5ed";
  ctx.fillRect(0, 0, w, h);
  const photoHeight = h * 0.69;
  const scale = Math.max(w / image.width, photoHeight / image.height);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, w, photoHeight);
  ctx.clip();
  ctx.drawImage(
    image,
    (w - image.width * scale) / 2,
    (photoHeight - image.height * scale) / 2,
    image.width * scale,
    image.height * scale,
  );
  ctx.restore();
  const fade = ctx.createLinearGradient(0, photoHeight * 0.68, 0, photoHeight);
  fade.addColorStop(0, "#f3f5ed00");
  fade.addColorStop(1, "#f3f5ed");
  ctx.fillStyle = fade;
  ctx.fillRect(0, photoHeight * 0.68, w, photoHeight * 0.32);
  const pad = w * 0.075;
  ctx.fillStyle = "#2d4b39";
  ctx.font = `500 ${Math.round(w * 0.025)}px "Microsoft YaHei", sans-serif`;
  ctx.fillText(content.brand.slice(0, 24), pad, pad);
  ctx.fillStyle = "#38523e";
  ctx.font = `500 ${Math.round(w * 0.052)}px "Microsoft YaHei", sans-serif`;
  function lines(
    text: string,
    x: number,
    y: number,
    max: number,
    lineHeight: number,
    limit: number,
  ) {
    const chars = Array.from(text.replace(/\s+/g, " "));
    let line = "",
      row = 0;
    for (let i = 0; i < chars.length; i++) {
      const next = line + chars[i];
      if (ctx!.measureText(next).width > max && line) {
        ctx!.fillText(
          row === limit - 1 ? line.slice(0, -1) + "…" : line,
          x,
          y + row * lineHeight,
        );
        row++;
        if (row >= limit) return;
        line = chars[i]!;
      } else line = next;
    }
    if (line) ctx!.fillText(line, x, y + row * lineHeight);
  }
  lines(
    content.title,
    pad,
    h * 0.72,
    w - pad * 2,
    w * 0.07,
    content.aspect === "landscape" ? 1 : 2,
  );
  ctx.fillStyle = "#77816d";
  ctx.font = `400 ${Math.round(w * 0.022)}px "Microsoft YaHei", sans-serif`;
  lines(
    content.caption,
    pad,
    h * 0.84,
    w - pad * 2,
    w * 0.028,
    content.aspect === "landscape" ? 2 : 3,
  );
  ctx.fillStyle = "#8e9a82";
  ctx.font = `400 ${Math.round(w * 0.016)}px "Microsoft YaHei", sans-serif`;
  ctx.fillText(
    content.sample
      ? "示例排版 · AI 场景示意 · 非实时生成"
      : content.simulated
        ? "AI 生成 · 虚构门店演示素材"
        : "AI 生成 · 场景示意",
    pad,
    h - pad * 0.5,
  );
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("海报导出失败"))),
      "image/png",
    ),
  );
}
