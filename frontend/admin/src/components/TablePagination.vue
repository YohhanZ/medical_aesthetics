<script setup lang="ts">
import { computed } from "vue";
import { ChevronLeft, ChevronRight } from "lucide-vue-next";

const props = withDefaults(
  defineProps<{
    total: number;
    page: number;
    pageSize?: number;
    disabled?: boolean;
  }>(),
  { pageSize: 25 },
);
const emit = defineEmits<{ change: [page: number] }>();
const pageCount = computed(() =>
  Math.max(1, Math.ceil(props.total / props.pageSize)),
);
const pages = computed(() => {
  const count = pageCount.value;
  if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1);
  const start = Math.max(2, Math.min(props.page - 1, count - 3));
  const end = Math.min(count - 1, Math.max(props.page + 1, 4));
  const items: (number | string)[] = [1];
  if (start > 2) items.push("leading-gap");
  for (let i = start; i <= end; i++) items.push(i);
  if (end < count - 1) items.push("trailing-gap");
  items.push(count);
  return items;
});
function go(page: number) {
  if (
    !props.disabled &&
    page >= 1 &&
    page <= pageCount.value &&
    page !== props.page
  )
    emit("change", page);
}
</script>

<template>
  <nav class="table-pagination" aria-label="预约列表分页">
    <p class="table-pagination__summary" aria-live="polite" aria-atomic="true">
      共 <strong>{{ total.toLocaleString("zh-CN") }}</strong> 条记录
      <span class="table-pagination__size">每页 {{ pageSize }} 条</span>
    </p>
    <div class="table-pagination__controls">
      <span class="table-pagination__position"
        >第 {{ page }} / {{ pageCount }} 页</span
      >
      <button
        type="button"
        class="table-pagination__arrow"
        aria-label="上一页"
        :disabled="disabled || page <= 1"
        @click="go(page - 1)"
      >
        <ChevronLeft :size="16" aria-hidden="true" /><span>上一页</span>
      </button>
      <div class="table-pagination__pages">
        <template v-for="item in pages" :key="item">
          <button
            v-if="typeof item === 'number'"
            type="button"
            class="table-pagination__number"
            :class="{ 'is-current': item === page }"
            :aria-label="`第 ${item} 页`"
            :aria-current="item === page ? 'page' : undefined"
            :disabled="disabled"
            @click="go(item)"
          >
            {{ item }}
          </button>
          <span v-else class="table-pagination__gap" aria-hidden="true">…</span>
        </template>
      </div>
      <button
        type="button"
        class="table-pagination__arrow"
        aria-label="下一页"
        :disabled="disabled || page >= pageCount"
        @click="go(page + 1)"
      >
        <span>下一页</span><ChevronRight :size="16" aria-hidden="true" />
      </button>
    </div>
  </nav>
</template>

<style scoped>
.table-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding: 18px 27px;
  border-top: 1px solid var(--border);
  color: #7b847e;
  font-size: 12px;
}
.table-pagination__summary {
  display: flex;
  align-items: center;
  gap: 5px;
}
.table-pagination__summary strong {
  color: #354d40;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.table-pagination__size {
  margin-left: 10px;
  padding-left: 14px;
  border-left: 1px solid #e4e9e2;
  color: #969e97;
}
.table-pagination__controls,
.table-pagination__pages {
  display: flex;
  align-items: center;
  gap: 5px;
}
.table-pagination__arrow,
.table-pagination__number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 38px;
  min-height: 40px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  color: #6b7b70;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  transition:
    background 0.16s,
    border-color 0.16s,
    color 0.16s;
}
.table-pagination__arrow {
  background: #fff;
  border-color: #e4e9e1;
  padding: 0 12px;
}
.table-pagination__number:not(:disabled):hover,
.table-pagination__arrow:not(:disabled):hover {
  background: #f1f5ef;
  color: #234d3b;
  border-color: #d7e1d2;
}
.table-pagination__number.is-current {
  background: #234d3b;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 2px 5px #234d3b12;
}
.table-pagination__number.is-current:not(:disabled):hover {
  background: #2d6049;
  color: #fff;
  border-color: transparent;
}
.table-pagination__arrow:disabled {
  background: #f7f8f5;
  color: #a8b0a6;
  border-color: #ecefe8;
  opacity: 1;
}
.table-pagination__gap {
  display: grid;
  place-items: center;
  width: 25px;
}
.table-pagination__position {
  display: none;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
@media (max-width: 680px) {
  .table-pagination {
    padding: 16px 18px;
    gap: 12px;
  }
  .table-pagination__summary {
    width: 100%;
  }
  .table-pagination__controls {
    width: 100%;
    justify-content: flex-end;
    gap: 8px;
  }
  .table-pagination__position {
    display: inline;
    margin-right: auto;
  }
  .table-pagination__pages {
    display: none;
  }
  .table-pagination__arrow {
    min-height: 44px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .table-pagination__arrow,
  .table-pagination__number {
    transition: none;
  }
}
</style>
