<script setup lang="ts">
import { computed, ref } from "vue";
import { Plus, Search } from "lucide-vue-next";
import { isDemo, storeId } from "../state";
import { demoData } from "../services/demo";
import type { Project } from "../types";
import EmptyState from "../components/EmptyState.vue";
import SidePanel from "../components/SidePanel.vue";
const search = ref(""),
  selected = ref<Project | null>(null),
  editing = ref(false);
const title = ref(""),
  category = ref("美容护理"),
  introduction = ref("");
const rows = computed(() =>
  (isDemo.value ? (demoData[storeId.value]?.projects ?? []) : []).filter((p) =>
    `${p.title}${p.category}`.includes(search.value.trim()),
  ),
);
function edit(row?: Project) {
  selected.value = row ?? null;
  title.value = row?.title ?? "";
  category.value = row?.category ?? "美容护理";
  introduction.value = row?.introduction ?? "";
  editing.value = true;
}
function save() {
  if (!isDemo.value) return;
  const data = {
    title: title.value.trim(),
    category: category.value,
    introduction: introduction.value.trim(),
  };
  if (!data.title || !data.introduction) return;
  if (selected.value) Object.assign(selected.value, data);
  else
    demoData[storeId.value].projects.push({
      ...data,
      id: `DEMO-P${Date.now()}`,
      active: false,
    });
  editing.value = false;
}
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">PROJECT CATALOG</p>
      <h1>清晰的项目介绍，安心的了解入口。</h1>
      <p>目录与门店供给分开核验，不编造价格、资质或效果承诺。</p>
    </div>
    <button class="button primary" :disabled="!isDemo" @click="edit()">
      <Plus :size="17" />新增项目
    </button>
  </div>
  <section class="card">
    <div class="table-toolbar">
      <h2>项目目录</h2>
      <label class="search-field"
        ><Search :size="17" /><input
          v-model="search"
          aria-label="搜索项目"
          placeholder="搜索项目或分类"
      /></label>
    </div>
    <div v-if="rows.length" class="project-grid">
      <article v-for="row in rows" :key="row.id" class="project-card">
        <div>
          <span class="soft-label">{{ row.category }}</span
          ><span class="status" :class="row.active ? 'green' : 'neutral'">{{
            row.active ? "演练展示中" : "演练已隐藏"
          }}</span>
        </div>
        <h3>{{ row.title }}</h3>
        <p>{{ row.introduction }}</p>
        <footer>
          <button class="text-button" @click="edit(row)">编辑介绍</button
          ><button class="text-button" @click="row.active = !row.active">
            {{ row.active ? "隐藏演练项目" : "展示演练项目" }}
          </button>
        </footer>
      </article>
    </div>
    <EmptyState
      v-else
      :title="isDemo ? '暂无符合条件的项目' : '项目目录等待管理接口接入'"
      :description="
        isDemo
          ? '可以新增合成目录，或调整搜索条件。'
          : '真实供给、有效报价和图片授权核验接入后开放编辑。'
      "
    />
  </section>
  <SidePanel
    v-if="editing"
    :title="selected ? '编辑项目介绍' : '新增项目'"
    subtitle="合成目录 · 仅界面演练"
    @close="editing = false"
    ><form class="stack-form" @submit.prevent="save">
      <label>项目名称<input v-model="title" required maxlength="80" /></label
      ><label
        >分类<select v-model="category">
          <option>美容护理</option>
          <option>医疗美容咨询</option>
        </select></label
      ><label
        >简介<textarea
          v-model="introduction"
          required
          maxlength="1000"
          rows="5"
        ></textarea>
      </label>
      <p class="hint">
        模拟资料不构成真实机构供给，新项目默认隐藏。医学说明与资质需单独核验。
      </p>
      <button class="button primary">保存演练目录</button>
    </form></SidePanel
  >
</template>
