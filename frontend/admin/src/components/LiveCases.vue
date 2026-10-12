<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { CaseInbox, caseApi } from "../services/cases";
import { can, currentStore, session, storeId } from "../state";
import SidePanel from "./SidePanel.vue";
import EmptyState from "./EmptyState.vue";
const inbox = reactive(new CaseInbox(caseApi));
const offset = ref(0),
  arrivalOffset = ref(0),
  arrival = ref(""),
  createChecked = ref(false),
  checked = ref(false);
const form = reactive({
  name: "",
  intention: "",
  reason: "",
  project_version_id: "",
});
const readable = computed(() => can("customer_read"));
const scope = computed(() => `${storeId.value}/${session.value?.token ?? ""}`);
function load() {
  return inbox.load(offset.value, arrivalOffset.value, can("appointment_read"));
}
watch(
  scope,
  () => {
    inbox.bind(storeId.value, session.value?.token ?? "");
    offset.value = arrivalOffset.value = 0;
    arrival.value = "";
    createChecked.value = false;
    if (readable.value) void load();
  },
  { immediate: true },
);
watch(
  () => inbox.selected,
  (row) => {
    checked.value = false;
    form.name = row?.current.name ?? "";
    form.intention = row?.current.intention ?? "";
    form.project_version_id = row?.current.project_version_id ?? "";
    form.reason = "";
  },
);
watch(
  () => JSON.stringify(form),
  () => (checked.value = false),
);
watch(arrival, () => (createChecked.value = false));
onBeforeUnmount(() => inbox.bind("", ""));
const date = (value: string) => new Date(value).toLocaleString("zh-CN");
const status = (value: string | null) =>
  value === "accept"
    ? "客户已确认当前意向"
    : value === "reject"
      ? "客户选择继续沟通"
      : "等待客户审阅";
