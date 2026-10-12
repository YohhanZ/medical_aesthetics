<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import {
  ArrowUp,
  ArrowUpRight,
  Plus,
  ShieldCheck,
  Sparkles,
} from "lucide-vue-next";
import type { Conversation } from "../services/conversation";
import ProjectCard from "./ProjectCard.vue";
import BookingPanel from "./BookingPanel.vue";
import type { BookingApi } from "../services/booking";
const props = defineProps<{ chat: Conversation; bookingApi: BookingApi }>();
defineEmits<{ reconnect: [] }>();
const question = ref(""),
  log = ref<HTMLElement | null>(null);
async function ask(text = question.value) {
  if (
    !props.chat.ready ||
    props.chat.busy ||
    props.chat.pending ||
    !text.trim()
  )
    return;
  question.value = "";
  await props.chat.send(text);
}
watch(
  () => [props.chat.messages.length, props.chat.busy],
  async () => {
    await nextTick();
    log.value?.scrollTo({ top: log.value.scrollHeight, behavior: "smooth" });
  },
);
</script>
<template>
  <div
    class="consultation-card"
    :class="{ 'chat-active': chat.messages.length }"
  >
    <div class="concierge-header">
      <div class="concierge-avatar">
        <Sparkles :size="24" :stroke-width="1.5" />
      </div>
      <div>
        <strong>美丽田园 · 咨询助手</strong
        ><span
          ><span class="status-dot"></span>
          {{
            chat.busy ? "正在处理" : chat.ready ? "可以开始咨询" : "等待连接"
          }}</span
        >
      </div>
      <button
        class="reset-button"
        :disabled="chat.busy || !chat.ready || chat.refreshing"
        @click="chat.newConversation()"
      >
        <Plus :size="15" /> 新对话
      </button>
    </div>
    <p v-if="chat.session?.simulated" class="booking-simulation" role="note">
      演示模式 · 门店、人员、供给和价格为虚构设定；公开科普仅经模拟复核，不代表真实医学批准。
    </p>
    <div v-if="chat.threads.length > 1" class="history-picker">
      <label
        >我的对话
        <select
          :value="chat.thread"
          :disabled="chat.busy || chat.refreshing"
          @change="
            chat.selectThread(($event.target as HTMLSelectElement).value)
          "
        >
          <option
            v-for="(thread, index) in chat.threads"
            :key="thread.thread_id"
            :value="thread.thread_id"
          >
            对话 {{ chat.threads.length - index }} ·
            {{ new Date(thread.created_at).toLocaleString("zh-CN") }}
          </option>
        </select></label
      >
    </div>
    <div v-if="chat.error" class="chat-error" role="alert">
      <p>{{ chat.error }}</p>
      <div class="error-actions">
        <button
          v-if="chat.pending && chat.ready"
          :disabled="chat.busy || chat.refreshing"
          @click="chat.retry()"
        >
          重试原消息</button
        ><button
          v-if="chat.ready"
          :disabled="chat.busy || chat.refreshing"
          @click="chat.refresh()"
        >
          核实最新记录</button
        ><button v-else :disabled="chat.busy" @click="$emit('reconnect')">
          重新连接
        </button>
      </div>
    </div>
    <div v-if="!chat.messages.length" class="chat-welcome">
      <h3>今天，想了解些什么？</h3>
      <p>护理、项目、到店流程，都可以直接提问。</p>
      <div class="suggestions">
        <button
          v-for="prompt in [
            '想了解基础补水护理',
            '护理和医美有什么区别？',
            '不确定项目，能先到店咨询吗？',
          ]"
          :key="prompt"
          :disabled="!chat.ready || chat.busy || chat.refreshing"
          @click="ask(prompt)"
        >
          {{ prompt }} <ArrowUpRight :size="14" />
        </button>
      </div>
    </div>
    <div
      v-else
      ref="log"
      class="conversation live-conversation"
      role="log"
      aria-label="咨询对话"
      aria-live="polite"
      :aria-busy="chat.busy || chat.refreshing"
    >
      <button
        v-if="chat.hasOlder"
        class="older-messages"
        :disabled="chat.busy || chat.refreshing"
        @click="chat.older()"
      >
        查看更早的消息
      </button>
      <div
        v-for="message in chat.messages"
        :key="message.id"
        class="message"
        :class="message.role"
      >
        <span v-if="message.role === 'assistant'" class="message-icon"
          ><Sparkles :size="17"
        /></span>
        <div class="message-content">
          <span
            v-if="message.result?.action?.type === 'visit_interest'"
            class="answer-note"
            >预约意愿记录 · 以下为消息发出时的状态</span
          >
          <p>
            {{
              chat.refreshing && message.role === "assistant"
                ? "正在核验最新资料…"
                : message.text
            }}
          </p>
          <template v-if="message.result && !chat.refreshing">
            <div
              v-if="message.result.mode === 'evidence_fallback'"
              class="answer-note"
            >
              暂时以当前可核验资料摘录回答
            </div>
            <div
              v-if="message.result.projects?.length"
              class="answer-projects photographic-projects"
            >
              <ProjectCard
                v-for="project in message.result.projects"
                :key="project.id"
                :project="project"
                compact
              />
            </div>
            <details
              v-if="message.result.evidence.length"
              class="answer-sources"
            >
              <summary>
                查看回答依据 · {{ message.result.evidence.length }} 条
              </summary>
              <div v-for="source in message.result.evidence" :key="source.id">
                <strong>{{ source.title }}</strong
                ><span
                  >版本 {{ source.version
                  }}{{ source.simulated ? " · 模拟资料" : "" }}</span
                >
                <p>{{ source.source }}</p>
              </div>
            </details>
            <div v-if="message.result.handoff" class="handoff-status">
              <strong>转接请求已记录 · 人工尚未接通</strong>
              <p>
                {{
                  message.result.action?.type === "visit_interest"
                    ? "可在下方完善信息、核验并确认申请。当前是否已提交或获门店确认，请查看预约记录。"
                    : "等待有权限的专业人员处理，不代表医学评估或业务操作已完成。"
                }}
              </p>
            </div>
          </template>
          <span
            v-if="
              message.role === 'user' &&
              chat.pending?.message_id === message.message_id
            "
            class="answer-note"
            >{{ chat.busy ? "正在核实与回答…" : "尚未获得完整结果" }}</span
          >
        </div>
      </div>
      <div v-if="chat.busy" class="typing" aria-label="正在检索资料并准备回答">
        <i></i><i></i><i></i>
      </div>
    </div>
    <BookingPanel :chat="chat" :api="bookingApi" />
    <form class="composer" @submit.prevent="ask()">
      <label class="sr-only" for="question">您的咨询问题</label
      ><textarea
        id="question"
        v-model="question"
        rows="2"
        maxlength="2000"
        :disabled="!chat.ready || !!chat.pending || chat.refreshing"
        placeholder="说说你想了解的护理、项目或到店流程…"
        @keydown.enter.exact="
          if (!$event.isComposing) {
            $event.preventDefault();
            ask();
          }
        "
      ></textarea
      ><button
        class="send-button"
        :disabled="
          !question.trim() ||
          !chat.ready ||
          chat.busy ||
          !!chat.pending ||
          chat.refreshing
        "
        aria-label="发送问题"
      >
        <ArrowUp :size="21" />
      </button>
    </form>
    <p class="chat-disclaimer">
      <ShieldCheck :size="12" />
      普通咨询依据已发布资料自动答复；个人医疗判断转专业人员。请勿输入身份、病历或其他敏感记录。
    </p>
  </div>
</template>
