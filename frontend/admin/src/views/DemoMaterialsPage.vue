<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, reactive, ref, watch } from "vue";
import { can, isDemo, session, storeId } from "../state";
import {
  DemoMaterialsView,
  readDemoMaterials,
} from "../services/demo-materials";
const view = reactive(new DemoMaterialsView(markRaw(readDemoMaterials)));
const active = ref("store");
const tabs = [
  { id: "store", name: "门店与团队" },
  { id: "services", name: "服务与演示价" },
  { id: "policies", name: "接待规则" },
  { id: "suppliers", name: "供应商演练" },
  { id: "scripts", name: "演示讲解" },
];
const readable = computed(() => !isDemo.value && can("customer_read"));
watch(
  () => `${storeId.value}/${session.value?.token ?? ""}/${isDemo.value}`,
  () => {
    view.bind(storeId.value, session.value?.token ?? "");
    active.value = "store";
    if (readable.value) void view.load();
  },
  { immediate: true },
);
onBeforeUnmount(() => view.bind("", ""));
const money = (value: number) =>
  new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(value);
function download() {
  if (!view.pack) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(view.pack, null, 2)], {
      type: "application/json;charset=utf-8",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `${view.pack.pack_id}-${view.pack.store.code}.json`;
  link.click();
  URL.revokeObjectURL(url);
}
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">A GARDEN OF POSSIBILITIES</p>
      <h1>让演示，更有生活的细节。</h1>
      <p>一致的机构设定、清楚的服务价格、完整的接待与协同流程。</p>
    </div>
    <span class="soft-label">虚构机构资料 · 只读展示</span>
  </div>
  <p v-if="!readable" class="notice">
    请登录拥有当前门店客户资料读取权限的顾问账号查看。界面演练账号不调用此接口。
  </p>
  <p v-if="view.error" class="error-message" role="alert">{{ view.error }}</p>
  <p v-if="view.busy" role="status">正在读取授权门店的演示资料…</p>
  <div v-if="readable" class="form-actions">
    <button class="button secondary" :disabled="view.busy" @click="view.load()">
      刷新演示资料
    </button>
    <button
      class="button secondary"
      :disabled="!view.pack || view.busy"
      @click="download"
    >
      下载当前门店资料 JSON
    </button>
  </div>
  <template v-if="view.pack">
    <p class="notice">
      {{ view.pack.disclosure }} 资料只用于讲解，未发布到 Agent 知识库。
    </p>
    <div class="stat-grid">
      <article class="stat-card">
        <div><span>当前门店团队</span></div>
        <strong>{{ view.pack.personnel.length }}</strong>
        <p>虚构岗位档案</p>
      </article>
      <article class="stat-card">
        <div><span>服务了解入口</span></div>
        <strong>{{ view.pack.services.length }}</strong>
        <p>演示报价，不收费</p>
      </article>
      <article class="stat-card">
        <div><span>协同流程</span></div>
        <strong>{{ view.pack.suppliers.length }}</strong>
        <p>实际供应商仍待验收</p>
      </article>
    </div>
    <nav class="material-tabs" aria-label="演示资料分类">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :aria-pressed="active === tab.id"
        :class="{ selected: active === tab.id }"
        @click="active = tab.id"
      >
        {{ tab.name }}
      </button>
    </nav>
    <p class="material-version">
      版本 {{ view.pack.version }} · 资料演示期 {{ view.pack.created_on }} 至
      {{ view.pack.valid_until }} · {{ view.pack.store.city }}
    </p>
    <section v-if="active === 'store'" class="materials-stack">
      <article class="card material-store">
        <p class="eyebrow">{{ view.pack.institution.name }}</p>
        <h2>{{ view.pack.store.name }}</h2>
        <p>{{ view.pack.store.address }}</p>
        <dl class="material-facts">
          <div>
            <dt>营业时段设定</dt>
            <dd>{{ view.pack.store.hours }}</dd>
          </div>
          <div>
            <dt>空间设定</dt>
            <dd>
              {{ view.pack.store.area_m2 }} m² ·
              {{ view.pack.store.rooms }} 间沟通/体验室
            </dd>
          </div>
          <div>
            <dt>店长</dt>
            <dd>{{ view.pack.store.manager }}</dd>
          </div>
          <div>
            <dt>接待方式</dt>
            <dd>{{ view.pack.store.contact }}</dd>
          </div>
          <div>
            <dt>日咨询容量设定</dt>
            <dd>
              {{ view.pack.store.daily_consultation_capacity }} 位 · 人工核实
            </dd>
          </div>
          <div>
            <dt>机构资质</dt>
            <dd>
              {{ view.pack.institution.actual_verification }} · 无虚构证号
            </dd>
          </div>
        </dl>
        <p class="hint">{{ view.pack.store.capacity_note }}</p>
      </article>
      <div class="material-grid">
        <article
          v-for="person in view.pack.personnel"
          :key="person.id"
          class="card material-card"
        >
          <span class="soft-label">{{ person.role }}</span>
          <h3>{{ person.name }}</h3>
          <p>{{ person.experience_setting }} · {{ person.shift }}</p>
          <p>{{ person.specialty }}</p>
          <p class="material-status">{{ person.qualification_status }}</p>
        </article>
      </div>
    </section>
    <section
      v-if="active === 'services'"
      class="material-grid"
      aria-label="演示服务报价"
    >
      <article
        v-for="service in view.pack.services"
        :key="service.id"
        class="card material-card"
      >
        <span class="soft-label">{{ service.category }}</span>
        <h3>{{ service.name }}</h3>
        <div class="material-price">
          <strong>{{ money(service.demo_price_cny) }}</strong
          ><span>/ {{ service.unit }}</span>
          <span v-if="service.list_price_cny > service.demo_price_cny"
            >标价设定 {{ money(service.list_price_cny) }}</span
          >
        </div>
        <p>{{ service.minutes }} 分钟 · {{ service.included }}</p>
        <p v-if="service.category === '医疗美容咨询'" class="material-status">
          仅了解咨询，不含治疗操作或治疗报价。
        </p>
        <p class="hint">
          {{ service.price_note }} · {{ service.actual_supply_status }}
        </p>
      </article>
    </section>
    <section v-if="active === 'policies'" class="material-grid">
      <article
        v-for="rule in view.pack.policies"
        :key="rule.id"
        class="card material-card"
      >
        <span class="soft-label">模拟接待规则</span>
        <h3>{{ rule.title }}</h3>
        <p>{{ rule.content }}</p>
        <p class="material-status">{{ rule.flow }}</p>
      </article>
    </section>
    <section v-if="active === 'suppliers'" class="material-grid">
      <article
        v-for="supplier in view.pack.suppliers"
        :key="supplier.id"
        class="card material-card"
      >
        <span class="soft-label">{{ supplier.kind }}</span>
        <h3>{{ supplier.name }}</h3>
        <p>{{ supplier.scope }}</p>
        <p>{{ supplier.integration }}</p>
        <p class="material-status">实际状态：{{ supplier.actual_status }}</p>
        <details>
          <summary>查看演练复核与正式验收清单</summary>
          <div
            v-for="review in view.pack.review_records.filter(
              (r) => r.supplier_id === supplier.id,
            )"
            :key="review.id"
          >
            <p>{{ review.demo_result }}</p>
            <p>实际结果：{{ review.actual_result }}</p>
            <p>
              编制 {{ review.prepared_by }} · 独立复核 {{ review.reviewed_by }}
            </p>
            <p>{{ review.evidence_reference }} · {{ review.evidence_type }}</p>
          </div>
          <ul>
            <li v-for="item in supplier.required" :key="item">{{ item }}</li>
          </ul>
        </details>
      </article>
    </section>
    <section v-if="active === 'scripts'" class="materials-stack">
      <article
        v-for="journey in view.pack.journeys"
        :key="journey.id"
        class="card material-card"
      >
        <span class="soft-label">{{ journey.customer_alias }} · 讲解脚本</span>
        <h3>{{ journey.title }}</h3>
        <ol>
          <li v-for="step in journey.steps" :key="step">{{ step }}</li>
        </ol>
        <p class="material-status">{{ journey.expected }}</p>
        <p class="hint">{{ journey.record_type }}</p>
      </article>
      <details class="card material-card">
        <summary>常见问题与接待表达 · 6组</summary>
        <div
          v-for="script in view.pack.scripts"
          :key="script.id"
          class="material-script"
        >
          <h3>{{ script.customer_question }}</h3>
          <p>{{ script.suggested_reply }}</p>
        </div>
      </details>
    </section>
  </template>
