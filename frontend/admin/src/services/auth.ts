import { clearSession, demoAvailable, setSession, session } from "../state";
import type { Profile } from "../types";
import { request } from "./api";
import { demoProfile } from "./demo";

export async function login(username: string, password: string) {
  clearSession();
  const result = await request<{ access_token: string }>("/staff-sessions", {
    method: "POST",
    body: { username, password },
  });
  try {
    const profile = await request<Profile>("/staff/me", {
      token: result.access_token,
    });
    setSession({ mode: "live", token: result.access_token, profile });
  } catch (error) {
    await request("/staff-sessions/logout", {
      method: "POST",
      token: result.access_token,
    }).catch(() => undefined);
    throw error;
  }
}
export function startDemo() {
  if (!demoAvailable(import.meta.env.DEV))
    throw new Error("当前构建不开放界面演练");
  setSession({ mode: "demo", token: "", profile: demoProfile });
}
export async function logout() {
  try {
    if (session.value?.mode === "live")
      await request("/staff-sessions/logout", { method: "POST" });
  } finally {
    clearSession();
  }
}
