<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { RefreshCw } from "lucide-vue-next";
import RefinedSelect from "../../../shared/components/RefinedSelect.vue";
import { can, currentStore, session, storeId } from "../state";
import {
  AppointmentInbox,
  appointmentApi,
  appointmentLabels,
  reasonLabels,
} from "../services/appointments";
import SidePanel from "./SidePanel.vue";
import EmptyState from "./EmptyState.vue";
import TablePagination from "./TablePagination.vue";
const inbox = reactive(new AppointmentInbox(appointmentApi));
const state = ref(""),
  offset = ref(0),
  checked = ref(false),
  availability = ref(false),
  reason = ref(""),
  newTime = ref(""),
  changeAvailable = ref(false),
  changeChecked = ref(false),
  identityChecked = ref(false),
  arrivalChecked = ref(false);
const readable = computed(() => can("appointment_read"));
const scope = computed(() => `${storeId.value}/${session.value?.token ?? ""}`);
const stateOptions = [
  { value: "", label: "全部预约" },
  { value: "pending_store_confirmation", label: "待门店确认" },
  { value: "confirmed", label: "已确认" },
  { value: "declined", label: "未接受" },
  { value: "cancelled", label: "已取消" },
  { value: "arrived", label: "已到店" },
];
const reasonOptions = [
  { value: "", label: "请选择暂无法接待的原因" },
  ...Object.entries(reasonLabels).map(([value, label]) => ({ value, label })),
];
function load() {
  return inbox.load(state.value, offset.value);
}
function changePage(page: number) {
  if (inbox.busy) return;
  offset.value = (page - 1) * 25;
  void load();
}
watch(
  scope,
  () => {
    inbox.bind(storeId.value, session.value?.token ?? "");
    state.value = "";
    offset.value = 0;
    if (readable.value) void load();
  },
  { immediate: true },
);
watch(state, () => {
  offset.value = 0;
  void load();
});
watch(newTime, () => {
  changeAvailable.value = changeChecked.value = false;
});
watch(
  () => inbox.selected?.id + "/" + inbox.selected?.version,
  () => {
    checked.value = false;
    availability.value = false;
    reason.value = "";
    newTime.value = "";
    changeAvailable.value =
      changeChecked.value =
      identityChecked.value =
      arrivalChecked.value =
        false;
  },
);
let contactTimer: ReturnType<typeof setTimeout> | undefined;
async function contact() {
  await inbox.contact();
  clearTimeout(contactTimer);
  contactTimer = setTimeout(() => (inbox.phone = ""), 60000);
}
onBeforeUnmount(() => {
  clearTimeout(contactTimer);
  inbox.bind("", "");
});
function date(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "尚未确认";
}
async function decide(action: "confirm" | "decline") {
  await inbox.decide(action, checked.value, availability.value, reason.value);
  if (!inbox.pending) void load();
}
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">APPOINTMENTS</p>
      <h1>每一份到店意愿，认真回应。</h1>
      <p>接收客户申请，核实安排后确认；时间变更需客户重新确认。</p>
    </div>
    <span class="soft-label">{{ currentStore?.name || "暂无授权门店" }}</span>
  </div>
  <p v-if="inbox.error" class="error-message" role="alert">{{ inbox.error }}</p>
  <div v-if="inbox.pending" class="notice">
    <p>本次处理结果尚未核实，请保留原请求；刷新可查看当前状态。</p>
    <button
      class="button secondary"
      :disabled="inbox.busy"
      @click="inbox.retry()"
    >
      用原请求核实处理结果
    </button>
  </div>
  <section class="card appointments-card">
    <div class="table-toolbar appointments-toolbar">
      <div class="appointments-filter">
        <label for="appointment-state">申请状态</label>
        <RefinedSelect
          id="appointment-state"
          v-model="state"
          :options="stateOptions"
          label="申请状态"
          :disabled="inbox.busy || !readable"
        />
      </div>
      <button
        class="button secondary appointments-refresh"
        :disabled="inbox.busy || !readable"
        @click="load"
      >
        <RefreshCw
          :size="15"
          :class="{ 'is-loading': inbox.busy }"
          aria-hidden="true"
        />
        刷新列表
      </button>
    </div>
    <p v-if="!readable" class="notice">
      此账号没有当前门店的预约读取权限，请使用获明确授权的接待账号。
    </p>
    <p
      v-else-if="inbox.busy"
      class="loading-state appointments-loading"
      role="status"
    >
      正在核实当前门店记录…
    </p>
    <div v-else-if="inbox.items.length" class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>客户 / 申请</th>
            <th>咨询意向</th>
            <th>到店时间 / 提案</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in inbox.items" :key="row.id">
            <td>
              <strong>{{ row.name }}</strong
              ><small
                >{{ row.phone_masked }} ·
                {{ row.simulated ? "模拟申请" : "客户申请" }}</small
              ><small>{{ row.id }}</small>
            </td>
            <td>{{ row.intention }}</td>
            <td>
              {{ date(row.confirmed_at || row.desired_at) }}
              <small>{{
                row.confirmed_at ? "已确认时间" : "客户期望时间"
              }}</small>
              <small v-if="row.change_proposal"
                >等待客户回应改约 ·
                {{ date(row.change_proposal.proposed_at) }}</small
              >
            </td>
            <td>
              <span
                class="status"
                :class="
                  row.state === 'pending_store_confirmation' ? 'amber' : 'green'
                "
                >{{ appointmentLabels[row.state] ?? "状态待核实" }}</span
              >
            </td>
            <td>
              <button class="text-button" @click="inbox.open(row.id)">
                查看与处理
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else-if="readable && !inbox.error"
      title="暂无符合条件的申请"
      description="客户确认提交后，申请将在当前授权门店显示。"
    />
    <TablePagination
      v-if="readable && !inbox.busy"
      :total="inbox.total"
      :page="Math.floor(offset / 25) + 1"
      :disabled="inbox.busy"
      @change="changePage"
    />
  </section>
  <SidePanel
    v-if="inbox.selected && !inbox.busy"
    :title="inbox.selected.name"
    :subtitle="
      inbox.selected.simulated ? '模拟申请 · 持久业务记录' : '当前门店预约申请'
    "
    @close="inbox.close()"
  >
    <div class="detail-summary">
      <span class="status amber">{{
        appointmentLabels[inbox.selected.state]
      }}</span>
      <h3>{{ inbox.selected.intention }}</h3>
      <p>申请 {{ inbox.selected.id }} · 版本 {{ inbox.selected.version }}</p>
    </div>
    <dl class="detail-list">
      <dt>期望时间</dt>
      <dd>{{ date(inbox.selected.desired_at) }}</dd>
      <dt>已确认到店时间</dt>
      <dd>{{ date(inbox.selected.confirmed_at) }}</dd>
      <dt v-if="inbox.selected.arrived_at">实际到店登记</dt>
      <dd v-if="inbox.selected.arrived_at">
        {{ date(inbox.selected.arrived_at) }}
      </dd>
      <dt>意向项目</dt>
      <dd>{{ inbox.selected.project_title || "不确定项目，先咨询" }}</dd>
      <dt>客户确认</dt>
      <dd>{{ date(inbox.selected.customer_confirmed_at) }} · 客户按钮确认</dd>
      <dt>联系方式</dt>
      <dd>
        {{ inbox.phone || inbox.selected.phone_masked }}
        <button
          v-if="can('appointment_contact') && !inbox.phone"
          class="text-button"
          @click="contact"
        >
          查看本次预约联系号码</button
        ><small v-if="inbox.phone"
          >仅供本次联系；查看已记录，60 秒后隐藏。</small
        >
      </dd>
      <dt v-if="inbox.selected.decision_reason">处理原因</dt>
      <dd v-if="inbox.selected.decision_reason">
        {{ reasonLabels[inbox.selected.decision_reason] }}
      </dd>
    </dl>
    <h3>处理记录</h3>
    <ol class="timeline">
      <li
        v-for="event in inbox.selected.events"
        :key="`${event.version}/${event.event}`"
      >
        {{ date(event.occurred_at) }} ·
        {{
          event.event === "submitted"
            ? "客户提交申请"
            : appointmentLabels[event.event]
        }}<span v-if="event.reason"> · {{ reasonLabels[event.reason] }}</span>
      </li>
    </ol>
    <div
      v-if="
        inbox.selected.state === 'pending_store_confirmation' &&
        !inbox.selected.change_proposal &&
        can('appointment_manage') &&
        !inbox.pending
      "
      class="stack-form"
    >
      <h3>核实接待安排</h3>
      <p>
        按客户已确认的期望时间
        {{ date(inbox.selected.desired_at) }}
        接待。需要更换时间时，请在下方发起改约提案。
      </p>
      <label class="checkbox-label"
        ><input
          v-model="availability"
          type="checkbox"
        />已核实门店能在此时间接待</label
      ><label for="appointment-decline-reason"
        >暂无法接待原因<RefinedSelect
          id="appointment-decline-reason"
          v-model="reason"
          :options="reasonOptions"
          label="暂无法接待原因"
          :disabled="inbox.busy" /></label
      ><label class="checkbox-label"
        ><input
          v-model="checked"
          type="checkbox"
        />我确认所选处理结果，将更新客户可见状态并保留记录</label
      >
      <div class="form-actions">
        <button
          class="button secondary"
          :disabled="!checked || !reason"
          @click="decide('decline')"
        >
          确认暂无法接待</button
        ><button
          class="button primary"
          :disabled="!checked || !availability"
          @click="decide('confirm')"
        >
          确认客户期望时间
        </button>
      </div>
    </div>
    <p
      v-else-if="
        inbox.selected.state === 'pending_store_confirmation' &&
        !can('appointment_manage')
      "
      class="notice"
    >
      此账号仅可查看，未获预约处理权限。
    </p>
    <div v-if="inbox.selected.change_proposal" class="notice">
      <h3>等待客户回应改约</h3>
      <p>建议新时间：{{ date(inbox.selected.change_proposal.proposed_at) }}</p>
      <p>
        提案有效至
        {{
          date(inbox.selected.change_proposal.expires_at)
        }}。原安排保持不变，客户接受后才会更新。
      </p>
    </div>
    <form
      v-if="
        can('appointment_manage') &&
        !inbox.pending &&
        ['pending_store_confirmation', 'confirmed'].includes(
          inbox.selected.state,
        )
      "
      class="stack-form"
      @submit.prevent="inbox.propose(newTime, changeAvailable, changeChecked)"
    >
      <h3>与客户协商新时间</h3>
      <label
        >建议到店时间<input v-model="newTime" type="datetime-local" required
      /></label>
      <label class="checkbox-label"
        ><input
          v-model="changeAvailable"
          type="checkbox"
        />已核实门店能在建议时间接待</label
      >
      <label class="checkbox-label"
        ><input
          v-model="changeChecked"
          type="checkbox"
        />确认提出改约，等待客户本人选择；已有提案将被替换</label
      >
      <button
        class="button secondary"
        :disabled="!newTime || !changeAvailable || !changeChecked"
      >
        提出新时间，等待客户确认
      </button>
    </form>
    <div
      v-if="
        can('appointment_manage') &&
        !inbox.pending &&
        inbox.selected.state === 'confirmed' &&
        !inbox.selected.change_proposal
      "
      class="stack-form"
    >
      <h3>客户到店登记</h3>
      <label class="checkbox-label"
        ><input
          v-model="identityChecked"
          type="checkbox"
        />已现场核实本次预约客户身份及实际到店</label
      >
      <label class="checkbox-label"
        ><input
          v-model="arrivalChecked"
          type="checkbox"
        />确认登记实际到店，保留本次操作记录</label
      >
      <button
        class="button primary"
        :disabled="!identityChecked || !arrivalChecked"
        @click="inbox.arrive(identityChecked, arrivalChecked)"
      >
        确认登记已到店
      </button>
    </div>
  </SidePanel>
