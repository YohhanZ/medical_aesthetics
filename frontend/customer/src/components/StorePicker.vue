<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from "vue";
import { MapPin } from "lucide-vue-next";
import type { Conversation } from "../services/conversation";
import { NearbyStores, distanceLabel } from "../services/nearby-stores";
import RefinedSelect from "../../../shared/components/RefinedSelect.vue";

const props = defineProps<{
  chat: Conversation;
  disabled?: boolean;
  autoSelect?: boolean;
}>();
const emit = defineEmits<{ switch: [code: string] }>();
const nearby = reactive(new NearbyStores());
const choice = ref("");
let selectionVersion = 0;
let autoTried = false;
let disposed = false;
const disabled = computed(
  () =>
    props.disabled ||
    props.chat.busy ||
    props.chat.refreshing ||
    !!props.chat.pending,
);
const options = computed(() => {
  const matches = nearby.matches;
  const matched = new Set(matches.map((row) => row.store.code));
  return [
    ...matches.map((row, index) => ({
      value: row.store.code,
      label: `${row.store.name} · ${distanceLabel(row.kilometers)}${index === 0 ? " · 最近" : ""}`,
    })),
    ...props.chat.stores
      .filter((store) => !matched.has(store.code))
      .map((store) => ({ value: store.code, label: store.name })),
  ];
});
const nearest = computed(() => nearby.matches[0]);
watch(
  () => props.chat.session?.visitor_id,
  () => {
    selectionVersion++;
    nearby.reset();
    choice.value = props.chat.session?.store_code ?? "";
  },
  { immediate: true },
);
function choose(value: string) {
  selectionVersion++;
  choice.value = value;
}
async function locate() {
  if (disabled.value || nearby.busy) return;
  const version = selectionVersion;
  const visitor = props.chat.session?.visitor_id;
  await nearby.locate(
    props.chat.stores,
    navigator.geolocation,
    window.isSecureContext,
  );
  if (
    disposed ||
    version !== selectionVersion ||
    visitor !== props.chat.session?.visitor_id ||
    disabled.value
  )
    return;
  if (nearest.value) {
    choice.value = nearest.value.store.code;
    if (
      props.autoSelect &&
      !nearby.lowAccuracy &&
      !props.chat.customer &&
      props.chat.freshSession &&
      choice.value !== props.chat.session?.store_code
    ) {
      emit("switch", choice.value);
    }
  }
}
watch(
  () => [
    props.chat.busy,
    props.chat.refreshing,
    props.chat.session?.visitor_id,
  ],
  async () => {
    if (
      autoTried ||
      disabled.value ||
      !props.chat.session ||
      !props.chat.stores.length
    )
      return;
    autoTried = true;
    const version = selectionVersion;
    // A prompt is only opened by the location button. Existing permission can be reused.
    try {
      const permission = await navigator.permissions?.query({
        name: "geolocation",
      });
      if (
        !disposed &&
        version === selectionVersion &&
        permission?.state === "granted"
      )
        await locate();
    } catch {
      /* Permission queries are unavailable in some browsers; manual locate remains available. */
    }
  },
  { immediate: true },
);
onUnmounted(() => {
  disposed = true;
  nearby.reset();
});
</script>

<template>
  <section
    class="store-picker"
    aria-label="选择咨询门店"
    :aria-busy="nearby.busy"
  >
    <div class="store-picker__controls">
      <RefinedSelect
        :model-value="choice"
        label="咨询门店"
        :options="options"
        :disabled="disabled || nearby.busy"
        @update:model-value="choose"
      />
      <button
        type="button"
        class="store-picker__locate"
        :disabled="disabled || nearby.busy"
        @click="locate"
      >
        <MapPin :size="14" />{{ nearby.busy ? "正在匹配…" : "定位附近门店" }}
      </button>
      <button
        v-if="choice && choice !== chat.session?.store_code"
        type="button"
        class="store-picker__confirm"
        :disabled="disabled || nearby.busy"
        @click="emit('switch', choice)"
      >
        确认切换门店
      </button>
    </div>
    <p v-if="nearby.error" role="status" class="store-picker__note">
      {{ nearby.error }}
    </p>
    <p v-else-if="nearest" role="status" class="store-picker__note">
      {{
        nearest.store.code === chat.session?.store_code
          ? "当前已选最近门店"
          : "距离最近"
      }}：{{ nearest.store.name }} ·
      {{ distanceLabel(nearest.kilometers) }}（直线距离）<span
        v-if="nearby.lowAccuracy"
        >。定位精度较低，推荐仅供参考</span
      ><span v-if="nearest.store.simulated">。模拟位置，不可用于导航</span>
    </p>
    <p v-else class="store-picker__note">
      允许定位后匹配附近门店，也可以手动选择。位置仅用于本页计算距离。
    </p>
    <p
      v-if="choice && choice !== chat.session?.store_code"
      class="store-picker__note"
    >
      切换后需在新门店登录，原门店的咨询和预约记录会保留。
    </p>
  </section>
</template>

<style scoped>
.store-picker {
  min-width: 0;
  width: 100%;
}
.store-picker__controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 9px;
}
.store-picker__controls :deep(.refined-select) {
  flex: 1;
  min-width: 160px;
}
.store-picker__controls button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px solid #dce5d8;
  border-radius: 20px;
  padding: 10px 13px;
  font-size: 11px;
  background: #fff;
  color: #45634c;
  min-height: 40px;
}
.store-picker__controls .store-picker__confirm {
  background: #294e3b;
  border-color: #294e3b;
  color: #fff;
}
.store-picker__note {
  font-size: 10px;
  line-height: 1.8;
  color: #84917c;
  margin: 9px 0 0;
  overflow-wrap: anywhere;
}
</style>
