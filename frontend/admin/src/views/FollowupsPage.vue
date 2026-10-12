<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { can, currentStore, isDemo, session, storeId } from "../state";
import {
  FollowupInbox,
  followupApi,
  followupLabels,
  type FollowupState,
  type StaffFollowup,
} from "../services/followups";
import SidePanel from "../components/SidePanel.vue";
import EmptyState from "../components/EmptyState.vue";
const inbox = reactive(new FollowupInbox(followupApi));
const state = ref(""),
  offset = ref(0),
  candidateOffset = ref(0),
  checked = ref(false),
  noteChecked = ref(false),
  note = ref("");
const form = reactive({
  case_id: "",
  due_at: "",
  message: "咨询之后还有哪些疑问？您可以在原对话中告诉我们。",
});
const readable = computed(() => !isDemo.value && can("customer_read"));
const manageable = computed(() => !isDemo.value && can("customer_manage"));
function load() {
  return inbox.load(state.value, offset.value, candidateOffset.value);
}
watch(
  () => `${storeId.value}/${session.value?.token ?? ""}/${isDemo.value}`,
  () => {
    inbox.bind(storeId.value, session.value?.token ?? "");
    state.value = "";
    offset.value = candidateOffset.value = 0;
    form.case_id = form.due_at = "";
    checked.value = false;
    if (readable.value) void load();
  },
  { immediate: true },
);
watch(
  () => JSON.stringify(form),
  () => (checked.value = false),
);
watch(note, () => (noteChecked.value = false));
watch(
  () => inbox.selected,
  () => {
    note.value = "";
    noteChecked.value = false;
  },
);
onBeforeUnmount(() => inbox.bind("", ""));
async function create() {
  const candidate = inbox.candidates.find((x) => x.id === form.case_id);
  if (!candidate || !form.due_at) return;
  await inbox.create(
    candidate,
    new Date(form.due_at).toISOString(),
    form.message,
    checked.value,
  );
  checked.value = false;
  if (!inbox.pending && !inbox.error) await load();
}
async function act(action: "note" | "cancel") {
  await inbox.act(action, note.value, noteChecked.value);
  if (!inbox.pending && !inbox.error) await load();
}
async function retry() {
  await inbox.retry();
  if (!inbox.pending && !inbox.error) await load();
}
const date = (value: string) => new Date(value).toLocaleString("zh-CN");
const feedback = (row: StaffFollowup) =>
  row.history.filter((x) => x.kind === "feedback").at(-1);
