import { describe, expect, it } from "vitest";
import { filterProjects } from "./domain";
import { project } from "./tests/fixtures";

describe("当前公开目录过滤", () => {
  it("组合分类和关键词过滤，未知项目不返回结果", () => {
    expect(filterProjects([project], "care", "补水").map((p) => p.key)).toEqual(
      ["hydration"],
    );
    expect(filterProjects([project], "medical", "补水")).toEqual([]);
    expect(filterProjects([project], "all", "未提供的项目")).toEqual([]);
  });
  it("没有服务端公开记录时保持空目录，不使用本地示例补齐", () => {
    expect(filterProjects([], "all")).toEqual([]);
  });
});
