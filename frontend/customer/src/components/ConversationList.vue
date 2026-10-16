<script setup lang="ts">
import { computed } from "vue";
import { ArrowUpRight, MessageCircle, Plus } from "lucide-vue-next";
import type { Conversation } from "../services/conversation";

const props = defineProps<{ chat: Conversation }>();
defineEmits<{ select: [thread: string]; create: []; more: [] }>();
const disabled = computed(
  () => !props.chat.ready || props.chat.busy || props.chat.refreshing,
);
function dateLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
}
</script>

<template>
  <div class="conversation-list">
    <div class="conversation-list__heading">
      <span>YOUR CONVERSATIONS</span>
      <h3>每次咨询，都在这里。</h3>
    </div>
    <button
      type="button"
      class="conversation-list__new"
      :disabled="disabled"
      @click="$emit('create')"
    >
      <Plus :size="17" :stroke-width="1.6" /> 新建对话
      <ArrowUpRight :size="15" :stroke-width="1.5" />
    </button>
    <div class="conversation-list__section">
      最近的咨询 <span>{{ chat.threads.length }} 段</span>
    </div>
    <nav
      class="conversation-list__items"
      aria-label="历史咨询会话"
      :aria-busy="chat.loadingThreads"
    >
      <button
        v-for="thread in chat.threads"
        :key="thread.thread_id"
        type="button"
        class="conversation-list__item"
        :class="{ 'is-current': thread.thread_id === chat.thread }"
        :aria-current="thread.thread_id === chat.thread ? 'true' : undefined"
        :aria-label="`打开会话：${thread.title || '新对话'}`"
        :disabled="disabled"
        @click="$emit('select', thread.thread_id)"
      >
        <MessageCircle :size="16" :stroke-width="1.4" aria-hidden="true" />
        <span class="conversation-list__copy"
          ><strong>{{ thread.title || "新对话" }}</strong>
          <small>{{
            thread.thread_id === chat.thread
              ? "当前对话"
              : dateLabel(thread.created_at)
          }}</small>
        </span>
        <span
          v-if="thread.thread_id === chat.thread"
          class="conversation-list__dot"
          aria-hidden="true"
        ></span>
      </button>
      <p v-if="!chat.threads.length" class="conversation-list__empty">
        你的咨询，将从这里开始。
      </p>
      <button
        v-if="chat.hasMoreThreads"
        type="button"
        class="conversation-list__more"
        :disabled="disabled || chat.loadingThreads"
        @click="$emit('more')"
      >
        {{ chat.loadingThreads ? "正在加载…" : "查看更早的会话" }}
      </button>
    </nav>
    <p
      v-if="chat.threadListError"
      class="conversation-list__error"
      role="status"
    >
      {{ chat.threadListError }}
    </p>
    <div class="conversation-list__footer">
      <span></span> 随时回来，继续聊聊。
    </div>
  </div>
</template>

<style scoped>
.conversation-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 26px 16px 20px;
  color: #36523e;
}
.conversation-list__heading {
  padding: 0 8px;
}
.conversation-list__heading > span {
  font-size: 8px;
  letter-spacing: 0.16em;
  color: #8b9a80;
}
.conversation-list__heading h3 {
  font-size: 15px;
  line-height: 1.6;
  letter-spacing: -0.02em;
  font-weight: 500;
  margin: 10px 0 24px;
}
.conversation-list__new {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 12px 14px;
  min-height: 44px;
  border: 1px solid #d9e3d1;
  border-radius: 12px;
  background: #fff;
  font-size: 12px;
  box-shadow: 0 3px 9px #264f3e04;
  transition:
    background 0.18s,
    border-color 0.18s;
}
.conversation-list__new svg:last-child {
  margin-left: auto;
  color: #93a287;
}
.conversation-list__new:not(:disabled):hover {
  background: #edf3e7;
  border-color: #b8c9ac;
}
.conversation-list__section {
  display: flex;
  justify-content: space-between;
  padding: 26px 9px 12px;
  color: #8a9782;
  font-size: 10px;
}
.conversation-list__section > span {
  color: #a5ae9d;
  font-size: 9px;
}
.conversation-list__items {
  display: flex;
  flex-direction: column;
  gap: 5px;
  max-height: 510px;
  min-height: 170px;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: #d5dfcd transparent;
  padding: 2px;
  margin: -2px;
}
.conversation-list__item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 69px;
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 12px 10px;
  color: #7a8a70;
  text-align: left;
  transition: background 0.18s;
  flex-shrink: 0;
}
.conversation-list__item:not(:disabled):hover {
  background: #edf2e7;
}
.conversation-list__item.is-current {
  background: #e6edde;
  border-color: #dce6d3;
  color: #365638;
}
.conversation-list__copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.conversation-list__copy strong {
  display: block;
  font-size: 12px;
  line-height: 1.5;
  font-weight: 450;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conversation-list__copy small {
  font-size: 9px;
  line-height: 1.4;
  color: #98a28e;
}
.conversation-list__item.is-current small {
  color: #7d946e;
}
.conversation-list__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #839c70;
  flex-shrink: 0;
}
.conversation-list__empty {
  font-size: 11px;
  color: #98a28e;
  padding: 20px 10px;
  line-height: 1.8;
}
.conversation-list__more {
  padding: 13px 8px;
  min-height: 44px;
  color: #7f9172;
  font-size: 11px;
  flex-shrink: 0;
}
.conversation-list__error {
  font-size: 11px;
  line-height: 1.7;
  color: #926d50;
  padding: 12px 8px 0;
}
.conversation-list__footer {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: auto;
  padding: 30px 8px 0;
  font-size: 10px;
  color: #9ca68f;
}
.conversation-list__footer > span {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #9db08c;
}
button:disabled {
  opacity: 0.5;
}
@media (prefers-reduced-motion: reduce) {
  button {
    transition: none;
  }
}
</style>