const eventLabels: Record<string, string> = {
  created: "门店提出计划",
  accept: "客户同意",
  reject: "客户拒绝并暂停邀请",
  cancel: "计划取消",
  resume: "客户恢复邀请",
  feedback: "客户提交反馈",
  note: "门店内部跟进",
};
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">CARE THAT CONTINUES</p>
      <h1>咨询之后，关怀继续。</h1>
      <p>客户同意每次计划，反馈与门店跟进各自留痕。</p>
    </div>
    <span class="soft-label">{{ currentStore?.name || "暂无授权门店" }}</span>
  </div>
  <p v-if="!readable" class="notice">
    {{
      isDemo
        ? "回访页使用持久业务，请退出界面演练后登录授权顾问账号。"
        : "此账号没有当前门店的客户资料权限。"
    }}
  </p>
  <p v-if="inbox.error" role="alert" class="error-message">{{ inbox.error }}</p>
  <div v-if="inbox.pending" class="notice">
    <p>结果尚未核实，保留原计划或记录，避免重复操作。</p>
    <button class="button secondary" :disabled="inbox.busy" @click="retry">
      核实并重试原回访操作
    </button>
  </div>
  <template v-if="readable">
    <div class="stat-grid">
      <article
        v-for="status in [
          'awaiting_confirmation',
          'scheduled',
          'completed',
        ] as FollowupState[]"
        :key="status"
        class="stat-card"
      >
        <div>
          <span>{{ followupLabels[status] }}</span>
        </div>
        <strong>{{
          inbox.busy || inbox.error ? "—" : (inbox.counts[status] ?? 0)
        }}</strong>
        <p>当前授权门店</p>
      </article>
    </div>
    <section class="card">
      <div class="table-toolbar">
        <h2>回访计划</h2>
        <label
          >回访状态<select
            v-model="state"
            :disabled="inbox.busy"
            @change="
              offset = 0;
              load();
            "
          >
            <option value="">全部状态</option>
            <option
              v-for="(label, key) in followupLabels"
              :key="key"
              :value="key"
            >
              {{ label }}
            </option>
          </select></label
        ><button class="button secondary" :disabled="inbox.busy" @click="load">
          刷新回访计划
        </button>
      </div>
      <p v-if="inbox.busy" role="status">正在核实回访记录…</p>
      <div v-else-if="inbox.items.length" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>客户</th>
              <th>计划时间</th>
              <th>状态</th>
              <th>客户反馈</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in inbox.items" :key="row.id">
              <td>
                <strong>{{ row.name }}</strong
                ><small
                  >{{ row.phone_masked }} ·
                  {{ row.simulated ? "模拟回访" : "站内回访" }}</small
                >
              </td>
              <td>
                {{ date(row.due_at)
                }}<small>咨询版本 {{ row.case_version }}</small>
              </td>
              <td>
                {{ followupLabels[row.state]
                }}<small v-if="row.opted_out">客户已暂停邀请</small>
              </td>
              <td>
                {{
                  feedback(row)?.result === "need_help"
                    ? "希望继续沟通"
                    : feedback(row)?.result === "resolved"
                      ? "目前没有其他疑问"
                      : "尚无反馈"
                }}
              </td>
              <td>
                <button class="text-button" @click="inbox.open(row.id)">
                  查看回访详情
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else-if="!inbox.error"
        title="暂无回访计划"
        description="从客户已确认的到店咨询意向提出站内计划，等待本人同意。"
      />
      <div class="form-actions">
        <span>{{ inbox.error ? "数量待核实" : `共 ${inbox.total} 条` }}</span
        ><button
          class="text-button"
          :disabled="inbox.busy || offset === 0"
          @click="
            offset -= 25;
            load();
          "
        >
          上一页回访</button
        ><button
          class="text-button"
          :disabled="inbox.busy || offset + 25 >= inbox.total"
          @click="
            offset += 25;
            load();
          "
        >
          下一页回访
        </button>
      </div>
    </section>
    <form v-if="manageable" class="card stack-form" @submit.prevent="create">
      <h2>提出站内回访计划</h2>
      <p>
        不会发送短信或拨打电话。客户在原对话中明确同意后，计划才生效；拒绝或取消会暂停该档案的后续邀请。
      </p>
      <label
        >已确认咨询档案<select
          v-model="form.case_id"
          required
          :disabled="inbox.busy || !!inbox.pending"
        >
          <option value="">请选择</option>
          <option v-for="row in inbox.candidates" :key="row.id" :value="row.id">
            {{ row.name }} · {{ row.phone_masked }} · 版本 {{ row.version }} ·
            {{ row.id }}
          </option>
        </select></label
      >
      <div class="form-actions">
        <span>共 {{ inbox.candidateTotal }} 份已确认档案</span
        ><button
          type="button"
          class="text-button"
          :disabled="inbox.busy || candidateOffset === 0"
          @click="
            candidateOffset -= 25;
            form.case_id = '';
            load();
          "
        >
          上一页候选档案</button
        ><button
          type="button"
          class="text-button"
          :disabled="inbox.busy || candidateOffset + 25 >= inbox.candidateTotal"
          @click="
            candidateOffset += 25;
            form.case_id = '';
            load();
          "
        >
          下一页候选档案
        </button>
      </div>
      <label
        >计划回访时间<input
          v-model="form.due_at"
          type="datetime-local"
          required
          :disabled="inbox.busy || !!inbox.pending"
      /></label>
      <label
        >给客户的回访说明<textarea
          v-model="form.message"
          required
          maxlength="300"
          rows="3"
          :disabled="inbox.busy || !!inbox.pending"
        ></textarea>
      </label>
      <label class="checkbox-label"
        ><input
          v-model="checked"
          type="checkbox"
          :disabled="inbox.busy || !!inbox.pending"
        />确认提出此计划，等待客户本人同意</label
      ><button
        class="button primary"
        :disabled="inbox.busy || !!inbox.pending || !checked"
      >
        提出回访计划，等待客户同意
      </button>
    </form>
  </template>
  <SidePanel
    v-if="inbox.selected && !inbox.busy"
    :title="inbox.selected.name"
    :subtitle="
      inbox.selected.simulated ? '模拟站内回访 · 持久记录' : '站内回访'
    "
    @close="inbox.close()"
  >
    <dl class="detail-list">
      <dt>回访状态</dt>
      <dd>
        {{ followupLabels[inbox.selected.state] }} · 版本
        {{ inbox.selected.version }}
      </dd>
      <dt>计划回访时间</dt>
      <dd>{{ date(inbox.selected.due_at) }}</dd>
      <dt>来源咨询档案</dt>
      <dd>
        {{ inbox.selected.case_id }} · 意向版本
        {{ inbox.selected.case_version }}
      </dd>
      <dt>回访说明</dt>
      <dd>{{ inbox.selected.message }}</dd>
      <dt>客户反馈</dt>
      <dd>
        {{
          feedback(inbox.selected)?.result === "need_help"
            ? "希望门店继续沟通"
            : feedback(inbox.selected)?.result === "resolved"
              ? "目前没有其他疑问"
              : "尚未提交"
        }}
        <p>{{ feedback(inbox.selected)?.feedback }}</p>
      </dd>
    </dl>
    <p v-if="inbox.selected.opted_out" class="notice">
      客户已暂停此档案的新邀请，顾问不能代为恢复。
    </p>
    <p v-if="!inbox.selected.source_current" class="notice">
      来源咨询意向已更新。未同意的旧计划需取消后重新安排；已有反馈保留。
    </p>
    <p class="notice">
      “反馈已保存”不代表人工已回复。内部跟进记录只供授权门店查看，不发送给客户或模型。
    </p>
    <h3>回访与跟进历史</h3>
    <ol class="timeline">
      <li v-for="event in inbox.selected.history" :key="event.version">
        <strong
          >版本 {{ event.version }} · {{ eventLabels[event.kind] }} ·
          {{ date(event.recorded_at) }}</strong
        >
        <p>{{ event.confirmation_text }} {{ event.text }}</p>
        <p>
          {{
            event.result === "need_help"
              ? "希望门店继续沟通"
              : event.result === "resolved"
                ? "目前没有其他疑问"
                : ""
          }}
          {{ event.feedback }}
        </p>
      </li>
    </ol>
    <div v-if="manageable && !inbox.pending" class="stack-form">
      <h3>追加门店内部跟进记录</h3>
      <label
        >内部跟进备注<textarea
          v-model="note"
          maxlength="500"
          rows="3"
          placeholder="记录实际沟通与处理情况，不填写医疗诊断"
        ></textarea></label
      ><label class="checkbox-label"
        ><input
          v-model="noteChecked"
          type="checkbox"
        />确认下面的跟进操作并保留历史</label
      >
      <div class="form-actions">
        <button
          class="button primary"
          :disabled="!noteChecked || !note.trim()"
          @click="act('note')"
        >
          追加内部跟进记录</button
        ><button
          v-if="
            ['awaiting_confirmation', 'scheduled'].includes(
              inbox.selected.state,
            )
          "
          class="button secondary"
          :disabled="!noteChecked || !note.trim()"
          @click="act('cancel')"
        >
          取消这次回访计划
        </button>
      </div>
    </div>
  </SidePanel>
</template>
