import { createRouter, createWebHashHistory } from "vue-router";
import { session } from "./state";
import LoginPage from "./views/LoginPage.vue";
import AdminLayout from "./layouts/AdminLayout.vue";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/login", component: LoginPage },
    {
      path: "/",
      component: AdminLayout,
      children: [
        {
          path: "",
          name: "dashboard",
          component: () => import("./views/DashboardPage.vue"),
          meta: { title: "工作台" },
        },
        {
          path: "appointments",
          component: () => import("./views/AppointmentsPage.vue"),
          meta: { title: "预约管理" },
        },
        {
          path: "customers",
          component: () => import("./views/CustomersPage.vue"),
          meta: { title: "客户跟进" },
        },
        {
          path: "followups",
          component: () => import("./views/FollowupsPage.vue"),
          meta: { title: "回访管理" },
        },
        {
          path: "projects",
          component: () => import("./views/ProjectsPage.vue"),
          meta: { title: "项目目录" },
        },
        {
          path: "knowledge",
          component: () => import("./views/KnowledgePage.vue"),
          meta: { title: "知识管理" },
        },
        {
          path: "marketing",
          component: () => import("./views/MarketingPage.vue"),
          meta: { title: "AI 营销创作" },
        },
        {
          path: "demo-materials",
          component: () => import("./views/DemoMaterialsPage.vue"),
          meta: { title: "演示资料" },
        },
        {
          path: "settings",
          component: () => import("./views/SettingsPage.vue"),
          meta: { title: "账号与门店" },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
router.beforeEach((to) => {
  if (to.path !== "/login" && !session.value) return "/login";
  if (to.path === "/login" && session.value) return "/";
});