</template>

<style scoped>
.appointments-filter {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.appointments-filter > label {
  color: #7b877e;
  font-size: 12px;
  white-space: nowrap;
}
.appointments-filter > .refined-select {
  width: 210px;
}
.appointments-refresh {
  min-height: 44px;
  padding: 10px 15px;
  border-radius: 12px;
  background: #fff;
  color: #49604f;
}
.appointments-refresh:not(:disabled):hover {
  background: #f3f7f0;
  border-color: #cbd9c5;
}
.appointments-refresh .is-loading {
  animation: refresh-spin 1s linear infinite;
}
.appointments-loading {
  min-height: 220px;
  display: grid;
  place-items: center;
}
@keyframes refresh-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 680px) {
  .appointments-toolbar {
    gap: 12px;
  }
  .appointments-filter {
    flex: 1;
    gap: 10px;
  }
  .appointments-filter > .refined-select {
    width: 100%;
    min-width: 145px;
  }
  .appointments-refresh {
    padding-inline: 12px;
  }
}
@media (max-width: 420px) {
  .appointments-filter {
    width: 100%;
    flex-basis: 100%;
  }
  .appointments-refresh {
    margin-left: auto;
  }
}
@media (prefers-reduced-motion: reduce) {
  .appointments-refresh .is-loading {
    animation: none;
  }
}
</style>
