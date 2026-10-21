<script setup lang="ts" generic="T extends string">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  useId,
  watch,
} from "vue";
import { Check, ChevronDown } from "lucide-vue-next";

const props = defineProps<{
  modelValue: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  label: string;
  disabled?: boolean;
  id?: string;
}>();
const emit = defineEmits<{
  "update:modelValue": [value: T];
  change: [value: T];
}>();
const uid = useId();
const listId = `${uid}-options`;
const trigger = ref<HTMLButtonElement | null>(null);
const menu = ref<HTMLElement | null>(null);
const teleportTarget = ref<HTMLElement | string>("body");
const opened = ref(false);
const active = ref(0);
const placement = ref("below");
const menuStyle = ref<Record<string, string>>({});
const selected = computed(() =>
  props.options.find((option) => option.value === props.modelValue),
);
let search = "";
let searchedAt = 0;

function position() {
  if (!opened.value || !trigger.value) return;
  const rect = trigger.value.getBoundingClientRect();
  const viewport = window.visualViewport;
  const leftEdge = (viewport?.offsetLeft ?? 0) + 12;
  const topEdge = (viewport?.offsetTop ?? 0) + 12;
  const rightEdge = leftEdge + (viewport?.width ?? window.innerWidth) - 24;
  const bottomEdge = topEdge + (viewport?.height ?? window.innerHeight) - 24;
  const below = bottomEdge - rect.bottom - 8;
  const above = rect.top - topEdge - 8;
  const upwards = below < 220 && above > below;
  placement.value = upwards ? "above" : "below";
  const height = Math.min(320, Math.max(80, upwards ? above : below));
  const width = Math.min(Math.max(rect.width, 290), rightEdge - leftEdge);
  menuStyle.value = {
    left: `${Math.max(leftEdge, Math.min(rect.left, rightEdge - width))}px`,
    width: `${width}px`,
    maxHeight: `${height}px`,
    ...(upwards
      ? { bottom: `${window.innerHeight - rect.top + 8}px` }
      : { top: `${rect.bottom + 8}px` }),
  };
}
function revealActive() {
  void nextTick(() =>
    menu.value
      ?.querySelector<HTMLElement>(`[data-index="${active.value}"]`)
      ?.scrollIntoView({ block: "nearest" }),
  );
}
function open() {
  if (props.disabled || !props.options.length) return;
  active.value = Math.max(
    0,
    props.options.findIndex((option) => option.value === props.modelValue),
  );
  search = "";
  opened.value = true;
  position();
  revealActive();
}
function close() {
  opened.value = false;
  search = "";
}
function choose(index: number) {
  const option = props.options[index];
  if (props.disabled || !option) return;
  close();
  if (option.value !== props.modelValue) {
    emit("update:modelValue", option.value);
    emit("change", option.value);
  }
  trigger.value?.focus({ preventScroll: true });
}
function onKey(event: KeyboardEvent) {
  if (props.disabled) return;
  if (event.key === "Tab") {
    close();
    return;
  }
  if (event.key === "Escape") {
    if (opened.value) {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
    return;
  }
  if (
    ["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)
  ) {
    event.preventDefault();
    if (!opened.value) {
      open();
      if (event.key === "Home") active.value = 0;
      if (event.key === "End") active.value = props.options.length - 1;
    } else if (event.key === "Enter" || event.key === " ") {
      choose(active.value);
    } else {
      if (event.key === "Home") active.value = 0;
      else if (event.key === "End") active.value = props.options.length - 1;
      else
        active.value = Math.max(
          0,
          Math.min(
            props.options.length - 1,
            active.value + (event.key === "ArrowDown" ? 1 : -1),
          ),
        );
    }
    revealActive();
  } else if (
    event.key.length === 1 &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey
  ) {
    event.preventDefault();
    if (!opened.value) open();
    const now = performance.now();
    search =
      (now - searchedAt < 700 ? search : "") + event.key.toLocaleLowerCase();
    searchedAt = now;
    const index = props.options.findIndex((option) =>
      option.label.toLocaleLowerCase().startsWith(search),
    );
    if (index >= 0) {
      active.value = index;
      revealActive();
    }
  }
}
function outside(event: Event) {
  const target = event.target;
  if (
    target instanceof Node &&
    !trigger.value?.contains(target) &&
    !menu.value?.contains(target)
  )
    close();
}
watch(
  () => [props.disabled, props.options],
  () => {
    if (opened.value) close();
  },
);
onMounted(() => {
  teleportTarget.value =
    trigger.value?.closest<HTMLElement>('[role="dialog"]') ?? "body";
  document.addEventListener("pointerdown", outside);
  document.addEventListener("focusin", outside);
  window.addEventListener("resize", position);
  window.addEventListener("scroll", position, true);
  window.visualViewport?.addEventListener("resize", position);
  window.visualViewport?.addEventListener("scroll", position);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", outside);
  document.removeEventListener("focusin", outside);
  window.removeEventListener("resize", position);
  window.removeEventListener("scroll", position, true);
  window.visualViewport?.removeEventListener("resize", position);
  window.visualViewport?.removeEventListener("scroll", position);
});
</script>

<template>
  <span class="refined-select">
    <button
      :id="id"
      ref="trigger"
      type="button"
      class="refined-select__trigger"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="label"
      :aria-expanded="opened"
      :aria-controls="opened ? listId : undefined"
      :aria-activedescendant="opened ? `${uid}-${active}` : undefined"
      :disabled="disabled || !options.length"
      :data-open="opened"
      @click="opened ? close() : open()"
      @keydown="onKey"
    >
      <span class="refined-select__value">{{
        selected?.label ?? "请选择"
      }}</span>
      <ChevronDown :size="15" :stroke-width="1.6" aria-hidden="true" />
    </button>
    <Teleport :to="teleportTarget">
      <Transition name="select-popover">
        <div
          v-if="opened"
          :id="listId"
          ref="menu"
          class="refined-select__menu"
          :class="`refined-select__menu--${placement}`"
          :style="menuStyle"
          role="listbox"
          :aria-label="label"
        >
          <div class="refined-select__caption" aria-hidden="true">
            {{ label }}
          </div>
          <div
            v-for="(option, index) in options"
            :id="`${uid}-${index}`"
            :key="option.value"
            :data-index="index"
            role="option"
            :aria-selected="option.value === modelValue"
            class="refined-select__option"
            :class="{ 'is-active': active === index }"
            @pointermove="active = index"
            @mousedown.prevent
            @click="choose(index)"
          >
            <span>{{ option.label }}</span>
            <Check
              v-if="option.value === modelValue"
              :size="16"
              :stroke-width="1.8"
              aria-hidden="true"
            />
          </div>
        </div>
      </Transition>
    </Teleport>
  </span>
</template>

<style scoped>
.refined-select {
  display: inline-flex;
  min-width: 0;
  width: 100%;
}
.refined-select .refined-select__trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  width: 100%;
  min-width: 0;
  min-height: 44px;
  padding: 11px 14px;
  border: 1px solid #dfe6dc;
  border-radius: 12px;
  background: #fff;
  color: #365340;
  font: inherit;
  font-size: 12px;
  line-height: 1.6;
  text-align: left;
  box-shadow: 0 2px 5px #264f3e03;
  transition:
    border-color 0.18s,
    background 0.18s,
    box-shadow 0.18s;
}
.refined-select__value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.refined-select__trigger svg {
  color: #889a83;
  transition: transform 0.2s;
}
.refined-select__trigger:not(:disabled):hover {
  border-color: #adbea7;
  background: #fafcf8;
}
.refined-select__trigger[data-open="true"] {
  border-color: #8ba184;
  box-shadow: 0 0 0 3px #446c500c;
}
.refined-select__trigger[data-open="true"] svg {
  transform: rotate(180deg);
}
.refined-select__trigger:focus-visible {
  outline: 3px solid #94b8a04d;
  outline-offset: 3px;
}
.refined-select__trigger:disabled {
  background: #f4f6f1;
  opacity: 0.55;
  cursor: default;
}
.refined-select__menu {
  position: fixed;
  z-index: 200;
  padding: 6px;
  overflow-y: auto;
  overscroll-behavior: contain;
  border: 1px solid #e2e8df;
  border-radius: 16px;
  background: #fffffff7;
  backdrop-filter: blur(24px);
  box-shadow:
    0 16px 48px #193d291c,
    0 3px 10px #193d2908;
  color: #365340;
  font-size: 12px;
  line-height: 1.6;
  scrollbar-width: thin;
  scrollbar-color: #cbd7c6 transparent;
  transform-origin: top;
}
.refined-select__menu--above {
  transform-origin: bottom;
}
.refined-select__caption {
  padding: 7px 11px 9px;
  color: #8b9885;
  font-size: 10px;
  letter-spacing: 0.06em;
}
.refined-select__option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  min-height: 44px;
  padding: 11px;
  margin: 2px 0;
  border-radius: 10px;
  cursor: pointer;
  user-select: none;
  transition: background 0.12s;
}
.refined-select__option span {
  overflow-wrap: anywhere;
}
.refined-select__option[aria-selected="true"] {
  color: #264f3e;
  font-weight: 500;
  background: #f0f5eb;
}
.refined-select__option.is-active {
  background: #eaf1e4;
}
.refined-select__option svg {
  flex-shrink: 0;
  color: #567c45;
}
.select-popover-enter-active,
.select-popover-leave-active {
  transition:
    opacity 0.14s,
    transform 0.14s;
}
.select-popover-enter-from,
.select-popover-leave-to {
  opacity: 0;
  transform: translateY(-3px) scale(0.98);
}
@media (prefers-reduced-motion: reduce) {
  .refined-select__trigger,
  .refined-select__trigger svg,
  .refined-select__option,
  .select-popover-enter-active,
  .select-popover-leave-active {
    transition: none;
  }
}
</style>