async function create() {
  const row = inbox.arrivals.find((x) => x.id === arrival.value);
  if (row) {
    await inbox.create(row, createChecked.value);
    createChecked.value = false;
    if (!inbox.pending) await load();
  }
}
async function save() {
  await inbox.revise(
    { ...form, project_version_id: form.project_version_id || null },
    checked.value,
  );
}
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">CONTINUING THE CONVERSATION</p>
      <h1>从到店开始，更了解她的想法。</h1>
      <p>原意向、后续沟通与客户确认分开保留。</p>
    </div>
    <span class="soft-label">{{ currentStore?.name || "暂无授权门店" }}</span>
  </div>
  <p v-if="!readable" class="notice">
    此账号没有当前门店客户资料权限，请使用明确授权的咨询顾问账号。
  </p>
  <p v-if="inbox.error" role="alert" class="error-message">{{ inbox.error }}</p>
  <div v-if="inbox.pending" class="notice">
    <p>结果尚未核实，保留原内容和请求，避免重复创建或修改。</p>
    <button
      class="button secondary"
      :disabled="inbox.busy"
      @click="inbox.retry()"
    >
      核实并重试原档案操作
    </button>
  </div>
  <section v-if="readable" class="card">
    <div class="table-toolbar">
      <h2>到店咨询档案</h2>
      <button class="button secondary" :disabled="inbox.busy" @click="load()">
        刷新咨询档案
      </button>
    </div>
    <p v-if="inbox.busy" role="status">正在核实当前门店记录…</p>
    <div v-else-if="inbox.items.length" class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>客户</th>
            <th>原预约意向</th>
            <th>当前咨询方向</th>
            <th>确认状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in inbox.items" :key="row.id">
            <td>
              <strong>{{ row.current.name }}</strong
              ><small
                >{{ row.phone_masked }} ·
                {{ row.simulated ? "模拟档案" : "到店档案" }}</small
              >
            </td>
            <td>{{ row.initial.intention }}</td>
            <td>
              {{ row.current.intention
              }}<small>{{ row.current.project_title || "项目未定" }}</small>
            </td>
            <td>{{ status(row.current.decision) }}</td>
            <td>
              <button class="text-button" @click="inbox.open(row.id)">
                查看咨询档案
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else-if="!inbox.error"
      title="暂无到店咨询档案"
      description="从已经登记到店的预约建立独立档案，不按手机号合并其他客户。"
    />
    <div class="form-actions">
      <span>共 {{ inbox.total }} 条</span
      ><button
        class="text-button"
        :disabled="inbox.busy || offset === 0"
        @click="
          offset -= 25;
          load();
        "
      >
        上一页档案</button
      ><button
        class="text-button"
        :disabled="inbox.busy || offset + 25 >= inbox.total"
        @click="
          offset += 25;
          load();
        "
      >
        下一页档案
      </button>
    </div>
  </section>
  <section
    v-if="readable && can('customer_manage') && can('appointment_read')"
    class="card stack-form"
  >
    <h2>从到店预约开始</h2>
    <p>仅限已登记到店的预约，保留原申请作为来源。每份预约只创建一份档案。</p>
    <label
      >已到店预约<select
        v-model="arrival"
        :disabled="inbox.busy || !!inbox.pending"
      >
        <option value="">请选择</option>
        <option v-for="row in inbox.arrivals" :key="row.id" :value="row.id">
          {{ row.name }} · {{ row.phone_masked }} · {{ row.id }}
        </option>
      </select></label
    >
    <div class="form-actions">
      <span>共 {{ inbox.arrivalTotal }} 份已到店预约</span
      ><button
        class="text-button"
        :disabled="inbox.busy || arrivalOffset === 0"
        @click="
          arrivalOffset -= 25;
          arrival = '';
          load();
        "
      >
        上一页到店预约</button
      ><button
        class="text-button"
        :disabled="inbox.busy || arrivalOffset + 25 >= inbox.arrivalTotal"
        @click="
          arrivalOffset += 25;
          arrival = '';
          load();
        "
      >
        下一页到店预约
      </button>
    </div>
    <label class="checkbox-label"
      ><input
        v-model="createChecked"
        type="checkbox"
        :disabled="inbox.busy || !!inbox.pending"
      />确认基于这份到店预约建立咨询档案，保留原始意向</label
    >
    <button
      class="button primary"
      :disabled="inbox.busy || !!inbox.pending || !arrival || !createChecked"
      @click="create()"
    >
      建立到店咨询档案
    </button>
  </section>
  <SidePanel
    v-if="inbox.selected && !inbox.busy"
    :title="inbox.selected.current.name"
    :subtitle="
      inbox.selected.simulated ? '模拟到店档案 · 持久记录' : '到店咨询档案'
    "
    @close="inbox.close()"
  >
    <dl class="detail-list">
      <dt>来源预约</dt>
      <dd>{{ inbox.selected.appointment_id }}</dd>
      <dt>原预约称呼</dt>
      <dd>{{ inbox.selected.initial.name }}</dd>
      <dt>原预约意向</dt>
      <dd>{{ inbox.selected.initial.intention }}</dd>
      <dt>当前咨询方向</dt>
      <dd>
        {{ inbox.selected.current.intention }} ·
        {{ inbox.selected.current.project_title || "项目未定" }}
      </dd>
      <dt>客户确认</dt>
      <dd>
        {{ status(inbox.selected.current.decision) }} · 版本
        {{ inbox.selected.version }}
      </dd>
    </dl>
    <p class="notice">
      记录用于本次咨询。医疗评估、治疗同意、收费和合同仍需独立流程；不发送档案给模型。
    </p>
    <h3>咨询变化与确认历史</h3>
    <ol class="timeline">
      <li v-for="version in inbox.selected.history" :key="version.version">
        <strong
          >版本 {{ version.version }} · {{ date(version.recorded_at) }} ·
          {{
            version.source === "original_application"
              ? "原预约申请"
              : "顾问记录"
          }}</strong
        >
        <p>
          {{ version.name }} · {{ version.intention }} ·
          {{ version.project_title || "项目未定" }}
        </p>
        <p>{{ version.reason }}</p>
        <small
          >{{ status(version.decision)
          }}{{
            version.confirmed_at ? " · " + date(version.confirmed_at) : ""
          }}</small
        >
      </li>
    </ol>
    <form
      v-if="can('customer_manage') && !inbox.pending"
      class="stack-form"
      @submit.prevent="save()"
    >
      <h3>追加本次沟通版本</h3>
      <label
        >到店称呼<input v-model="form.name" required maxlength="40" /></label
      ><label
        >本次咨询意向<textarea
          v-model="form.intention"
          required
          maxlength="300"
          rows="3"
        ></textarea>
      </label>
      <label
        >咨询项目入口<select v-model="form.project_version_id">
          <option value="">不确定项目，继续沟通</option>
          <option
            v-for="project in inbox.options"
            :key="project.id"
            :value="project.id"
          >
            {{ project.title }}{{ project.simulated ? " · 模拟目录" : "" }}
          </option>
        </select></label
      >
      <label
        >给客户审阅的变更说明<textarea
          v-model="form.reason"
          required
          maxlength="300"
          rows="2"
          placeholder="说明咨询方向为什么变化，不填写员工内部备注或医疗诊断"
        ></textarea>
      </label>
      <label class="checkbox-label"
        ><input
          v-model="checked"
          type="checkbox"
        />确认追加新版本，等待客户本人审阅；既有确认记录保留</label
      ><button class="button primary" :disabled="!checked">
        保存新版本，等待客户确认
      </button>
    </form>
  </SidePanel>
</template>
