import { describe, expect, it, vi } from "vitest";
import { Typewriter, type AnimationClock } from "./typewriter";

class TestClock implements AnimationClock {
  time = 0;
  sequence = 0;
  frames = new Map<number, (time: number) => void>();
  now() {
    return this.time;
  }
  request(callback: (time: number) => void) {
    const id = ++this.sequence;
    this.frames.set(id, callback);
    return id;
  }
  cancel(id: number) {
    this.frames.delete(id);
  }
  advance(ms: number) {
    this.time += ms;
    const pending = [...this.frames.values()];
    this.frames.clear();
    pending.forEach((callback) => callback(this.time));
  }
}

describe("回复逐字呈现", () => {
  it("按可见字符呈现，不拆开中文、组合字符和 emoji", () => {
    const clock = new TestClock(),
      update = vi.fn();
    new Typewriter(update, clock).start("你👩‍⚕️é");
    expect(update).toHaveBeenLastCalledWith("", true);
    clock.advance(26);
    expect(update).toHaveBeenLastCalledWith("你", true);
    clock.advance(26);
    expect(update).toHaveBeenLastCalledWith("你👩‍⚕️", true);
    clock.advance(26);
    expect(update).toHaveBeenLastCalledWith("你👩‍⚕️é", false);
    expect(clock.frames.size).toBe(0);
  });
  it("长回答在有限时间内完成，暂停标签页后按实际经过时间推进", () => {
    const clock = new TestClock(),
      update = vi.fn();
    const text = "护理".repeat(2000);
    new Typewriter(update, clock).start(text);
    clock.advance(8000);
    expect(update).toHaveBeenLastCalledWith(text, false);
    expect(clock.frames.size).toBe(0);
  });
  it("立即显示和组件销毁都会撤销未完成帧，不再回写旧回复", () => {
    const clock = new TestClock(),
      update = vi.fn();
    const player = new Typewriter(update, clock);
    player.start("上一段回答");
    clock.advance(26);
    player.finish();
    expect(update).toHaveBeenLastCalledWith("上一段回答", false);
    expect(clock.frames.size).toBe(0);
    player.start("新会话");
    player.dispose();
    const calls = update.mock.calls.length;
    clock.advance(1000);
    expect(update).toHaveBeenCalledTimes(calls);
    expect(clock.frames.size).toBe(0);
  });
  it("历史记录、减少动态效果和空消息无需启动计时", () => {
    const clock = new TestClock(),
      update = vi.fn();
    const player = new Typewriter(update, clock);
    player.start("历史完整回复", false);
    expect(update).toHaveBeenLastCalledWith("历史完整回复", false);
    player.start("");
    expect(update).toHaveBeenLastCalledWith("", false);
    expect(clock.frames.size).toBe(0);
  });
});
