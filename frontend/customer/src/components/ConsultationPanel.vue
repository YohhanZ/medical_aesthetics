<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import {
  ArrowUp,
  ArrowUpRight,
  Plus,
  PanelLeft,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-vue-next";
import type { Conversation } from "../services/conversation";
import ProjectCard from "./ProjectCard.vue";
import BookingPanel from "./BookingPanel.vue";
import type { BookingApi } from "../services/booking";
import type { Message } from "../types";
import TypewriterText from "./TypewriterText.vue";
import ConversationList from "./ConversationList.vue";
const props = defineProps<{ chat: Conversation; bookingApi: BookingApi }>();
const drawer = ref<HTMLDialogElement | null>(null);
const drawerOpen = ref(false);
async function openHistory() {
  drawer.value?.showModal();
  drawerOpen.value = true;
  await nextTick();
  drawer.value
    ?.querySelector<HTMLElement>('[aria-current="true"]')
    ?.scrollIntoView({ block: "nearest" });
}
function closeHistory() {
  drawer.value?.close();
  drawerOpen.value = false;
}
async function selectThread(id: string) {
  await props.chat.selectThread(id);
  if (props.chat.thread === id) closeHistory();
}
async function newConversation() {
  const previous = props.chat.thread;
  await props.chat.newConversation();
  if (props.chat.thread !== previous) closeHistory();
}
defineEmits<{ reconnect: [] }>();
const question = ref(""),
  log = ref<HTMLElement | null>(null);
const completed = ref(new Set<string>());
const following = ref(true);
function isTyping(message: Message | undefined) {
  return Boolean(
    message?.animate &&
      message.role === "assistant" &&
      message.id === props.chat.messages.at(-1)?.id &&
      !props.chat.refreshing &&
      !completed.value.has(message.id),
  );
}
const typing = computed(() => isTyping(props.chat.messages.at(-1)));
function finishTyping(id: string) {
  completed.value.add(id);
  void scrollReply();
}
function onScroll() {
  if (log.value)
    following.value =
      log.value.scrollHeight - log.value.clientHeight - log.value.scrollTop <
      72;
}
async function scrollReply() {
  await nextTick();
  if (following.value)
    log.value?.scrollTo({ top: log.value.scrollHeight, behavior: "auto" });
}
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
  [
    () => props.chat.messages.at(-1)?.id,
    () => props.chat.thread,
    () => props.chat.busy,
  ],
  ([id, thread], [previousId, previousThread]) => {
    if (thread !== previousThread) {
      completed.value.clear();
      question.value = "";
    }
    if (id !== previousId || thread !== previousThread) following.value = true;
    void scrollReply();
  },
);
</script>
<template>
  <div class="consultation-workspace">
    <aside class="consultation-sidebar" aria-label="咨询会话列表">
      <ConversationList
        :chat="chat"
        @select="selectThread"
        @create="newConversation"
        @more="chat.moreThreads()"
      />
    </aside>
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
              chat.busy
                ? "正在处理"
                : typing
                  ? "正在回复"
                  : chat.ready
                    ? "可以开始咨询"
                    : "等待连接"
            }}</span
          >
        </div>
        <div class="conversation-mobile-actions">
          <button
            type="button"
            class="history-drawer-button"
            aria-label="打开历史对话"
            aria-haspopup="dialog"
            :aria-expanded="drawerOpen"
            @click="openHistory"
          >
            <PanelLeft :size="18" :stroke-width="1.5" /><span>历史对话</span>
          </button>
          <button
            class="reset-button"
            type="button"
            :disabled="chat.busy || !chat.ready || chat.refreshing"
            @click="newConversation()"
          >
            <Plus :size="15" /> 新对话
          </button>
        </div>
      </div>
      <p v-if="chat.session?.simulated" class="booking-simulation" role="note">
        演示模式 ·
        门店、人员、供给和价格为虚构设定；公开科普仅经模拟复核，不代表真实医学批准。
      </p>
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
      <div ref="log" class="consultation-body" @scroll="onScroll">
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
          class="conversation live-conversation"
          role="log"
          aria-label="咨询对话"
          aria-live="polite"
          :aria-busy="chat.busy || chat.refreshing || typing"
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
                <TypewriterText
                  v-if="message.role === 'assistant' && !chat.refreshing"
                  :text="message.text"
                  :animate="isTyping(message)"
                  @progress="scrollReply"
                  @complete="finishTyping(message.id)"
                />
                <template v-else>{{
                  chat.refreshing && message.role === "assistant"
                    ? "正在核验最新资料…"
                    : message.text
                }}</template>
              </p>
              <template
                v-if="message.result && !chat.refreshing && !isTyping(message)"
              >
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
                  <div
                    v-for="source in message.result.evidence"
                    :key="source.id"
                  >
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
          <div
            v-if="chat.busy"
            class="typing"
            aria-label="正在检索资料并准备回答"
          >
            <i></i><i></i><i></i>
          </div>
        </div>
        <BookingPanel :chat="chat" :api="bookingApi" />
      </div>
      <form class="composer" @submit.prevent="ask()">
        <label class="sr-only" for="question">您的咨询问题</label
        ><textarea
          id="question"
          v-model="question"
          rows="2"
          maxlength="2000"
          :disabled="
            !chat.ready || chat.busy || !!chat.pending || chat.refreshing
          "
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
  </div>
  <Teleport to="body">
    <dialog
      ref="drawer"
      class="conversation-drawer"
      aria-label="历史对话"
      @close="drawerOpen = false"
      @click="if ($event.target === drawer) closeHistory();"
    >
      <div class="conversation-drawer__surface">
        <button
          type="button"
          class="conversation-drawer__close"
          aria-label="关闭历史对话"
          @click="closeHistory"
        >
          <X :size="19" :stroke-width="1.5" />
        </button>
        <ConversationList
          :chat="chat"
          @select="selectThread"
          @create="newConversation"
          @more="chat.moreThreads()"
        />
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.consultation-workspace {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  height: clamp(560px, 78svh, 760px);
  border: 1px solid #e2e8dd;
  border-radius: 24px;
  background: #fff;
  box-shadow: 0 12px 55px #3d563c04;
  overflow: hidden;
}
.consultation-sidebar {
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  background: #f6f8f2;
  border-right: 1px solid #e5eade;
}
.consultation-sidebar :deep(.conversation-list__items) {
  flex: 1;
  min-height: 0;
  max-height: none;
  overscroll-behavior-y: contain;
}
.consultation-workspace > .consultation-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  padding: 26px 26px 18px;
}
.consultation-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior-y: contain;
  scrollbar-width: thin;
  scrollbar-color: #d5dfcd transparent;
  margin-bottom: 16px;
}
.consultation-workspace .concierge-header,
.consultation-card > .booking-simulation,
.consultation-card > .chat-error,
.consultation-workspace .chat-disclaimer {
  flex-shrink: 0;
}
.consultation-workspace .chat-welcome {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 58px 0 48px;
}
.consultation-workspace .composer {
  flex-shrink: 0;
  margin-top: auto;
}
.consultation-workspace .chat-welcome h3 {
  font-size: 23px;
}
.consultation-workspace .suggestions {
  gap: 8px;
}
.consultation-workspace .suggestions button {
  font-size: 10px;
  padding: 11px 12px;
  gap: 8px;
}
.consultation-workspace .live-conversation {
  max-height: none;
  overflow: visible;
  padding-top: 28px;
}
.consultation-workspace .live-conversation > * {
  flex-shrink: 0;
}
.consultation-workspace .booking-panel {
  margin: 16px 0 22px;
  padding: 20px;
}
.consultation-workspace .booking-simulation {
  font-size: 10px;
  line-height: 1.8;
  color: #9ba48f;
  margin-top: 16px;
}
.conversation-mobile-actions {
  display: none;
}
.conversation-drawer {
  border: 0;
  padding: 0;
  margin: 0;
  max-width: none;
  max-height: none;
  width: min(320px, 88vw);
  height: 100dvh;
  background: #f6f8f2;
  color: #36523e;
  box-shadow: 15px 0 70px #17331f26;
}
.conversation-drawer::backdrop {
  background: #17331f55;
  backdrop-filter: blur(4px);
}
.conversation-drawer__surface {
  position: relative;
  height: 100%;
  overflow: auto;
  padding-top: 26px;
}
.conversation-drawer__close {
  position: absolute;
  top: 15px;
  right: 15px;
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: 1px solid #e1e7da;
  border-radius: 50%;
  background: #fff;
  color: #809272;
}
.conversation-drawer[open] {
  animation: drawer-enter 0.2s ease-out;
}
@keyframes drawer-enter {
  from {
    transform: translateX(-30px);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}
@media (max-width: 1000px) and (min-width: 761px) {
  .consultation-workspace {
    grid-template-columns: 204px minmax(0, 1fr);
  }
  .consultation-workspace > .consultation-card {
    padding: 23px 20px 17px;
  }
  .consultation-workspace .suggestions {
    flex-direction: column;
  }
  .consultation-workspace .suggestions button {
    justify-content: space-between;
  }
}
@media (max-width: 760px) {
  .consultation-workspace {
    grid-template-columns: minmax(0, 1fr);
    height: clamp(480px, 78svh, 680px);
    border-radius: 20px;
  }
  .consultation-sidebar {
    display: none;
  }
  .consultation-workspace > .consultation-card {
    padding: 20px 16px 14px;
  }
  .conversation-mobile-actions {
    display: flex;
    align-items: center;
    margin-left: auto;
    gap: 12px;
  }
  .history-drawer-button {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 8px 0;
    color: #809272;
    font-size: 10px;
  }
  .reset-button {
    padding: 8px 0;
    font-size: 10px;
  }
  .concierge-header {
    flex-wrap: wrap;
    gap: 10px;
  }
  .consultation-workspace .chat-welcome {
    padding: 33px 0 30px;
  }
  .consultation-workspace .chat-welcome h3 {
    font-size: 20px;
  }
  .consultation-workspace .booking-panel {
    padding: 16px;
  }
}
@media (max-width: 410px) {
  .history-drawer-button span {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .conversation-drawer[open] {
    animation: none;
  }
}
</style>
