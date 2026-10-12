import { computed, ref } from "vue";
import type { Permission, Session } from "./types";

export const session = ref<Session | null>(null);
export const storeId = ref("");
export const currentStore = computed(() =>
  session.value?.profile.stores.find((s) => s.id === storeId.value),
);
export const isDemo = computed(() => session.value?.mode === "demo");
export function can(permission: Permission) {
  return Boolean(currentStore.value?.permissions.includes(permission));
}
export function setSession(value: Session) {
  session.value = value;
  storeId.value = value.profile.stores[0]?.id ?? "";
}
export function clearSession() {
  session.value = null;
  storeId.value = "";
}
export function demoAvailable(development: boolean) {
  return development;
}
