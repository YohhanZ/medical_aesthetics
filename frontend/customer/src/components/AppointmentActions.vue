<script setup lang="ts">
import { ref, watch } from "vue";
import {
  acceptChangeText,
  rejectChangeText,
  cancelText,
  type Appointment,
} from "../services/booking";
const props = defineProps<{ appointment: Appointment; disabled: boolean }>();
const emit = defineEmits<{
  cancel: [accepted: boolean];
  respond: [decision: "accept" | "reject", accepted: boolean];
}>();
const changeChecked = ref(false),
  cancelChecked = ref(false);
watch(
  () => `${props.appointment.id}/${props.appointment.version}`,
  () => {
    changeChecked.value = cancelChecked.value = false;
  },
);
const date = (value: string) => new Date(value).toLocaleString("zh-CN");
</script>
<template>
  <div v-if="appointment.change_proposal" class="booking-summary">
    <h4>门店建议一个新时间</h4>
    <p>{{ date(appointment.change_proposal.proposed_at) }}</p>
    <p>在您接受前，原安排保持不变；若尚待确认，仍未成为已确认预约。</p>
    <small
      >请在
      {{
        date(appointment.change_proposal.expires_at)
      }}
      前回应；过期后刷新核实。</small
    >
    <label class="booking-check"
      ><input
        v-model="changeChecked"
        type="checkbox"
        :disabled="disabled"
      />我已审阅新时间，确认下面选择的处理方式</label
    >
    <div class="booking-actions">
      <button
        :disabled="disabled || !changeChecked"
        @click="emit('respond', 'reject', changeChecked)"
      >
        {{ rejectChangeText }}
      </button>
      <button
        class="booking-primary"
        :disabled="disabled || !changeChecked"
        @click="emit('respond', 'accept', changeChecked)"
      >
        {{ acceptChangeText }}
      </button>
    </div>
  </div>
  <details
    v-if="
      ['pending_store_confirmation', 'confirmed'].includes(appointment.state)
    "
    class="answer-sources"
  >
    <summary>取消本次预约</summary>
    <p>
      取消后门店不再按本次预约接待，申请和处理记录仍保留。需要重新预约时请在对话中提出。
    </p>
    <label class="booking-check"
      ><input
        v-model="cancelChecked"
        type="checkbox"
        :disabled="disabled"
      />我确认取消这份预约，包括尚未回应的改约提案</label
    >
    <button
      :disabled="disabled || !cancelChecked"
      @click="emit('cancel', cancelChecked)"
    >
      {{ cancelText }}
    </button>
  </details>
  <p v-if="appointment.arrived_at">
    到店已登记：{{ date(appointment.arrived_at) }}。后续项目由门店继续沟通。
  </p>
</template>
