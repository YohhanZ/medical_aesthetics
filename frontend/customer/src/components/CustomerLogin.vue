<script setup lang="ts">
import { ref } from "vue";
import { ArrowRight, Leaf, ShieldCheck } from "lucide-vue-next";
import { ApiClient, ApiError, errorText } from "../services/api";
import type { Conversation } from "../services/conversation";
import StorePicker from "./StorePicker.vue";

const props = defineProps<{ api: ApiClient; chat: Conversation }>();
const emit = defineEmits<{ connected: []; reconnect: [] }>();
const register = ref(false);
const username = ref("");
const password = ref("");
const enableMemory = ref(false);
const bindCurrent = ref(false);
const busy = ref(false);
const error = ref("");
async function switchStore(code: string) {
  if (busy.value) return;
  password.value = "";
  bindCurrent.value = enableMemory.value = false;
  error.value = "";
  await props.chat.switchStore(code);
}
async function authenticate() {
  if (
    busy.value ||
    props.chat.busy ||
    props.chat.refreshing ||
    !props.chat.session
  )
    return;
  busy.value = true;
  props.chat.refreshing = true;
  error.value = "";
  if (register.value && !enableMemory.value) {
    error.value = "注册前请勾选允许保存咨询偏好。";
    busy.value = false;
    props.chat.refreshing = false;
    return;
  }
  try {
    await props.api.customerAuth(
      username.value.trim(),
      password.value,
      register.value,
      bindCurrent.value,
      enableMemory.value,
    );
    password.value = "";
    props.chat.refreshing = false;
    await props.chat.reloadIdentity();
    if (props.chat.customer) emit("connected");
  } catch (e) {
    if (
      e instanceof ApiError &&
      [
        "request_timeout",
        "network_unavailable",
        "customer_already_logged_in",
        "unauthenticated",
      ].includes(e.code)
    ) {
      props.chat.refreshing = false;
      await props.chat.reloadIdentity();
      if (props.chat.customer) {
        emit("connected");
        return;
      }
    }
    error.value = errorText(e);
  } finally {
    password.value = "";
    busy.value = false;
    props.chat.refreshing = false;
  }
}
</script>

<template>
  <main class="customer-login">
    <div class="login-brand">
      <Leaf :size="27" :stroke-width="1.3" /><span
        >美丽田园<small>BEAUTY FARM</small></span
      >
    </div>
    <div class="login-layout">
      <section class="login-intro">
        <p class="login-eyebrow">YOUR BEAUTY, YOUR PACE</p>
        <h1>每一次对话，<br />都从了解你开始。</h1>
        <p>登录后，继续你的专属咨询。<br />从上次聊到的地方，从容开始。</p>
        <img
          src="/images/beauty-portrait-v2.jpg"
          alt="AI 场景示意：明亮咨询空间中的女性肖像"
        />
        <small class="image-note">AI 场景示意</small>
      </section>
      <section class="login-card" aria-labelledby="login-title">
        <p class="login-eyebrow">WELCOME TO BEAUTY FARM</p>
        <h2 id="login-title">{{ register ? "开启专属咨询" : "欢迎回来" }}</h2>
        <p class="login-caption">
          {{
            register
              ? "创建账号，让每次咨询自然衔接。"
              : "登录你的账号，继续了解与探索。"
          }}
        </p>
        <p v-if="error || chat.error" class="login-error" role="alert">
          {{ error || chat.error }}
        </p>
        <p
          v-if="chat.busy && !chat.session"
          role="status"
          class="login-caption"
        >
          正在连接咨询服务…
        </p>
        <StorePicker
          :chat="chat"
          :disabled="busy"
          :auto-select="!username && !password && !bindCurrent && !enableMemory"
          @switch="switchStore"
        />
        <form @submit.prevent="authenticate">
          <fieldset
            :disabled="busy || chat.busy || chat.refreshing || !chat.session"
          >
            <label
              >账号<input
                v-model="username"
                autocomplete="username"
                required
                minlength="3"
                maxlength="40"
                pattern="[a-zA-Z0-9_-]+"
                placeholder="字母、数字、下划线或连字符"
            /></label>
            <label
              >密码<input
                v-model="password"
                type="password"
                :autocomplete="register ? 'new-password' : 'current-password'"
                required
                minlength="10"
                maxlength="128"
                placeholder="至少 10 位"
            /></label>
            <label class="login-check"
              ><input
                v-model="bindCurrent"
                type="checkbox"
                :required="register"
              />同意首次进入门店时，将当前咨询记录关联至我的账号。</label
            >
            <label class="login-check"
              ><input
                v-model="enableMemory"
                type="checkbox"
                :required="register"
              />允许保存我明确表达的咨询偏好，便于下次继续沟通（{{
                register ? "注册必选" : "可选"
              }}）。</label
            >
            <button
              class="login-submit"
              type="submit"
              :disabled="register && (!bindCurrent || !enableMemory)"
            >
              {{
                busy ? "正在连接…" : register ? "创建账号并进入" : "登录并进入"
              }}<ArrowRight :size="17" />
            </button>
            <button
              class="login-switch"
              type="button"
              @click="
                register = !register;
                error = '';
                password = '';
              "
            >
              {{ register ? "已有账号？登录" : "第一次来？创建账号" }}
            </button>
          </fieldset>
        </form>
        <button
          v-if="!chat.session && !chat.busy"
          class="login-switch"
          @click="emit('reconnect')"
        >
          重新连接
        </button>
        <p class="login-privacy">
          <ShieldCheck
            :size="15"
          />咨询记录与账号关联，按门店分别保存。咨询偏好有效期为 90
          天，病史和诊断不进入偏好记录。已有账号登录会恢复原记录；当前其他匿名记录不自动合并。
        </p>
        <p class="login-store">
          {{ chat.session?.store_name ?? "美丽田园 · 客户咨询平台"
          }}<span v-if="chat.session?.simulated"> · 虚构门店演示</span>
        </p>
      </section>
    </div>
  </main>
