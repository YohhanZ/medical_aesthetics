<script setup lang="ts">
import { computed, ref } from "vue";
import { Search } from "lucide-vue-next";
import { isDemo, storeId } from "../state";
import { demoData } from "../services/demo";
import type { Customer } from "../types";
import EmptyState from "../components/EmptyState.vue";
import SidePanel from "../components/SidePanel.vue";
import LiveCases from "../components/LiveCases.vue";
const query = ref(""),
  selected = ref<Customer | null>(null),
  note = ref(""),
  error = ref("");
const rows = computed(() =>
  (isDemo.value ? (demoData[storeId.value]?.customers ?? []) : []).filter((r) =>
    `${r.name}${r.currentIntent}`.includes(query.value.trim()),
  ),
);
function open(row: Customer) {
  selected.value = row;
  note.value = "";
  error.value = "";
}
function addNote() {
  if (!selected.value || !isDemo.value) return;
  if (!note.value.trim()) {
    error.value = "请填写本次需求变化或跟进内容。";
    return;
  }
  selected.value.history.push({
    time: "本次跟进 · 演练",
    text: note.value.trim().slice(0, 1000),
  });
  selected.value.currentIntent = note.value.trim().slice(0, 100);
  note.value = "";
  error.value = "";
}
</script>
<template>
  <LiveCases v-if="!isDemo" />
  <template v-else>
    <div class="page-heading">
      <div>
        <p class="eyebrow">CUSTOMER CARE</p>
        <h1>了解变化，延续每一次沟通。</h1>
        <p>最初意向与后续需求分别保留，最终项目需客户明确确认。</p>
      </div>
    </div>
    <section class="card">
      <div class="table-toolbar">
        <h2>客户跟进</h2>
        <label class="search-field"
          ><Search :size="17" /><input
            v-model="query"
            aria-label="搜索客户"
            placeholder="搜索客户或咨询方向"
        /></label>
      </div>
      <div v-if="rows.length" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>客户</th>
              <th>最初意向</th>
              <th>当前咨询方向</th>
              <th>服务进度</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>
                <strong>{{ row.name }}</strong
                ><small>{{ row.id }} · 合成记录</small>
              </td>
              <td>{{ row.initialIntent }}</td>
              <td>{{ row.currentIntent }}</td>
              <td>
                <span class="status green">{{ row.stage }}</span>
              </td>
              <td>
                <button class="text-button" @click="open(row)">查看跟进</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else
        :title="isDemo ? '暂无符合条件的客户' : '客户跟进等待业务接口接入'"
        :description="
          isDemo
            ? '可切换门店或清空搜索。'
            : '不依据手机号合并身份；真实档案读取和更新由服务端权限控制。'
        "
      />
    </section>
    <SidePanel
      v-if="selected"
      :title="selected.name"
      subtitle="合成客户 · 咨询意向记录"
      @close="selected = null"
      ><dl class="detail-list">
        <dt>最初意向</dt>
        <dd>{{ selected.initialIntent }}</dd>
        <dt>当前方向</dt>
        <dd>{{ selected.currentIntent }}</dd>
        <dt>最终项目</dt>
        <dd>尚无客户最终确认</dd>
      </dl>
      <h3>咨询与跟进历史</h3>
      <ol class="timeline">
        <li v-for="(event, i) in selected.history" :key="i">
          <strong>{{ event.time }}</strong>
          <p>{{ event.text }}</p>
        </li>
      </ol>
      <form class="stack-form" @submit.prevent="addNote">
        <label
          >追加跟进记录<textarea
            v-model="note"
            rows="4"
            maxlength="1000"
            placeholder="记录本次咨询方向或需求变化，不将员工判断视为客户最终确认。"
          ></textarea>
        </label>
        <p v-if="error" class="error-message" role="alert">{{ error }}</p>
        <button class="button primary">保存演练记录</button>
        <p class="hint">仅保存在当前页面会话内，刷新后恢复。</p>
      </form></SidePanel
    >
  </template>
</template>
