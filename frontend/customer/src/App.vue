<script setup lang="ts">
import {
  computed,
  markRaw,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  watch,
} from "vue";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  Leaf,
  Menu,
  MessageCircle,
  Search,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-vue-next";
import { filterProjects, type Category } from "./domain";
import { ApiClient, errorText } from "./services/api";
import { Conversation } from "./services/conversation";
import type { Project } from "./types";
import ConsultationPanel from "./components/ConsultationPanel.vue";
import ProjectCard from "./components/ProjectCard.vue";
let storage: Storage | undefined;
try {
  storage = sessionStorage;
} catch {
  /* References are optional. */
}
const api = markRaw(new ApiClient());
const chat = reactive(new Conversation(api, storage)) as Conversation;
const category = ref<Category>("all"),
  search = ref(""),
  mobileMenu = ref(false);
const visibleCount = ref(8);
watch([category, search], () => {
  visibleCount.value = 8;
});
const filtered = computed(() =>
  filterProjects(chat.projects, category.value, search.value),
);
const selected = ref<Project | null>(null),
  privacyOpen = ref(false),
  detailError = ref(""),
  detailBusy = ref(false);
const storeChoice = ref("");
const modalOpen = computed(() =>
  Boolean(
    selected.value ||
      privacyOpen.value ||
      detailBusy.value ||
      detailError.value,
  ),
);
let previousFocus: HTMLElement | null = null;
let detailEpoch = 0;
watch(modalOpen, async (value) => {
  document.body.style.overflow = value ? "hidden" : "";
  if (value) {
    previousFocus = document.activeElement as HTMLElement;
    await nextTick();
    document.querySelector<HTMLElement>(".modal .close-button")?.focus();
  } else previousFocus?.focus();
});
watch(
  () => chat.session?.store_code,
  (value) => {
    storeChoice.value = value ?? "";
  },
);
function closeModal() {
  detailEpoch++;
  selected.value = null;
  privacyOpen.value = false;
  detailBusy.value = false;
  detailError.value = "";
  if (location.hash.startsWith("#project/"))
    history.replaceState(
      null,
      "",
      `${location.pathname}${location.search}#explore`,
    );
}
async function openHashProject() {
  const match = location.hash.match(/^#project\/([a-f0-9-]{36})$/i);
  if (!match) {
    if (selected.value || detailBusy.value) closeModal();
    return;
  }
  if (!chat.ready) return;
  const epoch = ++detailEpoch;
  selected.value = null;
  privacyOpen.value = false;
  detailError.value = "";
  detailBusy.value = true;
  try {
    const project = await api.project(match[1]!);
    if (epoch === detailEpoch) selected.value = project;
  } catch (error) {
    if (epoch === detailEpoch) detailError.value = errorText(error);
    await chat.refresh();
  } finally {
    if (epoch === detailEpoch) detailBusy.value = false;
  }
}
function onKeydown(event: KeyboardEvent) {
  if (!modalOpen.value) return;
  if (event.key === "Escape") closeModal();
  if (event.key === "Tab") {
    const nodes = [
      ...document.querySelectorAll<HTMLElement>(
        ".modal button:not(:disabled), .modal a[href]",
      ),
    ].filter((n) => n.offsetParent !== null);
    const first = nodes[0],
      last = nodes.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
}
function scrollTo(id: string) {
  mobileMenu.value = false;
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
}
async function ask(text: string) {
  if (!chat.ready || chat.busy || chat.pending) {
    scrollTo("consultation");
    return;
  }
  closeModal();
  scrollTo("consultation");
  await chat.send(text);
}
function requestAppointment(project?: Project) {
  ask(project ? `我想预约到店咨询，了解${project.title}` : "我想预约到店咨询");
}
async function initialize() {
  await chat.initialize(
    new URLSearchParams(location.search).get("store") ?? undefined,
  );
  await openHashProject();
}
async function switchStore() {
  closeModal();
  await chat.switchStore(storeChoice.value);
}
async function onFocus() {
  const detailWasOpen = Boolean(selected.value);
  if (detailWasOpen) {
    selected.value = null;
    detailBusy.value = true;
  }
  await chat.refresh();
  if (detailWasOpen && chat.ready) await openHashProject();
  else if (detailWasOpen) {
    detailBusy.value = false;
    detailError.value = "请重新连接咨询后核验项目资料。";
  }
}
onMounted(() => {
  initialize();
  window.addEventListener("hashchange", openHashProject);
  window.addEventListener("focus", onFocus);
  document.addEventListener("keydown", onKeydown);
});
onUnmounted(() => {
  detailEpoch++;
  window.removeEventListener("hashchange", openHashProject);
  window.removeEventListener("focus", onFocus);
  document.removeEventListener("keydown", onKeydown);
  document.body.style.overflow = "";
});
</script>

<template>
  <div class="site-shell" :inert="modalOpen || undefined">
    <header class="site-header">
      <div class="header-inner">
        <a class="wordmark" href="#" aria-label="美丽田园首页"
          ><span class="brand-icon"
            ><Leaf :size="23" :stroke-width="1.5" /></span
          ><span>美丽田园<small>BEAUTY FARM</small></span></a
        >
        <nav class="desktop-nav" aria-label="主导航">
          <a href="#consultation">专属咨询</a><a href="#explore">探索项目</a
          ><button @click="requestAppointment()">到店体验</button>
        </nav>
        <button class="header-booking" @click="requestAppointment()">
          预约咨询 <ArrowUpRight :size="14" />
        </button>
        <button
          class="menu-button icon-button"
          aria-label="切换导航菜单"
          :aria-expanded="mobileMenu"
          @click="mobileMenu = !mobileMenu"
        >
          <Menu :size="22" />
        </button>
      </div>
      <nav v-if="mobileMenu" class="mobile-nav" aria-label="移动端导航">
        <button @click="scrollTo('consultation')">专属咨询</button
        ><button @click="scrollTo('explore')">探索项目</button
        ><button
          @click="
            requestAppointment();
            mobileMenu = false;
          "
        >
          到店体验
        </button>
      </nav>
    </header>

    <div class="preview-strip">
      <span class="status-dot"></span> 客户咨询平台
      <span class="strip-divider">·</span> 真实咨询已接入 ·
      {{ chat.session?.simulated ? "虚构门店演示" : "项目供给需门店核实" }} ·
      预约申请 · 门店确认后到店
    </div>

    <main>
      <section class="hero" aria-labelledby="hero-title">
        <div class="hero-copy">
          <p class="eyebrow"><span></span> BEAUTY, AT YOUR OWN PACE</p>
          <h1 id="hero-title">美，<br />从了解开始。</h1>
          <p class="hero-description">
            每一个关于美的疑问，都值得被认真倾听。<br />从日常护理到医疗美容，陪你从容了解每一种选择。
          </p>
          <div class="hero-actions">
            <button class="primary-button" @click="scrollTo('consultation')">
              聊聊我的需求 <ArrowRight :size="17" /></button
            ><a class="text-link" href="#explore"
              >探索服务 <ChevronRight :size="17"
            /></a>
          </div>
          <div class="hero-note">
            <ShieldCheck :size="16" /> 先了解，再选择。按你的节奏来。
          </div>
        </div>
        <div class="hero-art photographic-hero">
          <div class="hero-photo-frame">
            <img
              class="hero-photo"
              src="/images/beauty-portrait-v2.jpg"
              alt="AI 场景示意：自然肤质的女性在明亮的咨询空间中微笑"
              fetchpriority="high"
              width="1122"
              height="1402"
            /><span class="photo-provenance">AI 场景示意</span>
          </div>
          <div class="floating-label">
            <span class="float-symbol"><Sparkles :size="17" /></span
            ><span
              >每一份美，都有自己的节奏。<small
                >美容护理 · 医疗美容 · 到店咨询</small
              ></span
            >
          </div>
        </div>
        <a class="hero-scroll" href="#consultation" aria-label="向下查看咨询"
          ><ChevronDown :size="19"
        /></a>
      </section>

      <section id="consultation" class="consultation-section section-wrap">
        <div class="section-heading">
          <div>
            <p class="eyebrow">YOUR BEAUTY CONCIERGE</p>
            <h2>有疑问，就从这里聊起。</h2>
          </div>
          <p class="section-description">
            不需要知道项目名称。<br />说说你在意的，我们一起了解。
          </p>
        </div>
        <div class="consultation-scope" v-if="chat.session">
          <span
            ><span class="status-dot"></span> {{ chat.session.store_name
            }}{{ chat.session.simulated ? " · 模拟门店" : "" }}</span
          >
          <div v-if="chat.stores.length > 1">
            <label class="sr-only" for="store-choice">咨询门店</label
            ><select
              id="store-choice"
              v-model="storeChoice"
              :disabled="chat.busy || chat.refreshing"
            >
              <option
                v-for="store in chat.stores"
                :key="store.code"
                :value="store.code"
              >
                {{ store.name }}
              </option></select
            ><button
              :disabled="
                chat.busy ||
                chat.refreshing ||
                storeChoice === chat.session.store_code
              "
              @click="switchStore()"
            >
              切换门店并新建对话
            </button>
          </div>
          <small v-if="storeChoice !== chat.session.store_code"
            >切换后原匿名凭据结束，旧门店对话无法继续访问。</small
          >
        </div>
        <ConsultationPanel
          :chat="chat"
          :booking-api="api"
          @reconnect="initialize()"
        />
      </section>

      <section id="explore" class="explore-section section-wrap">
        <div class="section-heading">
          <div>
            <p class="eyebrow">EXPLORE YOUR POSSIBILITIES</p>
            <h2>发现你的关注方向。</h2>
          </div>
          <p class="section-description">
            日常的呵护，或进一步的了解。<br />选择可以慢慢来。
          </p>
        </div>
        <div class="catalog-controls">
          <div class="segmented-control" role="group" aria-label="服务分类">
            <button
              v-for="option in [
                { id: 'all', label: '全部方向' },
                { id: 'care', label: '美容护理' },
                { id: 'medical', label: '医疗美容' },
              ]"
              :key="option.id"
              :aria-pressed="category === option.id"
              :class="{ active: category === option.id }"
              @click="category = option.id as Category"
            >
              {{ option.label }}
            </button>
          </div>
          <label class="catalog-search"
            ><Search :size="16" /><input
              v-model="search"
              placeholder="搜索关注方向"
              aria-label="搜索关注方向"
          /></label>
        </div>
        <div
          v-if="chat.ready && !chat.refreshing"
          class="project-grid photographic-projects"
        >
          <ProjectCard
            v-for="project in filtered.slice(0, visibleCount)"
            :key="project.id"
            :project="project"
          />
        </div>
        <div v-if="!filtered.length" class="empty-state">
          <Search :size="28" />
          <h3>
            {{
              chat.busy || chat.refreshing
                ? "正在核验公开目录"
                : chat.ready
                  ? "暂时没有匹配的公开资料"
                  : "连接后查看当前门店目录"
            }}
          </h3>
          <p>这里仅显示当前门店已审核、已发布且有效的了解入口。</p>
          <button
            class="text-link"
            v-if="chat.ready"
            @click="
              search = '';
              category = 'all';
            "
          >
            查看全部方向 <ArrowRight :size="16" />
          </button>
        </div>
        <div
          class="load-more-projects"
          v-if="filtered.length > visibleCount && chat.ready"
        >
          <button class="text-link" @click="visibleCount += 8">
            查看更多方向 <ArrowRight :size="16" />
          </button>
        </div>
        <p class="catalog-note">
          图片为 AI
          生成场景示意，非真实顾客、医生或治疗效果。项目内容来自当前有效公开目录。模拟供给不是实际机构承诺，具体服务与费用需门店核实。
        </p>
      </section>

      <section class="journey-section section-wrap">
        <div class="journey-intro">
          <p class="eyebrow">A THOUGHTFUL NEXT STEP</p>
          <h2>下一步，<br />也可以很简单。</h2>
          <p>不急着确定项目。<br />先让门店了解你的想法。</p>
          <button class="text-link" @click="requestAppointment()">
            聊聊到店意愿 <ArrowRight :size="17" />
          </button>
        </div>
        <div class="journey-steps">
          <div
            v-for="(step, index) in [
              {
                title: '说说你的想法',
                text: '先聊咨询意向，项目可以暂不确定。',
              },
              {
                title: '由门店确认',
                text: '提交后等待门店沟通；本地演练不代表真实到店安排。',
              },
              {
                title: '到店，继续了解',
                text: '与专业人员进一步沟通，再决定具体服务。',
              },
            ]"
            :key="step.title"
            class="journey-step"
          >
            <span class="step-number">0{{ index + 1 }}</span>
            <div>
              <h3>{{ step.title }}</h3>
              <p>{{ step.text }}</p>
            </div>
          </div>
        </div>
      </section>
      <section class="closing">
        <Leaf :size="29" :stroke-width="1.2" />
        <h2>关于美，先听听自己。</h2>
        <p>一份关注，一次对话，一个从容的开始。</p>
        <button class="primary-button" @click="scrollTo('consultation')">
          开始了解 <ArrowRight :size="17" />
        </button>
      </section>
    </main>

    <footer class="site-footer">
      <div class="footer-top">
        <a class="wordmark" href="#"
          ><span class="brand-icon"
            ><Leaf :size="23" :stroke-width="1.5" /></span
          ><span>美丽田园<small>BEAUTY FARM</small></span></a
        ><span>美与健康，始于关怀。</span>
      </div>
      <div class="footer-bottom">
        <span>© 2026 客户咨询平台</span>
        <div>
          <button @click="privacyOpen = true">隐私与数据说明</button
          ><a
            href="https://www.beautyfarm.com.cn/"
            target="_blank"
            rel="noopener noreferrer"
            >品牌官网 <ArrowUpRight :size="12"
          /></a>
        </div>
      </div>
    </footer>

    <Teleport to="body"
      ><div v-if="modalOpen" class="modal-overlay" @click.self="closeModal()">
        <section
          class="modal"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="
            selected
              ? 'detail-title'
              : privacyOpen
                ? 'privacy-title'
                : 'detail-status-title'
          "
        >
          <button
            class="close-button icon-button"
            @click="closeModal()"
            aria-label="关闭窗口"
          >
            <X :size="21" />
          </button>
          <template v-if="selected"
            ><div
              class="detail-art photographic-detail"
              :class="selected.category === 'medical' ? 'mist' : 'sage'"
            >
              <img :src="selected.image_url" :alt="selected.image_alt" /><span
                class="photo-provenance"
                >AI 场景示意</span
              >
            </div>
            <div class="modal-content">
              <p class="eyebrow">
                {{
                  selected.simulated
                    ? "演示服务 · 虚构供给与价格"
                    : "当前有效公开资料"
                }}
              </p>
              <h2 id="detail-title">{{ selected.title }}</h2>
              <div class="detail-tags">
                <span>{{
                  selected.category === "medical"
                    ? "医美了解入口"
                    : "美容护理了解入口"
                }}</span
                ><span>版本 {{ selected.version }}</span>
              </div>
              <p class="detail-description">{{ selected.description }}</p>
              <div class="detail-source">
                <strong>资料来源</strong>
                <p>{{ selected.source }}</p>
                <span
                  >有效期至
                  {{
                    new Date(selected.valid_until).toLocaleDateString("zh-CN")
                  }}</span
                >
              </div>
              <div class="detail-notice">
                <ShieldCheck :size="18" />
                <p>
                  {{
                    selected.image_provenance
                  }}。项目名称和目录图片不代表个人适合性、效果或实际供给。
                </p>
              </div>
              <button
                class="primary-button full-width"
                :disabled="chat.busy || !!chat.pending || chat.refreshing"
                @click="requestAppointment(selected)"
              >
                带着这个方向，到店聊聊 <ArrowRight :size="17" /></button
              ><button
                class="detail-chat text-link"
                :disabled="chat.busy || !!chat.pending || chat.refreshing"
                @click="ask(`想了解${selected!.title}`)"
              >
                先向咨询助手提问 <MessageCircle :size="16" />
              </button></div
          ></template>
          <template v-else-if="privacyOpen"
            ><div class="modal-content privacy-content">
              <p class="eyebrow">PRIVACY & CARE</p>
              <h2 id="privacy-title">把你的信息，认真对待。</h2>
              <p>
                匿名凭据由服务端签发，限定当前门店及自己的对话。咨询消息在服务端持久保存，刷新可恢复；浏览器仅保存当前访客与对话的引用，不保存消息正文或模型密钥。
              </p>
              <p>
                普通咨询由真实模型依据已发布公开资料回答。发送前去除联系方式，个人医疗、身份和业务记录转人工；外部模型仅接收允许外发的问题、必要公开追问及证据。
              </p>
              <p>
                请勿在普通对话中填写病历、身份证、住址或合同。预约卡片中的称呼、手机号与意向保存在加密业务记录中，不发送给模型；需要先核验手机号、审阅草稿并明确确认，提交后仍待门店确认。模拟核验不发送真实短信，模拟资料不代表真实供给。数据保留与删除自助流程仍待接入。
              </p>
              <button class="primary-button" @click="closeModal()">
                我知道了 <Check :size="16" />
              </button></div
          ></template>
          <template v-else
            ><div class="modal-content privacy-content">
              <h2 id="detail-status-title">
                {{ detailBusy ? "正在核验项目资料" : "暂时无法查看" }}
              </h2>
              <p>
                {{ detailBusy ? "读取当前门店有效的公开版本…" : detailError }}
              </p>
              <button class="primary-button" @click="closeModal()">
                返回目录
              </button>
            </div></template
          >
        </section>
      </div></Teleport
    >
  </div>
</template>
