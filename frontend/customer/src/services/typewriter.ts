type Frame = (time: number) => void;
export interface AnimationClock {
  now(): number;
  request(callback: Frame): number;
  cancel(id: number): void;
}
const browserClock: AnimationClock = {
  now: () => performance.now(),
  request: (callback) => requestAnimationFrame(callback),
  cancel: (id) => cancelAnimationFrame(id),
};

/** Animate only text already accepted by the API. Never changes the underlying answer. */
export class Typewriter {
  private frame: number | null = null;
  private text = "";
  constructor(
    private update: (text: string, typing: boolean) => void,
    private clock: AnimationClock = browserClock,
  ) {}
  start(text: string, animate = true) {
    this.dispose();
    this.text = text;
    if (!animate || !text) {
      this.update(text, false);
      return;
    }
    const segments =
      typeof Intl.Segmenter === "function"
        ? Array.from(
            new Intl.Segmenter("zh", { granularity: "grapheme" }).segment(text),
            (part) => part.segment,
          )
        : Array.from(text);
    let offset = 0;
    const ends = segments.map((segment) => (offset += segment.length));
    const duration = Math.min(8000, segments.length * 26);
    const started = this.clock.now();
    this.update("", true);
    const step = (time: number) => {
      this.frame = null;
      const count = Math.min(
        ends.length,
        Math.floor((Math.max(0, time - started) / duration) * ends.length),
      );
      const typing = count < ends.length;
      this.update(text.slice(0, count ? ends[count - 1]! : 0), typing);
      if (typing) this.frame = this.clock.request(step);
    };
    this.frame = this.clock.request(step);
  }
  finish() {
    this.dispose();
    this.update(this.text, false);
  }
  dispose() {
    if (this.frame !== null) this.clock.cancel(this.frame);
    this.frame = null;
  }
}
