<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Plus, RefreshCw, Search } from "lucide-vue-next";
import { can, currentStore, isDemo, session } from "../state";
import { knowledgeLabels } from "../services/demo";
import {
  actionAllowed,
  createKnowledge,
  knowledgeAction,
  listKnowledge,
} from "../services/knowledge";
import { errorText } from "../services/api";
import type { Knowledge, KnowledgeInput } from "../types";
import EmptyState from "../components/EmptyState.vue";
import SidePanel from "../components/SidePanel.vue";
const rows = ref<Knowledge[]>([]),
  total = ref(0),
  offset = ref(0),
  query = ref(""),
  filter = ref("all");
const loading = ref(false),
  busy = ref(false),
  error = ref(""),
  notice = ref(""),
  selected = ref<Knowledge | null>(null),
  editing = ref(false);
const panelError = ref(""),
  reason = ref(""),
  confirm = ref(false);
const action = ref<"approve" | "reject" | "publish" | "withdraw" | "">("");
const categoryLabels = {
  operational: "运营政策",
  communication: "沟通策略",
  medical: "医学资料",
};
const actionLabels = {
  approve: "通过审核",
  reject: "不通过审核",
  publish: "申请发布",
  withdraw: "撤回版本",
};
const emptyForm = (): KnowledgeInput => ({
  knowledge_key: "",
  category: "operational",
  title: "",
  content: "",
  source: "",
  simulated: currentStore.value?.simulated ?? true,
  valid_until: new Date(Date.now() + 90 * 86400000).toISOString().slice(0, 10),
});
const form = ref(emptyForm());
const filtered = computed(() =>
  rows.value.filter(
    (r) =>
      (filter.value === "all" || r.status === filter.value) &&
      `${r.title}${r.knowledge_key}`.includes(query.value.trim()),
  ),
);
async function load() {
  if (!currentStore.value) return;
  error.value = "";
  loading.value = true;
  try {
    const result = await listKnowledge(offset.value);
    rows.value = result.items;
    total.value = result.total;
  } catch (e) {
    rows.value = [];
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
function open(row: Knowledge) {
  selected.value = row;
  action.value = "";
  reason.value = "";
  confirm.value = false;
  panelError.value = "";
}
function allowed(row: Knowledge, name: Exclude<typeof action.value, "">) {
  const permission =
    name === "approve" || name === "reject"
      ? "knowledge_review"
      : "knowledge_publish";
  return can(permission) && actionAllowed(row, name, session.value!.profile.id);
}
function edit(row?: Knowledge) {
  if (!can("knowledge_author")) return;
  selected.value = null;
  form.value = row
    ? {
        knowledge_key: row.knowledge_key,
        category: row.category,
        title: row.title,
        content: row.content,
        source: row.source,
        simulated: row.simulated,
        valid_until: new Date(Date.now() + 90 * 86400000)
          .toISOString()
          .slice(0, 10),
      }
    : emptyForm();
  editing.value = true;
  panelError.value = "";
  notice.value = "";
}
async function save() {
  if (busy.value) return;
  busy.value = true;
  panelError.value = "";
  try {
    if (
      ![form.value.title, form.value.content, form.value.source].every(
        (value) => value.trim(),
      )
    )
      throw new Error("标题、正文和来源不能只填写空格。");
    const date = new Date(`${form.value.valid_until}T23:59:59`);
    if (!Number.isFinite(date.getTime()) || date <= new Date())
      throw new Error("请选择未来的知识有效日期。");
    await createKnowledge({
      ...form.value,
      title: form.value.title.trim(),
      content: form.value.content.trim(),
      source: form.value.source.trim(),
      valid_until: date.toISOString(),
    });
    editing.value = false;
    offset.value = 0;
    notice.value = isDemo.value
      ? "已创建合成知识版本，需要另一个账号审核。"
      : "知识新版本已保存到数据库，等待独立审核。";
    await load();
  } catch (e) {
    panelError.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
async function perform() {
  if (!selected.value || !action.value || busy.value) return;
  if (
    !confirm.value ||
    ((action.value === "approve" || action.value === "reject") &&
      !reason.value.trim())
  ) {
    panelError.value = "请填写审核意见，并明确确认本次操作。";
    return;
  }
  busy.value = true;
  panelError.value = "";
  try {
    const operation = action.value;
    await knowledgeAction(selected.value, operation, reason.value.trim());
    selected.value = null;
    notice.value =
      operation === "publish"
        ? "发布请求已记录，正在等待知识投影完成，当前不能对客使用。"
        : `${actionLabels[operation]}已完成${isDemo.value ? "（界面演练）" : "并记录到数据库"}。`;
    await load();
  } catch (e) {
    panelError.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
async function page(direction: number) {
  offset.value += direction * 50;
  await load();
}
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">KNOWLEDGE & TRUST</p>
      <h1>每一条回答，都有可靠的依据。</h1>
      <p>按版本审核，按门店发布。资料更新始终保留来源与记录。</p>
    </div>
    <button
      class="button primary"
      :disabled="!can('knowledge_author') || loading"
      @click="edit()"
    >
      <Plus :size="17" />新增知识
    </button>
  </div>
  <p v-if="notice" class="success-message" role="status">{{ notice }}</p>
  <p v-if="error" class="error-message" role="alert">{{ error }}</p>
  <section class="card">
    <div class="table-toolbar">
      <div class="tabs">
        <button :class="{ active: filter === 'all' }" @click="filter = 'all'">
          全部版本</button
        ><button
          :class="{ active: filter === 'draft' }"
          @click="filter = 'draft'"
        >
          待审核</button
        ><button
          :class="{ active: filter === 'publishing' }"
          @click="filter = 'publishing'"
        >
          等待投影</button
        ><button
          :class="{ active: filter === 'published' }"
          @click="filter = 'published'"
        >
          已发布
        </button>
      </div>
      <div class="toolbar-right">
        <label class="search-field"
          ><Search :size="17" /><input
            v-model="query"
            aria-label="搜索知识"
            placeholder="搜索当前页标题或知识标识" /></label
        ><button
          class="icon-button"
          aria-label="刷新知识"
          :disabled="loading"
          @click="load"
        >
          <RefreshCw :size="17" />
        </button>
      </div>
    </div>
    <p v-if="loading" class="loading-state" role="status">
      正在读取本门店知识…
    </p>
    <div v-else-if="filtered.length" class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>知识标题</th>
            <th>类别</th>
            <th>版本与状态</th>
            <th>有效期</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in filtered" :key="row.id">
            <td>
              <strong>{{ row.title }}</strong
              ><small
                >{{ row.knowledge_key
                }}<span v-if="row.simulated"> · 模拟资料</span></small
              >
            </td>
            <td>{{ categoryLabels[row.category] }}</td>
            <td>
              <span class="version">v{{ row.version }}</span
              ><span
                class="status"
                :class="
                  row.status === 'published'
                    ? 'green'
                    : row.status === 'withdrawn' || row.status === 'rejected'
                      ? 'neutral'
                      : 'amber'
                "
                >{{ knowledgeLabels[row.status] }}</span
              >
            </td>
            <td>{{ new Date(row.valid_until).toLocaleDateString("zh-CN") }}</td>
            <td>
              <button class="text-button" @click="open(row)">查看与处理</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      :title="currentStore ? '暂无符合条件的知识' : '暂无授权门店'"
      :description="
        currentStore
          ? '调整当前页筛选条件，或新增一个待审核版本。读取失败时请刷新，页面不会补入模拟内容。'
          : '平台账号不会自动获得门店数据权限，请由机构管理员明确授权。'
      "
    />
    <div v-if="currentStore" class="pagination">
      <span>共 {{ total }} 个版本 · 当前页筛选</span>
      <div>
        <button
          class="button small secondary"
          :disabled="offset === 0 || loading"
          @click="page(-1)"
        >
          上一页</button
        ><button
          class="button small secondary"
          :disabled="offset + 50 >= total || loading"
          @click="page(1)"
        >
          下一页
        </button>
      </div>
    </div>
  </section>
  <p class="page-note">
    医学资料需真实核验与独立医学审核。当前发布投影尚未接入，发布申请不会自动变成“已发布”。
  </p>
  <SidePanel
    v-if="selected"
    :title="selected.title"
    :subtitle="`知识版本 v${selected.version}`"
    @close="!busy && (selected = null)"
    ><div class="detail-summary">
      <span class="status amber">{{ knowledgeLabels[selected.status] }}</span
      ><span v-if="selected.simulated" class="soft-label">模拟资料</span>
      <p>
        {{ categoryLabels[selected.category] }} · {{ selected.knowledge_key }}
      </p>
    </div>
    <h3>知识正文</h3>
    <p class="knowledge-body">{{ selected.content }}</p>
    <dl class="detail-list">
      <dt>来源</dt>
      <dd>{{ selected.source }}</dd>
      <dt>有效期</dt>
      <dd>{{ new Date(selected.valid_until).toLocaleString("zh-CN") }}</dd>
      <dt>审核意见</dt>
      <dd>{{ selected.review_reason || "尚无审核记录" }}</dd>
    </dl>
    <p v-if="selected.author_id === session?.profile.id" class="info-message">
      这是你创建的版本，需要另一个授权账号审核。
    </p>
    <p v-if="selected.category === 'medical'" class="info-message">
      医学资料暂不能批准或发布。可保留待审或由独立人员驳回，不用模拟审核替代医学核验。
    </p>
    <div class="knowledge-actions">
      <button
        v-if="can('knowledge_author')"
        class="button secondary"
        :disabled="busy"
        @click="edit(selected)"
      >
        建立新版本</button
      ><button
        v-for="operation in [
          'approve',
          'reject',
          'publish',
          'withdraw',
        ] as const"
        :key="operation"
        class="button secondary"
        :disabled="!allowed(selected, operation) || busy"
        @click="
          action = operation;
          reason = '';
          confirm = false;
          panelError = '';
        "
      >
        {{ actionLabels[operation] }}
      </button>
    </div>
    <form
      v-if="action"
      class="stack-form action-form"
      @submit.prevent="perform"
    >
      <h3>{{ actionLabels[action] }}</h3>
      <label v-if="action === 'approve' || action === 'reject'"
        >审核意见<textarea
          v-model="reason"
          rows="3"
          required
          maxlength="1000"
          :disabled="busy"
          @input="confirm = false"
        ></textarea>
      </label>
      <p v-if="action === 'publish'" class="hint">
        提交发布请求后仍需等待投影，不能立即对客使用。
      </p>
      <p v-if="action === 'withdraw'" class="hint">
        撤回立即阻断该版本的公开使用；再次使用需建立并审核新版本。
      </p>
      <label class="checkbox-label"
        ><input
          v-model="confirm"
          type="checkbox"
          :disabled="busy"
        />我已核实版本和门店，确认本次操作。</label
      >
      <p v-if="panelError" class="error-message" role="alert">
        {{ panelError }}
      </p>
      <button class="button primary" :disabled="busy">
        {{ busy ? "正在提交…" : "确认操作" }}
      </button>
    </form></SidePanel
  >
  <SidePanel
    v-if="editing"
    :title="form.knowledge_key ? '创建知识新版本' : '新增知识'"
    subtitle="保存后仍需独立审核"
    @close="!busy && (editing = false)"
    ><form class="stack-form" @submit.prevent="save">
      <label
        >知识标识<input
          v-model="form.knowledge_key"
          required
          pattern="[a-z0-9-]+"
          maxlength="80"
          placeholder="例如 booking-process"
          :disabled="busy" /></label
      ><label
        >标题<input
          v-model="form.title"
          required
          maxlength="200"
          :disabled="busy" /></label
      ><label
        >资料类别<select v-model="form.category" :disabled="busy">
          <option value="operational">运营政策</option>
          <option value="communication">沟通策略</option>
          <option value="medical">医学资料（待实际核验）</option>
        </select></label
      ><label
        >正文<textarea
          v-model="form.content"
          required
          rows="6"
          maxlength="12000"
          :disabled="busy"
        ></textarea></label
      ><label
        >资料来源<input
          v-model="form.source"
          required
          maxlength="1000"
          placeholder="注明来源、版本及模拟性质"
          :disabled="busy" /></label
      ><label
        >有效日期<input
          v-model="form.valid_until"
          type="date"
          required
          :disabled="busy" /></label
      ><label class="checkbox-label"
        ><input
          v-model="form.simulated"
          type="checkbox"
          :disabled="busy || isDemo || currentStore?.simulated"
        />模拟资料，保留明确标识</label
      >
      <p v-if="panelError" class="error-message" role="alert">
        {{ panelError }}
      </p>
      <button class="button primary" :disabled="busy">
        {{ busy ? "正在保存…" : "保存待审版本" }}
      </button>
    </form></SidePanel
  >
</template>
