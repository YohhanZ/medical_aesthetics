<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { X } from "lucide-vue-next";
defineProps<{ title: string; subtitle?: string }>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement | null>(null);
let previous: HTMLElement | null = null;
let previousOverflow = "";
function key(event: KeyboardEvent) {
  if (event.key === "Escape") emit("close");
  if (event.key !== "Tab") return;
  const items = [
    ...panel.value!.querySelectorAll<HTMLElement>(
      "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
    ),
  ].filter((e) => e.offsetParent !== null);
  const first = items[0],
    last = items.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}
onMounted(async () => {
  previous = document.activeElement as HTMLElement;
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  document.getElementById("admin-shell")?.setAttribute("inert", "");
  await nextTick();
  panel.value?.querySelector<HTMLButtonElement>("button")?.focus();
  document.addEventListener("keydown", key);
});
onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow;
  document.getElementById("admin-shell")?.removeAttribute("inert");
  document.removeEventListener("keydown", key);
  previous?.focus();
});
</script>
<template>
  <Teleport to="body"
    ><div class="panel-backdrop" @click.self="emit('close')">
      <section
        ref="panel"
        class="side-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="panel-title"
      >
        <header>
          <div>
            <p class="eyebrow">{{ subtitle || "运营工作台" }}</p>
            <h2 id="panel-title">{{ title }}</h2>
          </div>
          <button
            class="icon-button"
            aria-label="关闭详情"
            @click="emit('close')"
          >
            <X :size="20" />
          </button>
        </header>
        <div class="panel-content"><slot /></div>
      </section></div
  ></Teleport>
</template>
