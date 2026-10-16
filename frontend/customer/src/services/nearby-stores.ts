import type { PublicStore } from "../types";

export interface Point {
  latitude: number;
  longitude: number;
}
export interface StoreDistance {
  store: PublicStore;
  kilometers: number;
}
function validPoint(point: Point): boolean {
  return (
    Number.isFinite(point.latitude) &&
    Number.isFinite(point.longitude) &&
    Math.abs(point.latitude) <= 90 &&
    Math.abs(point.longitude) <= 180
  );
}
export function rankStores(
  stores: PublicStore[],
  point: Point,
): StoreDistance[] {
  if (!validPoint(point)) return [];
  const radians = (degrees: number) => (degrees * Math.PI) / 180;
  return stores
    .flatMap((store) => {
      if (
        store.coordinate_system !== "WGS84" ||
        typeof store.latitude !== "number" ||
        typeof store.longitude !== "number" ||
        !validPoint({ latitude: store.latitude, longitude: store.longitude })
      )
        return [];
      const a =
        Math.sin(radians(store.latitude - point.latitude) / 2) ** 2 +
        Math.cos(radians(point.latitude)) *
          Math.cos(radians(store.latitude)) *
          Math.sin(radians(store.longitude - point.longitude) / 2) ** 2;
      const kilometers =
        6371.0088 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a))));
      return [{ store, kilometers }];
    })
    .sort(
      (a, b) =>
        a.kilometers - b.kilometers || a.store.code.localeCompare(b.store.code),
    );
}
export function distanceLabel(kilometers: number): string {
  return kilometers < 0.1
    ? "不足 100 米"
    : kilometers < 1
      ? `约 ${Math.round((kilometers * 1000) / 10) * 10} 米`
      : `约 ${kilometers < 10 ? kilometers.toFixed(1) : Math.round(kilometers)} 公里`;
}

export class NearbyStores {
  busy = false;
  error = "";
  matches: StoreDistance[] = [];
  lowAccuracy = false;
  private epoch = 0;
  reset() {
    this.epoch++;
    this.busy = false;
    this.error = "";
    this.matches = [];
    this.lowAccuracy = false;
  }
  async locate(
    stores: PublicStore[],
    geolocation: Pick<Geolocation, "getCurrentPosition"> | undefined,
    secure: boolean,
  ) {
    if (this.busy) return;
    this.reset();
    if (!secure || !geolocation) {
      this.error =
        "当前浏览器无法定位，请手动选店；定位需要安全连接和浏览器支持。";
      return;
    }
    if (
      !stores.some(
        (store) => rankStores([store], { latitude: 0, longitude: 0 }).length,
      )
    ) {
      this.error = "门店位置尚未配置，请先手动选择。";
      return;
    }
    const epoch = this.epoch;
    this.busy = true;
    try {
      // Coordinates are used transiently here, never persisted or sent to the API/model.
      const position = await new Promise<GeolocationPosition>(
        (resolve, reject) => {
          geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: false,
            maximumAge: 60000,
            timeout: 10000,
          });
        },
      );
      if (epoch !== this.epoch) return;
      this.matches = rankStores(stores, position.coords);
      this.lowAccuracy =
        !Number.isFinite(position.coords.accuracy) ||
        position.coords.accuracy > 5000;
      if (!this.matches.length)
        this.error = "本次位置暂不可用，请重试或手动选店。";
    } catch (error) {
      if (epoch !== this.epoch) return;
      const code =
        typeof error === "object" && error !== null && "code" in error
          ? error.code
          : 0;
      this.error =
        code === 1
          ? "未获得定位授权，你仍可以手动选店。"
          : code === 3
            ? "定位超时，请重试或手动选店。"
            : "暂时无法获取位置，请手动选店。";
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
}
