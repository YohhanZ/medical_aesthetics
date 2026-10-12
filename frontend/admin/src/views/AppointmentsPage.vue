<script setup lang="ts">
import { computed, ref } from "vue";
import { Search } from "lucide-vue-next";
import { currentStore, isDemo, storeId } from "../state";
import { bookingLabels, demoData, transitionBooking } from "../services/demo";
import type { Booking, BookingStatus } from "../types";
import EmptyState from "../components/EmptyState.vue";
import SidePanel from "../components/SidePanel.vue";
import LiveAppointments from "../components/LiveAppointments.vue";
const query = ref(""),
  filter = ref<BookingStatus | "all">("all"),
  selected = ref<Booking | null>(null);
const confirmedTime = ref(""),
  checked = ref(false),
  error = ref("");
const rows = computed(() =>
  (isDemo.value ? (demoData[storeId.value]?.bookings ?? []) : []).filter(
    (r) =>
      (filter.value === "all" || r.status === filter.value) &&
      `${r.customer}${r.intent}${r.id}`.includes(query.value.trim()),
  ),
);
function open(row: Booking) {
  selected.value = row;
  confirmedTime.value = row.expected.replace(" ", "T");
  checked.value = false;
  error.value = "";
}
function act(action: "confirm" | "arrive" | "decline") {
  if (!isDemo.value || !selected.value) return;
  error.value = "";
  try {
    transitionBooking(
      selected.value,
      action,
      confirmedTime.value.replace("T", " "),
      checked.value,
    );
    checked.value = false;
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>
<template>
  <LiveAppointments v-if="!isDemo" />
  <template v-else>
    <div class="page-heading">
      <div>
        <p class="eyebrow">APPOINTMENTS</p>
        <h1>每一份到店意愿，认真回应。</h1>
        <p>确认时间、安排接待，保持清晰的服务状态。</p>
      </div>
      <span class="soft-label">{{ currentStore?.name || "暂无授权门店" }}</span>
    </div>
    <section class="card">
      <div class="table-toolbar">
        <div class="tabs">
          <button :class="{ active: filter === 'all' }" @click="filter = 'all'">
            全部</button
          ><button
            :class="{ active: filter === 'pending_store_confirmation' }"
            @click="filter = 'pending_store_confirmation'"
          >
            待确认</button
          ><button
            :class="{ active: filter === 'confirmed' }"
            @click="filter = 'confirmed'"
          >
            已确认</button
          ><button
            :class="{ active: filter === 'arrived' }"
            @click="filter = 'arrived'"
          >
            已到店
          </button>
        </div>
        <label class="search-field"
          ><Search :size="17" /><input
            v-model="query"
            aria-label="搜索预约"
            placeholder="搜索客户、意向或编号"
        /></label>
      </div>
      <div v-if="rows.length" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>客户 / 申请</th>
              <th>咨询意向</th>
              <th>期望到店时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <strong>{{ row.customer }}</strong
                ><small>{{ row.id }} · 合成记录</small>
              </td>
              <td>{{ row.intent }}</td>
              <td>{{ row.expected }}</td>
              <td>
                <span
                  class="status"
                  :class="
                    row.status === 'pending_store_confirmation'
                      ? 'amber'
                      : 'green'
                  "
                  >{{ bookingLabels[row.status] }}</span
                >
              </td>
              <td>
                <button class="text-button" @click="open(row)">
                  查看与处理
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else
        :title="isDemo ? '没有符合条件的预约' : '预约管理等待业务接口接入'"
        :description="
          isDemo
            ? '试试其他状态或关键词。'
            : '接入后将展示本门店真实申请，并通过后端校验确认、版本和幂等。'
        "
      />
    </section>
    <SidePanel
      v-if="selected"
      :title="selected.customer"
      subtitle="模拟预约 · 不写入机构业务"
      @close="selected = null"
      ><div class="detail-summary">
        <span class="status amber">{{ bookingLabels[selected.status] }}</span>
        <h3>{{ selected.intent }}</h3>
        <p>申请 {{ selected.id }}</p>
      </div>
      <dl class="detail-list">
        <dt>期望时间</dt>
        <dd>{{ selected.expected }}</dd>
        <dt>确认时间</dt>
        <dd>{{ selected.confirmed || "尚未确认" }}</dd>
        <dt>来源</dt>
        <dd>{{ selected.source }}</dd>
      </dl>
      <h3>处理记录</h3>
      <ol class="timeline">
        <li v-for="(event, i) in selected.events" :key="i">{{ event }}</li>
      </ol>
      <form
        v-if="selected.status === 'pending_store_confirmation'"
        class="stack-form"
        @submit.prevent="act('confirm')"
      >
        <h3>核实到店时间</h3>
        <label
          >门店确认时间<input
            v-model="confirmedTime"
            type="datetime-local"
            required
            @input="checked = false" /></label
        ><label class="checkbox-label"
          ><input
            v-model="checked"
            type="checkbox"
          />已核实本次到店安排（本地演练）</label
        >
        <p v-if="error" class="error-message" role="alert">{{ error }}</p>
        <div class="form-actions">
          <button
            type="button"
            class="button secondary"
            @click="act('decline')"
          >
            暂无法接待</button
          ><button class="button primary">确认时间</button>
        </div>
      </form>
      <div v-else-if="selected.status === 'confirmed'" class="stack-form">
        <label class="checkbox-label"
          ><input
            v-model="checked"
            type="checkbox"
          />已核实客户实际到店（本地演练）</label
        >
        <p v-if="error" class="error-message" role="alert">{{ error }}</p>
        <button class="button primary" @click="act('arrive')">登记到店</button>
      </div></SidePanel
    >
  </template>
</template>
