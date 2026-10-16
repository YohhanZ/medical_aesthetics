<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Typewriter } from "../services/typewriter";

const props = defineProps<{ text: string; animate: boolean }>();
const emit = defineEmits<{ progress: []; complete: [] }>();
const shown = ref(props.animate ? "" : props.text);
const typing = ref(false);
let mounted = false;
let motion: MediaQueryList | undefined;
const player = new Typewriter((text, active) => {
  const wasTyping = typing.value;
  shown.value = text;
  typing.value = active;
  emit("progress");
  if (wasTyping && !active) emit("complete");
});
function finish() {
  player.dispose();
  const wasTyping = typing.value;
  shown.value = props.text;
  typing.value = false;
  emit("progress");
  if (wasTyping || props.animate) emit("complete");
}
function onVisibility() {
  if (document.hidden) finish();
}
function onMotion() {
  if (motion?.matches) finish();
}
onMounted(() => {
  mounted = true;
  motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  motion.addEventListener("change", onMotion);
  document.addEventListener("visibilitychange", onVisibility);
  if (props.animate && props.text && !motion.matches && !document.hidden)
    player.start(props.text);
  else finish();
});
// A mounted history entry or a revalidated answer must never start a fresh animation.
watch([() => props.text, () => props.animate], () => {
  if (mounted) finish();
});
onBeforeUnmount(() => {
  player.dispose();
  document.removeEventListener("visibilitychange", onVisibility);
  motion?.removeEventListener("change", onMotion);
});
</script>

<template>
  <span class="typewriter-text">
    <span aria-hidden="true"
      >{{ shown }}<span v-if="typing" class="typing-cursor"></span
    ></span>
    <span class="sr-only typewriter-accessible">{{ text }}</span>
    <button
      v-if="typing"
      type="button"
      class="reveal-answer"
      @click="player.finish()"
    >
      立即显示
    </button>
  </span>
</template>

<style scoped>
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 3px;
  background: #6b8a70;
  vertical-align: -0.12em;
  animation: caret-blink 0.8s steps(1) infinite;
}
.reveal-answer {
  display: inline-block;
  margin-left: 12px;
  padding: 2px 0;
  font-size: 10px;
  color: #788a74;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.typewriter-accessible {
  user-select: none;
}
@keyframes caret-blink {
  50% {
    opacity: 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .typing-cursor {
    animation: none;
  }
}
</style>
