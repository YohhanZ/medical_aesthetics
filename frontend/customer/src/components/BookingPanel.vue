<script setup lang="ts">
import { computed, markRaw, reactive, ref, watch } from "vue";
import type { Conversation } from "../services/conversation";
import {
  Booking,
  confirmationText,
  type BookingApi,
} from "../services/booking";
import { ApiError, errorText } from "../services/api";
import AppointmentActions from "./AppointmentActions.vue";
import CaseReviewPanel from "./CaseReviewPanel.vue";
import FollowupPanel from "./FollowupPanel.vue";
const props = defineProps<{ chat: Conversation; api: BookingApi }>();
const booking = reactive(new Booking(markRaw(props.api))) as Booking;
const form = reactive({
  name: "",
  phone: "",
  desired_at: "",
  intention: "不确定项目，先咨询",
  project_version_id: "",
});
const code = ref(""),
  smsConsent = ref(false),
  accepted = ref(false);
const disabled = computed(
  () =>
    !props.chat.ready ||
    props.chat.busy ||
    props.chat.refreshing ||
    !!props.chat.pending ||
    booking.busy ||
    booking.loading,
);
const visible = computed(
  () =>
    !!booking.error ||
    !!booking.pending ||
    !!booking.state?.trigger_run_id ||
    !!booking.state?.draft ||
    !!booking.state?.appointments.length,
);
function clearForm() {
  form.name = form.phone = form.desired_at = form.project_version_id = "";
  form.intention = "不确定项目，先咨询";
  code.value = "";
  smsConsent.value = accepted.value = false;
}
watch(
  () => `${props.chat.thread}/${props.chat.session?.visitor_id ?? ""}`,
  () => {
    booking.reset();
    clearForm();
  },
);
watch(
  () => [
    props.chat.ready,
    props.chat.thread,
    props.chat.session?.visitor_id,
    props.chat.messages.at(-1)?.id,
    props.chat.busy,
    props.chat.refreshing,
  ],
  async () => {
    if (!props.chat.ready) {
      booking.reset();
      clearForm();
      return;
    }
    if (!props.chat.busy && !props.chat.refreshing)
      await booking.bind(props.chat.thread, props.chat.session!.visitor_id);
  },
  { immediate: true },
);
watch(
  () => booking.state?.draft?.id,
  () => {
    accepted.value = smsConsent.value = false;
    code.value = "";
    form.phone = "";
  },
);
watch(
  () => booking.state?.verification?.id,
  () => {
    accepted.value = false;
    code.value = "";
  },
);
watch(
  () => booking.state,
  (state) => {
    if (!state) clearForm();
  },
);
function edit() {
  clearForm();
  const draft = booking.state?.draft;
  if (draft) {
    form.name = draft.name;
    form.intention = draft.intention;
    const date = new Date(draft.desired_at);
    form.desired_at = new Date(
      date.getTime() - date.getTimezoneOffset() * 60000,
    )
      .toISOString()
      .slice(0, 16);
  }
  booking.editing = true;
}
async function save() {
  if (disabled.value) return;
  try {
    await booking.save({
      ...form,
      desired_at: new Date(form.desired_at).toISOString(),
      project_version_id: form.project_version_id || null,
    });
    if (!booking.pending && !booking.editing) clearForm();
  } catch {
    booking.error = "请填写有效的期望时间。";
  }
}
function dateLabel(value: string) {
  return new Date(value).toLocaleString("zh-CN");
}
const states: Record<string, string> = {
  pending_store_confirmation: "待门店确认",
  confirmed: "门店已确认",
  arrived: "已到店",
  completed: "已完成",
  cancelled: "已取消",
  declined: "门店未接受",
  no_show: "未到店",
};
</script>
<template>
  <section
    v-if="visible"
    class="booking-panel"
    aria-label="对话内预约申请"
    :aria-busy="booking.busy || booking.loading"
  >
    <div class="booking-heading">
      <span>YOUR NEXT STEP</span>
      <h3>把下一步，交给一次沟通。</h3>
    </div>
    <p v-if="booking.state?.simulated_verification" class="booking-simulation">
      本地模拟核验 · 不发送真实短信 · 不代表真实门店可预约
    </p>
    <div v-if="booking.error" class="chat-error" role="alert">
      {{ booking.error }}
      <button :disabled="disabled" @click="booking.reload()">
        重新核实预约记录
      </button>
    </div>
    <div v-if="booking.pending" class="booking-actions">
      <p>结果尚未核实，继续使用原请求，避免重复提交。</p>
      <button :disabled="disabled" @click="booking.reload()">
        核实预约记录</button
      ><button :disabled="disabled" @click="booking.retry()">
        重试原预约操作
      </button>
    </div>
    <template v-if="booking.state && !booking.loading">
      <article
        v-for="appointment in booking.state.appointments"
        :key="appointment.id"
        class="appointment-receipt"
      >
        <strong
          >{{ states[appointment.state] ?? "状态待核实"
          }}{{ appointment.simulated ? " · 模拟申请" : "" }}</strong
        >
        <p>
          {{ appointment.store_name }} ·
          {{ dateLabel(appointment.desired_at) }}（期望时间）
        </p>
        <p>
          {{ appointment.name }} · {{ appointment.phone_masked }} ·
          {{ appointment.intention }}
        </p>
        <p v-if="appointment.state === 'pending_store_confirmation'">
          申请已持久保存；门店尚未确认时间，请等待进一步联系。
        </p>
        <p
          v-else-if="
            ['confirmed', 'arrived', 'completed'].includes(appointment.state) &&
            appointment.confirmed_at
          "
        >
          门店已确认到店时间：{{
            dateLabel(appointment.confirmed_at)
          }}。具体项目仍需到店沟通确认。
        </p>
        <p v-else-if="appointment.state === 'declined'">
          {{
            appointment.decision_reason === "no_availability"
              ? "期望时间暂无接待安排"
              : appointment.decision_reason === "unable_to_contact"
                ? "门店暂未能联系确认"
                : "门店暂无法接待，请进一步沟通"
          }}。本次申请未成为已确认预约。
        </p>
        <small>申请编号 {{ appointment.id }}</small>
        <CaseReviewPanel
          v-if="appointment.state === 'arrived'"
          :key="`${chat.thread}/${appointment.id}`"
          :api="api"
          :thread="chat.thread"
          :visitor="chat.session!.visitor_id"
          :appointment="appointment.id"
          :refresh="appointment"
          :disabled="disabled || !!booking.pending"
        />
        <FollowupPanel
          v-if="appointment.state === 'arrived'"
          :key="`followup/${chat.thread}/${appointment.id}`"
          :api="api"
          :thread="chat.thread"
          :visitor="chat.session!.visitor_id"
          :appointment="appointment.id"
          :refresh="appointment"
          :disabled="disabled || !!booking.pending"
        />
        <AppointmentActions
          :appointment="appointment"
          :disabled="disabled || !!booking.pending"
          @cancel="booking.cancel(appointment.id, $event)"
          @respond="
            (decision, accepted) =>
              booking.respond(appointment.id, decision, accepted)
          "
        />
      </article>
      <p v-if="!booking.state.configured">
        {{ errorText(new ApiError("verification_not_configured")) }}
      </p>
      <template v-else>
        <p v-if="booking.state.blocked_reason" class="booking-blocked">
          {{ errorText(new ApiError(booking.state.blocked_reason)) }}
        </p>
        <form
          v-if="
            booking.editing && booking.state.trigger_run_id && !booking.pending
          "
          class="booking-form"
          @submit.prevent="save"
        >
          <p>
            预约信息只用于本次申请与门店联系，不发送给模型；先保存草稿，再核验与确认。
          </p>
          <label
            >怎么称呼您<input
              v-model="form.name"
              required
              maxlength="40"
              autocomplete="off"
              :disabled="disabled"
          /></label>
          <label
            >预约联系手机号<input
              v-model="form.phone"
              required
              type="tel"
              pattern="1[3-9][0-9]{9}"
              inputmode="tel"
              maxlength="11"
              autocomplete="off"
              :disabled="disabled"
              placeholder="请输入中国大陆手机号"
          /></label>
          <label
            >期望到店时间<input
              v-model="form.desired_at"
              required
              type="datetime-local"
              :disabled="disabled"
          /></label>
          <label
            >咨询方向<select
              v-model="form.project_version_id"
              :disabled="disabled"
            >
              <option value="">不确定项目，先咨询</option>
              <option
                v-for="project in chat.projects"
                :key="project.id"
                :value="project.id"
              >
                {{ project.title }}{{ project.simulated ? " · 模拟目录" : "" }}
              </option>
            </select></label
          >
          <label class="booking-wide"
            >想了解什么<textarea
              v-model="form.intention"
              required
              rows="2"
              maxlength="300"
              :disabled="disabled"
              placeholder="仅填写咨询方向，不填写病历或个人医疗情况"
            ></textarea>
          </label>
          <div class="booking-actions booking-wide">
            <button class="booking-primary" :disabled="disabled">
              保存并审阅草稿</button
            ><button
              type="button"
              :disabled="disabled"
              @click="
                booking.editing = false;
                clearForm();
              "
            >
              继续了解
            </button>
          </div>
        </form>
        <button
          v-else-if="
            !booking.state.draft &&
            booking.state.trigger_run_id &&
            !booking.pending
          "
          class="booking-primary"
          :disabled="disabled"
          @click="edit"
        >
          在对话中完善预约信息
        </button>
        <template v-if="booking.state.draft && !booking.editing">
          <article class="booking-summary">
            <h4>请审阅这份预约草稿</h4>
            <dl>
              <div>
                <dt>门店</dt>
                <dd>{{ booking.state.draft.store_name }}</dd>
              </div>
              <div>
                <dt>称呼与联系</dt>
                <dd>
                  {{ booking.state.draft.name }} ·
                  {{ booking.state.draft.phone_masked }}
                </dd>
              </div>
              <div>
                <dt>期望时间</dt>
                <dd>{{ dateLabel(booking.state.draft.desired_at) }}</dd>
              </div>
              <div>
                <dt>咨询方向</dt>
                <dd>
                  {{
                    booking.state.draft.project_title ?? "不确定项目，先咨询"
                  }}
                </dd>
              </div>
              <div>
                <dt>咨询意向</dt>
                <dd>{{ booking.state.draft.intention }}</dd>
              </div>
            </dl>
            <small
              >草稿有效至
              {{
                dateLabel(booking.state.draft.expires_at)
              }}；修改后需要重新核验与确认。</small
            >
          </article>
          <details class="answer-sources">
            <summary>
              本次预约依据 · {{ booking.state.draft.policy.title }} · 版本
              {{ booking.state.draft.policy.version }}
            </summary>
            <p>{{ booking.state.draft.policy.content }}</p>
            <small
              >{{ booking.state.draft.policy.source
              }}{{
                booking.state.draft.policy.simulated ? " · 模拟政策" : ""
              }}</small
            >
          </details>
          <template v-if="!booking.state.blocked_reason && !booking.pending">
            <template v-if="!booking.state.verification?.verified">
              <label class="booking-check"
                ><input
                  v-model="smsConsent"
                  type="checkbox"
                  :disabled="disabled"
                />我同意向草稿中的号码发送预约核验验证码{{
                  booking.state.simulated_verification ? "（本次仅模拟）" : ""
                }}</label
              >
              <div class="booking-actions">
                <button
                  :disabled="disabled || !smsConsent"
                  @click="booking.send(smsConsent)"
                >
                  {{
                    booking.state.verification ? "重新获取验证码" : "获取验证码"
                  }}
                </button>
              </div>
              <div
                v-if="booking.state.verification"
                class="booking-verification"
              >
                <p
                  v-if="booking.state.verification.delivery_state === 'unknown'"
                >
                  发送结果未知，不会自动重发；如已收到短信可继续核验，否则请等待本次验证码过期。
                </p>
                <p
                  v-else-if="
                    booking.state.verification.delivery_state === 'rejected'
                  "
                >
                  短信请求未被接受，请稍后重新获取。
                </p>
                <p v-else>
                  {{
                    booking.state.verification.simulated
                      ? "模拟验证码已生成"
                      : "验证码发送请求已接受，请查看短信"
                  }}
                  · 有效至
                  {{ dateLabel(booking.state.verification.expires_at) }}
                </p>
                <p
                  v-if="booking.state.verification.simulated_code"
                  class="simulated-code"
                >
                  本地演练验证码：{{
                    booking.state.verification.simulated_code
                  }}
                </p>
                <form
                  class="booking-code-form"
                  @submit.prevent="booking.verify(code)"
                >
                  <label
                    >预约核验验证码<input
                      v-model="code"
                      required
                      pattern="[0-9]{6}"
                      maxlength="6"
                      inputmode="numeric"
                      autocomplete="one-time-code"
                      :disabled="disabled" /></label
                  ><button
                    :disabled="
                      disabled ||
                      code.length !== 6 ||
                      booking.state.verification.attempts_remaining === 0
                    "
                  >
                    核验手机号
                  </button>
                </form>
              </div>
            </template>
            <template v-else
              ><p class="booking-verified">联系方式已核验，请确认当前草稿。</p>
              <label class="booking-check"
                ><input
                  v-model="accepted"
                  type="checkbox"
                  :disabled="disabled"
                />我确认以上申请内容，并同意门店使用此号码联系本次预约。我了解时间仍需门店确认。</label
              ><button
                class="booking-primary"
                :disabled="disabled || !accepted"
                @click="booking.confirm(accepted)"
              >
                {{ confirmationText }}
              </button></template
            >
          </template>
          <div v-if="!booking.pending" class="booking-actions">
            <button
              :disabled="disabled || !booking.state.trigger_run_id"
              @click="edit"
            >
              修改信息并重新核验</button
            ><button :disabled="disabled" @click="booking.discard()">
              撤销草稿，继续了解
            </button>
          </div>
        </template>
      </template>
      <button
        class="booking-refresh"
        :disabled="disabled"
        @click="booking.reload()"
      >
        刷新预约状态
      </button>
    </template>
  </section>
</template>