</template>

<style scoped>
.customer-login {
  min-height: 100vh;
  background: #f5f7f4;
  color: #233e32;
  padding: 30px 6vw 48px;
  box-sizing: border-box;
}
.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 3px;
}
.login-card > :deep(.store-picker) {
  margin: 20px 0;
}
.login-brand small {
  display: block;
  font-size: 8px;
  letter-spacing: 2.7px;
  margin-top: 4px;
}
.login-layout {
  max-width: 1160px;
  margin: 58px auto 0;
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: 9%;
  align-items: center;
}
.login-eyebrow {
  font-size: 10px;
  letter-spacing: 2.1px;
  color: #7b8b7f;
  margin-bottom: 20px;
}
h1 {
  font-size: clamp(32px, 3.5vw, 52px);
  line-height: 1.35;
  letter-spacing: -1.5px;
  margin: 0 0 20px;
  font-weight: 600;
}
.login-intro > p:not(.login-eyebrow) {
  line-height: 1.9;
  color: #7a877d;
  font-size: 14px;
}
.login-intro img {
  width: 100%;
  max-height: 280px;
  object-fit: cover;
  object-position: center 35%;
  border-radius: 24px;
  margin-top: 18px;
}
.image-note {
  display: block;
  color: #8c978e;
  font-size: 10px;
  margin-top: 8px;
}
.login-card {
  background: #fff;
  border: 1px solid #e5eae3;
  border-radius: 28px;
  padding: 40px;
  box-shadow: 0 20px 60px #233e3205;
}
h2 {
  font-size: 30px;
  font-weight: 550;
  margin: 0 0 12px;
  letter-spacing: -0.7px;
}
.login-caption,
.login-store {
  color: #7f8b80;
  font-size: 13px;
  line-height: 1.7;
}
fieldset {
  padding: 0;
  border: 0;
  margin: 26px 0 0;
  min-width: 0;
}
label:not(.login-check) {
  display: block;
  font-size: 12px;
  margin: 18px 0;
}
input:not([type="checkbox"]) {
  width: 100%;
  box-sizing: border-box;
  background: #fafbf9;
  border: 1px solid #dde4da;
  border-radius: 12px;
  padding: 14px;
  margin-top: 8px;
  font-size: 14px;
  color: #233e32;
}
input:focus-visible {
  outline: 2px solid #8aa48a;
  outline-offset: 2px;
}
.login-check {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  color: #71806f;
  font-size: 11px;
  line-height: 1.8;
  margin: 14px 0;
}
input[type="checkbox"] {
  margin-top: 4px;
  flex-shrink: 0;
  accent-color: #315942;
}
button {
  cursor: pointer;
}
.login-submit {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  border: 0;
  border-radius: 24px;
  padding: 14px;
  background: #294d39;
  color: #fff;
  font-size: 13px;
  margin-top: 24px;
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
.login-switch {
  display: block;
  border: 0;
  background: none;
  color: #50674d;
  font-size: 12px;
  margin: 20px auto;
}
.login-privacy {
  display: flex;
  gap: 8px;
  font-size: 10px;
  line-height: 1.8;
  color: #8a9587;
  border-top: 1px solid #edf0eb;
  padding-top: 20px;
  margin-top: 16px;
}
.login-privacy svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.login-store {
  font-size: 10px;
  margin: 14px 0 0;
}
.login-error {
  color: #9f4937;
  font-size: 12px;
  line-height: 1.7;
}
@media (max-width: 720px) {
  .customer-login {
    padding: 24px 20px 40px;
  }
  .login-layout {
    grid-template-columns: 1fr;
    gap: 26px;
    margin-top: 34px;
    max-width: 440px;
  }
  .login-intro img,
  .image-note {
    display: none;
  }
  .login-intro h1 {
    font-size: 32px;
  }
  .login-intro .login-eyebrow {
    margin-bottom: 12px;
  }
  .login-card {
    padding: 26px;
    border-radius: 22px;
  }
}
</style>
