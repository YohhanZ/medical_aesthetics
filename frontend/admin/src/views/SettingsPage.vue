<script setup lang="ts">
import { ShieldCheck } from "lucide-vue-next";
import { isDemo, session } from "../state";
const permissionNames = {
  knowledge_author: "知识编辑",
  knowledge_review: "独立审核",
  knowledge_publish: "发布与撤回",
  appointment_read: "预约读取",
  appointment_manage: "预约确认与婉拒",
  appointment_contact: "查看预约联系号码",
  customer_read: "到店咨询档案读取",
  customer_manage: "到店咨询档案追加",
};
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">ACCOUNT & ACCESS</p>
      <h1>明确的权限，安心的协作。</h1>
      <p>每个账号只访问明确授权的门店。</p>
    </div>
  </div>
  <section class="card account-card">
    <span class="empty-icon"><ShieldCheck :size="24" /></span>
    <div>
      <h2>{{ session?.profile.username }}</h2>
      <p>
        {{
          isDemo
            ? "本地界面演练账号 · 不连接机构业务"
            : "已通过员工凭据登录 · 仅内存保存登录状态"
        }}
      </p>
    </div>
    <span
      class="status"
      :class="session?.profile.simulated ? 'amber' : 'green'"
      >{{ session?.profile.simulated ? "模拟账号" : "员工账号" }}</span
    >
  </section>
  <section class="card">
    <header class="card-heading">
      <div>
        <h2>已授权门店</h2>
        <p>
          以下权限来自{{
            isDemo ? "明确标识的演练配置" : "服务端授权记录"
          }}，前端不能自行授予。
        </p>
      </div>
    </header>
    <div v-if="session?.profile.stores.length" class="store-list">
      <article v-for="store in session.profile.stores" :key="store.id">
        <div>
          <h3>{{ store.name }}</h3>
          <p>
            {{ store.simulated ? "模拟门店 · 非真实机构供给" : "机构门店" }}
          </p>
        </div>
        <div class="permission-tags">
          <span
            v-for="permission in store.permissions"
            :key="permission"
            class="soft-label"
            >{{ permissionNames[permission] }}</span
          >
        </div>
      </article>
    </div>
    <p v-else class="loading-state">
      暂无授权门店。平台管理员身份不会自动获得门店或客户数据权限。
    </p>
  </section>
  <section class="card settings-notes">
    <h2>协作规则</h2>
    <p>
      知识作者不能审核自己的版本。医学资料需要实际资质核验与独立医学审核。客户预约申请必须取得明确确认，再由门店核实到店时间。
    </p>
    <p>
      预约、客户、项目的业务管理接口仍待开发；真实登录时这些页面保持空状态，不将演练数据混入机构数据。
    </p>
  </section>
</template>
