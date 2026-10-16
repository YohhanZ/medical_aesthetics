import { describe, expect, it, vi } from "vitest";
import type { PublicStore } from "../types";
import { NearbyStores, distanceLabel, rankStores } from "./nearby-stores";

const stores: PublicStore[] = [
  {
    code: "shanghai",
    name: "模拟上海店",
    simulated: true,
    coordinate_system: "WGS84",
    latitude: 31.23,
    longitude: 121.47,
  },
  {
    code: "hangzhou",
    name: "模拟杭州店",
    simulated: true,
    coordinate_system: "WGS84",
    latitude: 30.25,
    longitude: 120.15,
  },
];
const position = {
  coords: { latitude: 30.251, longitude: 120.151, accuracy: 100 },
} as GeolocationPosition;

describe("附近门店匹配", () => {
  it("按直线距离排序，坐标缺失、错误或坐标系不明的门店不参与", () => {
    const rows = rankStores(
      [
        ...stores,
        { ...stores[0]!, code: "missing", latitude: null },
        { ...stores[0]!, code: "invalid", latitude: NaN },
        { ...stores[0]!, code: "range", longitude: 181 },
        { ...stores[0]!, code: "unknown", coordinate_system: undefined },
      ],
      position.coords,
    );
    expect(rows.map((row) => row.store.code)).toEqual(["hangzhou", "shanghai"]);
    expect(rows[0]!.kilometers).toBeGreaterThan(0.1);
    expect(rows[0]!.kilometers).toBeLessThan(0.2);
    expect(rows[1]!.kilometers).toBeGreaterThan(150);
    expect(rankStores(stores, { latitude: 91, longitude: 0 })).toEqual([]);
    expect(stores[0]!.code).toBe("shanghai"); // Does not mutate the server's fallback ordering.
  });
  it("跨日期变更线仍按较短距离计算，并稳定处理重合门店", () => {
    const rows = rankStores(
      [
        { ...stores[0]!, code: "b", latitude: 0, longitude: -179.9 },
        { ...stores[0]!, code: "a", latitude: 0, longitude: -179.9 },
      ],
      { latitude: 0, longitude: 179.9 },
    );
    expect(rows.map((row) => row.store.code)).toEqual(["a", "b"]);
    expect(rows[0]!.kilometers).toBeCloseTo(22.239, 2);
    expect(distanceLabel(0)).toBe("不足 100 米");
    expect(distanceLabel(0.351)).toBe("约 350 米");
    expect(distanceLabel(2.34)).toBe("约 2.3 公里");
  });
  it("只请求一次位置，返回距离而不保留原始用户坐标", async () => {
    const getCurrentPosition = vi.fn<Geolocation["getCurrentPosition"]>(
      (success) => success(position),
    );
    const nearby = new NearbyStores();
    await nearby.locate(stores, { getCurrentPosition }, true);
    expect(nearby.matches[0]!.store.code).toBe("hangzhou");
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(getCurrentPosition.mock.calls[0]![2]).toMatchObject({
      timeout: 10000,
      maximumAge: 60000,
    });
    expect(
      Object.keys(nearby).some((key) =>
        /position|coords|latitude|longitude/.test(key),
      ),
    ).toBe(false);
    expect(nearby.busy).toBe(false);
  });
  it("拒绝授权、超时、不安全上下文与未配置门店均保留手动选店", async () => {
    const nearby = new NearbyStores();
    const getCurrentPosition = vi.fn<Geolocation["getCurrentPosition"]>(
      (_success, failure) => failure?.({ code: 1 } as GeolocationPositionError),
    );
    await nearby.locate(stores, { getCurrentPosition }, true);
    expect(nearby.error).toContain("未获得定位授权");
    getCurrentPosition.mockImplementationOnce((_success, failure) =>
      failure?.({ code: 3 } as GeolocationPositionError),
    );
    await nearby.locate(stores, { getCurrentPosition }, true);
    expect(nearby.error).toContain("定位超时");
    await nearby.locate(stores, { getCurrentPosition }, false);
    expect(nearby.error).toContain("安全连接");
    await nearby.locate(
      [{ code: "missing", name: "缺失位置", simulated: true }],
      { getCurrentPosition },
      true,
    );
    expect(nearby.error).toContain("尚未配置");
    expect(getCurrentPosition).toHaveBeenCalledTimes(2);
  });
  it("定位过程中切换身份会忽略迟到结果，重复点击不启动第二次请求", async () => {
    let finish!: PositionCallback;
    const getCurrentPosition = vi.fn<Geolocation["getCurrentPosition"]>(
      (success) => {
        finish = success;
      },
    );
    const nearby = new NearbyStores();
    const pending = nearby.locate(stores, { getCurrentPosition }, true);
    await nearby.locate(stores, { getCurrentPosition }, true);
    nearby.reset();
    finish(position);
    await pending;
    expect(nearby.matches).toEqual([]);
    expect(nearby.busy).toBe(false);
    expect(getCurrentPosition).toHaveBeenCalledTimes(1);
  });
});
