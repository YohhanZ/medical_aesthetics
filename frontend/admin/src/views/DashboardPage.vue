<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  ArrowRight,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Users,
} from "lucide-vue-next";
import { can, currentStore, isDemo, session, storeId } from "../state";
import { appointmentApi } from "../services/appointments";
import { caseApi } from "../services/cases";
import { demoData, bookingLabels } from "../services/demo";
import { listKnowledge } from "../services/knowledge";
import { errorText } from "../services/api";
import type { Booking, Knowledge } from "../types";
import EmptyState from "../components/EmptyState.vue";
const rows = computed(() =>
  isDemo.value ? (demoData[storeId.value]?.bookings ?? []) : liveRows.value,
);
const liveRows = ref<Booking[]>([]),
  counts = ref<Record<string, number> | null>(null),
  caseTotal = ref<number | null>(null);
const knowledge = ref<Knowledge[]>([]),
  error = ref(""),
  loading = ref(false);
const pending = computed(() =>
  rows.value.filter((r) => r.status === "pending_store_confirmation"),
);
const cards = computed(() => [
  {
    label: "待确认申请",
    value: isDemo.value
      ? pending.value.length
      : (counts.value?.pending_store_confirmation ?? (counts.value ? 0 : "—")),
    note: "等待门店核实到店时间",
    icon: CalendarDays,
  },
  {
    label: "已确认预约",
    value: isDemo.value
      ? rows.value.filter((r) => r.status === "confirmed").length
      : (counts.value?.confirmed ?? (counts.value ? 0 : "—")),
    note: "为客户提前做好准备",
    icon: CheckCircle2,
  },
  {
    label: "跟进客户",
    value: isDemo.value
      ? (demoData[storeId.value]?.customers.length ?? 0)
      : (caseTotal.value ?? "—"),
    note: isDemo.value
      ? "留意需求变化与咨询进展"
      : can("customer_read")
        ? "当前门店的到店咨询档案"
        : "此账号未获客户资料权限",
    icon: Users,
  },
  {
    label: "待审核知识",
    value:
      loading.value ||
      error.value ||
      (!isDemo.value && !can("knowledge_review"))
        ? "—"
        : knowledge.value.filter((r) => r.status === "draft").length,
    note: isDemo.value ? "合成知识演练" : "当前知识页的待审版本",
    icon: BookOpen,
  },
]);
let epoch = 0;
async function load() {
  const generation = ++epoch,
    scopeStore = storeId.value,
    token = session.value?.token ?? "";
  liveRows.value = [];
  counts.value = null;
  caseTotal.value = null;
  knowledge.value = [];
  if (!currentStore.value) return;
  error.value = "";
  loading.value = true;
  try {
    if (
      isDemo.value ||
      can("knowledge_author") ||
      can("knowledge_review") ||
      can("knowledge_publish")
    ) {
      const result = await listKnowledge();
      if (generation === epoch) knowledge.value = result.items;
    }
    if (!isDemo.value && can("appointment_read")) {
      const result = await appointmentApi.list(
        scopeStore,
        token,
        "pending_store_confirmation",
        0,
      );
      if (generation === epoch) {
        counts.value = result.counts;
        liveRows.value = result.items.map((row) => ({
          id: row.id,
          customer: row.name,
          intent: row.intention,
          expected: row.desired_at,
          confirmed: row.confirmed_at ?? "",
          status: row.state as Booking["status"],
          source: "客户申请",
          events: [],
        }));
      }
    }
    if (!isDemo.value && can("customer_read")) {
      const result = await caseApi.list(scopeStore, token, 0);
      if (generation === epoch) caseTotal.value = result.total;
    }
  } catch (e) {
    if (generation === epoch) {
      error.value = errorText(e);
      counts.value = null;
      caseTotal.value = null;
      liveRows.value = [];
    }
  } finally {
    if (generation === epoch) loading.value = false;
  }
}
watch(
  () => `${storeId.value}/${session.value?.token ?? ""}/${isDemo.value}`,
  () => void load(),
  { immediate: true },
);
onBeforeUnmount(() => epoch++);
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">YOUR DAILY OVERVIEW</p>
      <h1>把服务，准备得更周到。</h1>
      <p>{{ currentStore?.name || "先由机构管理员授予门店权限" }} · 运营概览</p>
    </div>
    <RouterLink to="/appointments" class="button primary"
      >查看预约 <ArrowRight :size="16"
    /></RouterLink>
  </div>
  <p v-if="error" class="error-message" role="alert">
    {{ error }} <button class="text-button" @click="load">重新加载</button>
  </p>
  <div class="stat-grid">
    <article v-for="card in cards" :key="card.label" class="stat-card">
      <div>
        <span>{{ card.label }}</span
        ><component :is="card.icon" :size="19" />
      </div>
      <strong>{{ card.value }}</strong>
      <p>{{ card.note }}</p>
    </article>
  </div>
  <div class="dashboard-grid">
    <section class="card">
      <header class="card-heading">
        <div>
          <h2>接下来，需要你</h2>
          <p>及时回应客户的到店意愿</p>
        </div>
        <RouterLink to="/appointments" class="text-button"
          >全部申请 <ArrowRight :size="15"
        /></RouterLink>
      </header>
      <div v-if="pending.length" class="task-list">
        <RouterLink
          v-for="row in pending"
          :key="row.id"
          to="/appointments"
          class="task-row"
          ><span class="task-icon"><CalendarDays :size="20" /></span>
          <div>
            <strong>{{ row.customer }}</strong>
            <p>{{ row.intent }}</p>
          </div>
          <span class="status amber">{{
            bookingLabels[row.status]
          }}</span></RouterLink
        >
      </div>
      <EmptyState
        v-else
        :title="
          isDemo || can('appointment_read')
            ? '暂时没有待确认申请'
            : '此账号没有预约读取权限'
        "
        :description="
          isDemo
            ? '可以切换门店，或查看已有预约。'
            : '仅显示当前明确授权门店的申请；完整记录请打开预约管理。'
        "
      />
      <div class="card-bottom">
        <Clock3 :size="15" /><span>线上申请后，需要门店确认时间。</span>
      </div>
    </section>
    <section class="card care-card">
      <span class="eyebrow">CONSISTENT CARE</span>
      <h2>好的咨询，<br />从可靠的知识开始。</h2>
      <p>
        让项目介绍、沟通口径与到店流程保持一致。每个版本，都有清晰的审核与来源。
      </p>
      <RouterLink to="/knowledge" class="button light"
        >管理咨询知识 <ArrowRight :size="16"
      /></RouterLink>
      <div class="care-orbit"><BookOpen :size="62" :stroke-width="1" /></div>
    </section>
  </div>
  <section class="card workflow-card">
    <header class="card-heading">
      <div>
        <h2>从咨询，到到店</h2>
        <p>保留每一步需求变化，具体项目由客户确认</p>
      </div>
    </header>
    <div class="workflow">
      <div
        v-for="(step, i) in [
          { title: '了解需求', text: '先解答客户的问题' },
          { title: '确认申请', text: '客户明确确认申请内容' },
          { title: '门店接待', text: '核实到店时间与安排' },
          { title: '继续咨询', text: '记录后续与最终意向' },
        ]"
        :key="step.title"
      >
        <span>0{{ i + 1 }}</span
        ><strong>{{ step.title }}</strong>
        <p>{{ step.text }}</p>
      </div>
    </div>
  </section>
</template>
