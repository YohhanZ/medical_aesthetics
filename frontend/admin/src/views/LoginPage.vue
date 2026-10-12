<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { ArrowRight, Leaf, LockKeyhole, ShieldCheck } from "lucide-vue-next";
import { login, startDemo } from "../services/auth";
import { errorText } from "../services/api";
const router = useRouter();
const username = ref(""),
  password = ref(""),
  busy = ref(false),
  error = ref("");
const development = import.meta.env.DEV;
const customerUrl =
  import.meta.env.VITE_CUSTOMER_URL ||
  (development ? "http://127.0.0.1:5173/" : undefined);
async function submit() {
  if (busy.value) return;
  error.value = "";
  busy.value = true;
  try {
    await login(username.value.trim(), password.value);
    password.value = "";
    await router.replace("/");
  } catch (e) {
    error.value = errorText(e);
    password.value = "";
  } finally {
    busy.value = false;
  }
}
function demo() {
  startDemo();
  router.replace("/");
}
</script>
<template>
  <main class="login-page">
    <section class="login-story">
      <component
        :is="customerUrl ? 'a' : 'div'"
        class="brand"
        :href="customerUrl"
      >
        <Leaf :size="28" /><span>美丽田园<small>BEAUTY FARM</small></span>
      </component>
      <div class="login-copy">
        <span class="eyebrow">THE CARE BEHIND EVERY VISIT</span>
        <h1>让每一次到店，<br />都有用心的准备。</h1>
        <p>从第一次咨询，到门店接待。<br />把服务的每一步，连在一起。</p>
        <div class="story-pill"><ShieldCheck :size="18" /> 机构运营工作台</div>
      </div>
      <footer>客户咨询与机构运营 · 两个独立平台</footer>
    </section>
    <section class="login-form-section">
      <form class="login-form" @submit.prevent="submit">
        <span class="login-symbol"><LockKeyhole :size="24" /></span>
        <h2>欢迎回来</h2>
        <p>使用机构员工账号登录。</p>
        <label
          >员工账号<input
            v-model="username"
            autocomplete="username"
            required
            maxlength="100"
            placeholder="请输入员工账号"
            :disabled="busy" /></label
        ><label
          >密码<input
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            maxlength="256"
            placeholder="请输入密码"
            :disabled="busy"
        /></label>
        <p v-if="error" class="error-message" role="alert">{{ error }}</p>
        <button class="button primary full" :disabled="busy">
          {{ busy ? "正在登录…" : "登录工作台" }}<ArrowRight :size="17" />
        </button>
        <p class="login-note">
          仅可访问已授权门店。登录凭据不会保存在浏览器本地存储，刷新后需重新登录。
        </p>
        <div v-if="development" class="demo-login">
          <span>本地开发</span
          ><button
            type="button"
            class="text-button"
            :disabled="busy"
            @click="demo"
          >
            进入界面演练 <ArrowRight :size="15" />
          </button>
          <p>演练使用合成数据，不连接机构业务；刷新后恢复初始数据。</p>
        </div>
      </form>
    </section>
  </main>
</template>
