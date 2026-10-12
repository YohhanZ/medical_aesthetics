<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  BookOpen,
  CalendarDays,
  ChevronDown,
  LayoutDashboard,
  Leaf,
  LogOut,
  Menu,
  Settings2,
  Sprout,
  Users,
  X,
} from "lucide-vue-next";
import { currentStore, isDemo, session, storeId } from "../state";
import { logout } from "../services/auth";
const route = useRoute(),
  router = useRouter(),
  mobileOpen = ref(false),
  leaving = ref(false);
const mobileQuery = window.matchMedia("(max-width: 850px)");
const isMobile = ref(mobileQuery.matches);
const syncViewport = () => {
  isMobile.value = mobileQuery.matches;
};
onMounted(() => mobileQuery.addEventListener("change", syncViewport));
onBeforeUnmount(() => mobileQuery.removeEventListener("change", syncViewport));
const links = [
  { path: "/", label: "工作台", icon: LayoutDashboard },
  { path: "/appointments", label: "预约管理", icon: CalendarDays },
  { path: "/customers", label: "客户跟进", icon: Users },
  { path: "/followups", label: "回访管理", icon: CalendarDays },
  { path: "/projects", label: "项目目录", icon: Sprout },
  { path: "/knowledge", label: "知识管理", icon: BookOpen },
  { path: "/demo-materials", label: "演示资料", icon: BookOpen },
  { path: "/settings", label: "账号与门店", icon: Settings2 },
];
const title = computed(() => route.meta.title || "工作台");
watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false;
  },
);
watch(session, (value) => {
  if (!value) router.replace("/login");
});
async function exit() {
  leaving.value = true;
  try {
    await logout();
  } catch {
    /* local session always cleared */
  } finally {
    leaving.value = false;
    router.replace("/login");
  }
}
</script>
<template>
  <div id="admin-shell" class="admin-shell">
    <button
      v-if="mobileOpen"
      class="mobile-scrim"
      aria-label="关闭导航"
      @click="mobileOpen = false"
    ></button>
    <aside
      class="sidebar"
      :class="{ open: mobileOpen }"
      :inert="isMobile && !mobileOpen"
    >
      <RouterLink to="/" class="brand"
        ><Leaf :size="26" /><span
          >美丽田园<small>运营工作台</small></span
        ></RouterLink
      ><button
        class="mobile-close icon-button"
        aria-label="关闭菜单"
        @click="mobileOpen = false"
      >
        <X :size="20" />
      </button>
      <div class="sidebar-caption">门店运营</div>
      <nav aria-label="后台导航">
        <RouterLink
          v-for="link in links"
          :key="link.path"
          :to="link.path"
          :class="{ active: route.path === link.path }"
          ><component :is="link.icon" :size="19" />{{ link.label
          }}<span v-if="link.path === '/knowledge'" class="nav-dot"></span
        ></RouterLink>
      </nav>
      <div class="sidebar-footer">
        <span class="avatar">{{
          session?.profile.username.slice(0, 1).toUpperCase()
        }}</span>
        <div>
          <strong>{{ session?.profile.username }}</strong
          ><small>{{ isDemo ? "本地界面演练" : "机构员工" }}</small>
        </div>
        <button
          class="icon-button"
          aria-label="退出登录"
          :disabled="leaving"
          @click="exit"
        >
          <LogOut :size="17" />
        </button>
      </div>
    </aside>
    <div class="main-wrap">
      <header class="topbar">
        <div class="breadcrumb">
          <button
            class="mobile-menu icon-button"
            aria-label="打开菜单"
            @click="mobileOpen = true"
          >
            <Menu :size="21" /></button
          ><span>机构运营</span><span class="slash">/</span
          ><strong>{{ title }}</strong>
        </div>
        <div class="topbar-right">
          <span class="mode-indicator" :class="{ demo: isDemo }">{{
            isDemo ? "界面演练" : "已登录"
          }}</span>
          <div class="store-select">
            <select
              v-model="storeId"
              aria-label="当前门店"
              :disabled="!session?.profile.stores.length"
            >
              <option v-if="!session?.profile.stores.length" value="">
                暂无授权门店
              </option>
              <option
                v-for="store in session?.profile.stores"
                :key="store.id"
                :value="store.id"
              >
                {{ store.name }}
              </option></select
            ><ChevronDown :size="14" />
          </div>
        </div>
      </header>
      <div v-if="isDemo" class="environment-banner">
        本地演练 · 所有客户、预约和运营资料均为合成数据，操作不会写入机构业务。
      </div>
      <div v-else-if="currentStore?.simulated" class="environment-banner">
        当前为模拟门店 · 操作记录保存在本地数据库，资料与业务保留模拟标识。
      </div>
      <main class="page-content">
        <RouterView :key="`${route.path}:${storeId}`" />
      </main>
    </div>
  </div>
</template>
