<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, reactive, watch } from "vue";
import RefinedSelect from "./RefinedSelect.vue";
const outcomeOptions = [
  { value: "resolved", label: "目前没有其他疑问" },
  { value: "need_help", label: "希望门店继续沟通" },
] as const;
import {
  FollowupReview,
  followupLabels,
  followupTexts,
  type CustomerFollowupApi,
  type Followup,
} from "../services/followups";
const props = defineProps<{
  api: CustomerFollowupApi;
  thread: string;
  visitor: string;
  appointment: string;
  refresh: object;
  disabled: boolean;
}>();
const review = reactive(new FollowupReview(markRaw(props.api)));
const forms = reactive<
  Record<
    string,
    { checked: boolean; result: "resolved" | "need_help"; feedback: string }
  >
>({});
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
  () => review.items,
  (rows) => {
    for (const id of Object.keys(forms)) delete forms[id];
    for (const row of rows)
      forms[row.id] = { checked: false, result: "resolved", feedback: "" };
  },
);
function changed(row: Followup) {
  forms[row.id]!.checked = false;
}
onBeforeUnmount(() => review.reset());
const date = (value: string) => new Date(value).toLocaleString("zh-CN");
</script>
<template>
  <section
    v-if="review.items.length || review.error || review.pending"
    class="booking-summary"
    aria-label="站内回访"
  >
    <h4>咨询之后，也可以继续沟通</h4>
    <p>回访仅在这段对话中进行。您可以拒绝或取消；这不会代表治疗同意。</p>
    <p v-if="review.error" role="alert" class="chat-error">
      {{ review.error }}
    </p>
    <div v-if="review.pending" class="booking-actions">
      <p>结果尚未核实，请使用原请求。</p>
      <button :disabled="props.disabled || review.busy" @click="review.retry()">
        重试原回访操作
      </button>
    </div>
    <article v-for="row in review.items" :key="row.id" class="booking-summary">
      <p v-if="row.simulated" class="booking-simulation">
        本地模拟回访 · 不发送短信
      </p>
      <strong>{{ followupLabels[row.state] }}</strong>
      <p>
        计划回访时间：{{ date(row.due_at) }} · 来源咨询版本
        {{ row.case_version }}
      </p>
      <p>{{ row.message }}</p>
      <p v-if="!row.source_current">
        此计划源于较早的咨询版本；未同意的旧计划需门店重新安排。
      </p>
      <p v-if="row.opted_out">
        这份档案已暂停回访邀请。恢复后，新的计划仍需您逐次同意。
      </p>
      <template v-if="row.state === 'scheduled'">
        <p>可提前反馈。仅记录沟通需求，请勿提交病历、身份或治疗记录。</p>
        <label
          >目前是否还有疑问<RefinedSelect
            v-model="forms[row.id]!.result"
            label="目前是否还有疑问"
            :options="outcomeOptions"
            :disabled="disabled"
            @change="changed(row)"
        /></label>
        <label
          >回访反馈<textarea
            v-model="forms[row.id]!.feedback"
            maxlength="500"
            rows="2"
            :disabled="disabled"
            @input="changed(row)"
          ></textarea>
        </label>
      </template>
      <label
        v-if="
          row.state === 'awaiting_confirmation' ||
          row.state === 'scheduled' ||
          row.opted_out
        "
        class="booking-check"
        ><input
          v-model="forms[row.id]!.checked"
          type="checkbox"
          :disabled="disabled"
        />我已审阅回访计划，确认下面选择的处理方式</label
      >
      <div class="booking-actions">
        <template v-if="row.state === 'awaiting_confirmation'">
          <button
            :disabled="disabled || !forms[row.id]!.checked"
            @click="review.respond(row, 'reject', forms[row.id]!.checked)"
          >
            {{ followupTexts.reject }}
          </button>
          <button
            class="booking-primary"
            :disabled="
              disabled || !forms[row.id]!.checked || !row.source_current
            "
            @click="review.respond(row, 'accept', forms[row.id]!.checked)"
          >
            {{ followupTexts.accept }}
          </button>
        </template>
        <template v-if="row.state === 'scheduled'">
          <button
            :disabled="disabled || !forms[row.id]!.checked"
            @click="review.respond(row, 'cancel', forms[row.id]!.checked)"
          >
            {{ followupTexts.cancel }}
          </button>
          <button
            class="booking-primary"
            :disabled="disabled || !forms[row.id]!.checked"
            @click="
              review.respond(
                row,
                'feedback',
                forms[row.id]!.checked,
                forms[row.id]!.result,
                forms[row.id]!.feedback,
              )
            "
          >
            {{ followupTexts.feedback }}
          </button>
        </template>
        <button
          v-if="row.opted_out"
          :disabled="disabled || !forms[row.id]!.checked"
          @click="review.respond(row, 'resume', forms[row.id]!.checked)"
        >
          {{ followupTexts.resume }}
        </button>
      </div>
      <p v-if="row.state === 'completed'">
        反馈已保存供门店查看，不代表人工已回复。
      </p>
      <details class="answer-sources">
        <summary>查看回访处理历史</summary>
        <p v-for="event in row.history" :key="event.version">
          {{ date(event.recorded_at) }} ·
          {{
            event.confirmation_text ||
            (event.kind === "created" ? "门店提出计划" : "门店取消计划")
          }}<br />{{
            event.result === "need_help"
              ? "希望门店继续沟通"
              : event.result === "resolved"
                ? "目前没有其他疑问"
                : ""
          }}
          {{ event.feedback }}
        </p>
      </details>
    </article>
    <button :disabled="props.disabled || review.busy" @click="review.load()">
      刷新站内回访
    </button>
  </section>
</template>
