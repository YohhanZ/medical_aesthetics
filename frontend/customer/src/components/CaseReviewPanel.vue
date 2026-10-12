<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, reactive, ref, watch } from "vue";
import {
  CaseReview,
  caseAcceptText,
  caseRejectText,
  type CustomerCaseApi,
} from "../services/cases";
const props = defineProps<{
  api: CustomerCaseApi;
  thread: string;
  visitor: string;
  appointment: string;
  refresh: object;
  disabled: boolean;
}>();
const review = reactive(new CaseReview(markRaw(props.api)));
const checked = ref(false);
const disabled = computed(
  () => props.disabled || review.busy || !!review.pending,
);
watch(
  () => [
    props.thread,
    props.visitor,
    props.appointment,
    props.refresh,
    props.disabled,
  ],
  () => {
    if (!props.disabled)
      void review.bind(props.thread, props.appointment, props.visitor);
  },
  { immediate: true },
);
watch(
  () =>
    `${review.row?.id}/${review.row?.version}/${review.row?.current.decision}`,
  () => (checked.value = false),
);
onBeforeUnmount(() => review.reset());
const date = (value: string) => new Date(value).toLocaleString("zh-CN");
</script>
<template>
  <section
    v-if="review.row || review.error || review.pending"
    class="booking-summary"
    aria-label="到店咨询意向确认"
  >
    <h4>到店后，继续了解您的想法</h4>
    <p>这里只确认本次咨询意向，具体治疗、医学评估和合同仍需独立处理。</p>
    <p v-if="review.error" class="chat-error" role="alert">
      {{ review.error }}
    </p>
    <div v-if="review.pending" class="booking-actions">
      <p>结果尚未核实，请使用原请求。</p>
      <button :disabled="props.disabled || review.busy" @click="review.retry()">
        重试原意向确认
      </button>
    </div>
    <template v-if="review.row">
      <p v-if="review.row.simulated" class="booking-simulation">
        本地模拟到店记录
      </p>
      <p>原预约意向：{{ review.row.initial.intention }}</p>
      <p>当前称呼：{{ review.row.current.name }}</p>
      <p>
        <strong>当前咨询方向：{{ review.row.current.intention }}</strong>
      </p>
      <p>
        项目入口：{{
          review.row.current.project_title || "不确定项目，继续沟通"
        }}
      </p>
      <p>变更说明：{{ review.row.current.reason }}</p>
      <p v-if="review.row.current.decision === 'accept'">
        您已确认版本 {{ review.row.version }} ·
        {{ date(review.row.current.confirmed_at!) }}
      </p>
      <p v-else-if="review.row.current.decision === 'reject'">
        您选择继续沟通，当前版本尚未确认为最终意向。
      </p>
      <template v-else>
        <label class="booking-check"
          ><input
            v-model="checked"
            type="checkbox"
            :disabled="disabled"
          />我已审阅当前版本
          {{ review.row.version }}，确认下面选择的处理方式</label
        >
        <div class="booking-actions">
          <button
            :disabled="disabled || !checked"
            @click="review.decide('reject', checked)"
          >
            {{ caseRejectText }}
          </button>
          <button
            class="booking-primary"
            :disabled="disabled || !checked"
            @click="review.decide('accept', checked)"
          >
            {{ caseAcceptText }}
          </button>
        </div>
      </template>
      <details class="answer-sources">
        <summary>查看咨询意向历史</summary>
        <p v-for="version in review.row.history" :key="version.version">
          版本 {{ version.version }} · {{ date(version.recorded_at) }} ·
          {{
            version.source === "original_application"
              ? "原预约申请"
              : "顾问记录"
          }}<br />{{ version.intention }} ·
          {{ version.project_title || "项目未定" }}<br />{{
            version.decision === "accept"
              ? "客户已确认"
              : version.decision === "reject"
                ? "客户选择继续沟通"
                : "等待客户确认"
          }}
        </p>
      </details>
    </template>
    <button :disabled="props.disabled || review.busy" @click="review.load()">
      刷新到店咨询记录
    </button>
  </section>
</template>
