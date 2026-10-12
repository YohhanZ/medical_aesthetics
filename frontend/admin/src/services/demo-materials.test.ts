import { describe, expect, it, vi } from "vitest";
import {
  DemoMaterialsView,
  type DemoMaterialsPack,
  type DemoMaterialsReader,
} from "./demo-materials";
import { ApiError } from "./api";
const pack = { pack_id: "SIM-TEST", simulated: true } as DemoMaterialsPack;
describe("演示资料授权视图", () => {
  it("clears old material and discards a late response after changing the store", async () => {
    let finish!: (value: DemoMaterialsPack) => void;
    const read = vi.fn<DemoMaterialsReader>().mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = new DemoMaterialsView(read);
    view.bind("shanghai", "token-a");
    const loading = view.load();
    view.bind("hangzhou", "token-b");
    finish(pack);
    await loading;
    expect(view.pack).toBeNull();
    expect(view.busy).toBe(false);
  });
  it("a revoked scope never leaves previously displayed data available for download", async () => {
    const read = vi
      .fn<DemoMaterialsReader>()
      .mockResolvedValueOnce(pack)
      .mockRejectedValueOnce(new ApiError("store_permission_denied", "", 403));
    const view = new DemoMaterialsView(read);
    view.bind("shanghai", "token-a");
    await view.load();
    expect(view.pack).toBe(pack);
    await view.load();
    expect(view.pack).toBeNull();
    expect(view.error).toContain("权限");
    expect(view.busy).toBe(false);
  });
});