</template>
<style scoped>
.materials-stack {
  display: grid;
  gap: 20px;
}
.material-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.material-card,
.material-store {
  padding: 28px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.material-card h3,
.material-store h2 {
  margin: 16px 0 12px;
}
.material-card p,
.material-store p {
  line-height: 1.8;
}
.material-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
  margin: 24px 0;
}
.material-facts dt,
.material-version,
.material-price span {
  color: var(--muted);
  font-size: 12px;
}
.material-facts dd {
  margin: 8px 0 0;
  line-height: 1.7;
}
.material-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 28px 0 16px;
}
.material-tabs button {
  border: 1px solid var(--border);
  border-radius: 24px;
  padding: 11px 18px;
  background: white;
  color: var(--muted);
}
.material-tabs button.selected {
  background: var(--green);
  color: white;
}
.material-price {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin: 18px 0;
}
.material-price strong {
  font-size: 30px;
  font-weight: 500;
}
.material-status {
  border-top: 1px solid var(--border);
  padding-top: 14px;
  color: var(--green);
}
.material-card summary {
  cursor: pointer;
  line-height: 1.8;
}
.material-card ol,
.material-card ul {
  padding-left: 22px;
  line-height: 2;
}
.material-script {
  border-top: 1px solid var(--border);
  margin-top: 22px;
}
@media (max-width: 650px) {
  .material-grid,
  .material-facts {
    grid-template-columns: 1fr;
  }
  .material-card,
  .material-store {
    padding: 22px;
  }
  .material-tabs button {
    padding: 10px 14px;
  }
}
</style>
