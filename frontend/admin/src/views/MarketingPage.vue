<script setup lang="ts">
import {
  computed,
  markRaw,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  Clapperboard,
  ImagePlus,
  Layers,
  RefreshCw,
  Sparkles,
  WandSparkles,
} from "lucide-vue-next";
import { can, currentStore, isDemo, storeId } from "../state";
import { errorText } from "../services/api";
import {
  marketingApi,
  marketingAsset,
  MarketingSubmission,
  mediaErrors,
  stateNames,
  type MarketingJob,
  type MarketingOptions,
  type MediaKind,
  type Aspect,
} from "../services/marketing";
import { renderPoster, saveBlob } from "../services/poster";

const scope = storeId.value;
const api = markRaw(marketingApi(scope));
const submission = reactive(new MarketingSubmission(api.create));
const allowed = computed(() => !isDemo.value && can("knowledge_author"));
const options = ref<MarketingOptions>({
  image_ready: false,
  video_ready: false,
  image_model: "Kwai-Kolors/Kolors",
  video_model: "wan2.2-t2v-plus",
  daily_limit: 10,
  projects: [],
});
const kind = ref<MediaKind>("image");
const form = reactive({
  brand: "美丽田园",
  title: "把日常，留给一份从容。",
  caption:
    "从日常护理开始，找到适合自己的节奏。\n欢迎了解护理项目与到店咨询流程。",
  prompt:
    "明亮自然光的美容护理空间，一位成年女性与顾问从容交流，奶油白与鼠尾草绿配色，自然真实肤质，生活方式摄影，画面留白用于宣传海报排版。",
  aspect: "portrait" as Aspect,
  project: "",
  videoCost: false,
});
const jobs = ref<MarketingJob[]>([]),
  selected = ref<MarketingJob | null>(null);
const busy = ref(false),
  error = ref(""),
  info = ref(""),
  hasMore = ref(false),
  assetBusy = ref(false);
const assetUrl = ref(""),
  posterUrl = ref(""),
  posterBlob = ref<Blob | null>(null),
  assetBlob = ref<Blob | null>(null);
const example = `${import.meta.env.BASE_URL}images/marketing-sample.jpg`;
const sample = computed(
  () =>
    !assetUrl.value ||
    selected.value?.kind !== "image" ||
    selected.value?.state !== "succeeded",
);
const ready = computed(
  () =>
    allowed.value &&
    (kind.value === "image"
      ? options.value.image_ready
      : options.value.video_ready),
);
const totalDone = computed(
  () => jobs.value.filter((j) => j.state === "succeeded").length,
);
const active = computed(() =>
  jobs.value.some((j) => ["queued", "running", "submitting"].includes(j.state)),
);
let disposed = false,
  assetEpoch = 0,
  renderEpoch = 0;
let poll: ReturnType<typeof setTimeout> | undefined;
let redraw: ReturnType<typeof setTimeout> | undefined;

function resetAsset() {
  assetEpoch++;
  assetBusy.value = false;
  if (assetUrl.value) URL.revokeObjectURL(assetUrl.value);
  assetUrl.value = "";
  assetBlob.value = null;
}
async function preview() {
  const epoch = ++renderEpoch;
  try {
    const blob = await renderPoster(
      {
        ...form,
        sample: sample.value,
        simulated:
          selected.value?.simulated ?? currentStore.value?.simulated ?? true,
      },
      sample.value ? example : assetUrl.value,
    );
    if (disposed || epoch !== renderEpoch) return;
    if (posterUrl.value) URL.revokeObjectURL(posterUrl.value);
    posterBlob.value = blob;
    posterUrl.value = URL.createObjectURL(blob);
  } catch {
    if (!disposed && epoch === renderEpoch)
      error.value = "海报预览暂未加载，请检查示例图片或重试。";
  }
}
watch(
  () => [
    form.brand,
    form.title,
    form.caption,
    form.aspect,
    assetUrl.value,
    sample.value,
  ],
  () => {
    posterBlob.value = null;
    clearTimeout(redraw);
    redraw = setTimeout(() => void preview(), 120);
  },
  { immediate: true },
);
function useProject() {
  const project = options.value.projects.find((p) => p.id === form.project);
  if (!project) return;
  form.title = `给自己一次${project.title}的时间`;
  form.caption = project.description.slice(0, 230);
  form.prompt = `${project.title}宣传场景，成年顾客与顾问交流，自然光美容护理空间，真实自然肤质，奶油白与鼠尾草绿色调，画面留白，不包含治疗效果对比。`;
}
function template(name: "brand" | "care" | "visit") {
  if (submission.pending) return;
  if (name === "brand") {
    form.title = "把日常，留给一份从容。";
    form.caption =
      "从日常护理开始，找到适合自己的节奏。\n欢迎了解护理项目与到店咨询流程。";
  }
  if (name === "care") {
    form.title = "今天，给自己一点照顾。";
    form.caption =
      "关于清洁、保湿与日常呵护，先听听自己的需求。\n项目内容与具体安排，请向门店了解。";
  }
  if (name === "visit") {
    form.title = "下一次见面，从了解开始。";
    form.caption =
      "不必急着决定项目。\n先聊聊关注的方向，再由门店确认咨询安排。";
  }
}
async function load(more = false) {
  if (!allowed.value || busy.value) return;
  busy.value = true;
  try {
    const result = await api.list(more ? jobs.value.length : 0);
    if (disposed) return;
    hasMore.value = result.items.length === 20;
    jobs.value = (
      more
        ? [...jobs.value, ...result.items]
        : [
            ...result.items,
            ...jobs.value.filter(
              (j) => !result.items.some((n) => n.id === j.id),
            ),
          ]
    ).filter((j, i, all) => all.findIndex((n) => n.id === j.id) === i);
    if (selected.value) {
      const updated = jobs.value.find((j) => j.id === selected.value?.id);
      if (updated) {
        const previous = selected.value.state;
        selected.value = updated;
        if (updated.state === "succeeded" && previous !== "succeeded")
          void openAsset(updated);
      }
    }
  } catch (e) {
    if (!disposed) error.value = errorText(e);
  } finally {
    busy.value = false;
    schedule();
  }
}
function schedule() {
  clearTimeout(poll);
  if (!disposed && active.value) poll = setTimeout(() => void load(), 5000);
}
async function openAsset(job: MarketingJob) {
  resetAsset();
  const epoch = assetEpoch;
  assetBusy.value = true;
  try {
    const blob = await marketingAsset(scope, job.id);
    if (disposed || epoch !== assetEpoch) return;
    assetBlob.value = blob;
    assetUrl.value = URL.createObjectURL(blob);
  } catch (e) {
    if (!disposed && epoch === assetEpoch) error.value = errorText(e);
  } finally {
    if (epoch === assetEpoch) assetBusy.value = false;
  }
}
async function choose(job: MarketingJob) {
  if (submission.pending) return;
  selected.value = job;
  form.brand = job.brand;
  kind.value = job.kind;
  form.title = job.title;
  form.caption = job.caption;
  form.prompt = job.prompt;
  form.aspect = job.aspect;
  resetAsset();
  if (job.state === "succeeded") await openAsset(job);
}
async function generate() {
  if (!ready.value || submission.busy) return;
  error.value = "";
  info.value = "";
  try {
    const job = await submission.send({
      brand: form.brand,
      kind: kind.value,
      title: form.title,
      prompt: form.prompt,
      caption: form.caption,
      aspect: form.aspect,
      project_id: form.project || null,
      video_cost_acknowledged: form.videoCost,
    });
    if (disposed || !job) return;
    jobs.value = [job, ...jobs.value.filter((j) => j.id !== job.id)];
    await choose(job);
    info.value = "任务已保存，生成进度会自动更新。";
    schedule();
  } catch (e) {
    if (!disposed) error.value = errorText(e);
  }
}
async function action(job: MarketingJob, operation: "cancel" | "reconcile") {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const updated = await api[operation](job.id);
    if (disposed) return;
    jobs.value = jobs.value.map((j) => (j.id === job.id ? updated : j));
    if (selected.value?.id === job.id) selected.value = updated;
    schedule();
  } catch (e) {
    if (!disposed) error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
function downloadPoster() {
  if (posterBlob.value)
    saveBlob(
      posterBlob.value,
      `${sample.value ? "示例排版" : "宣传海报"}-${Date.now()}.png`,
    );
}
function downloadVideo() {
  if (assetBlob.value && selected.value?.kind === "video")
    saveBlob(assetBlob.value, `宣传短片-${selected.value.id}.mp4`);
}
function downloadCopy() {
  saveBlob(
    new Blob(
      [
        `${form.title}\n\n${form.caption}\n\n画面描述：${form.prompt}\n\n${kind.value === "video" ? "5秒无声画面；文案可作为后期字幕参考。\n" : ""}AI创作草稿，发布前请核对品牌、项目及素材。`,
      ],
      { type: "text/plain;charset=utf-8" },
    ),
    "宣传文案.txt",
  );
}
onMounted(async () => {
  if (!allowed.value) return;
  try {
    const value = await api.options();
    if (!disposed) options.value = value;
  } catch (e) {
    if (!disposed) error.value = errorText(e);
  }
  if (!disposed) await load();
});
onBeforeUnmount(() => {
  disposed = true;
  renderEpoch++;
  clearTimeout(poll);
  clearTimeout(redraw);
  resetAsset();
  if (posterUrl.value) URL.revokeObjectURL(posterUrl.value);
});
</script>

<template>
  <div class="page-heading marketing-heading">
    <div>
      <p class="eyebrow">MAKE YOUR CARE VISIBLE</p>
      <h1>让好服务，被更多人看见。</h1>
      <p>从一个想法，到一份图文、一段短片。为每次沟通准备恰到好处的表达。</p>
    </div>
    <div class="marketing-mark">
      <Sparkles :size="24" :stroke-width="1.3" />
    </div>
  </div>
  <div class="marketing-intro">
    <span><span class="mkt-dot"></span> AI 营销创作中心</span
    ><span>创作 → 预览 → 下载使用</span>
  </div>
  <p v-if="!allowed && !isDemo" class="notice">
    当前账号没有门店知识创作权限，可以预览示例版式；生成与作品库需要知识创作权限。
  </p>
  <p v-if="error" class="error-message" role="alert">{{ error }}</p>
  <p v-if="info" class="marketing-info" role="status">
    <Check :size="14" />{{ info }}
  </p>
  <div class="marketing-layout">
    <section class="card marketing-editor" aria-label="营销创作设置">
      <div class="mkt-section-heading">
        <span>01 / 创作设定</span><small>按你的想法，慢慢调整。</small>
      </div>
      <div class="mkt-mode" role="group" aria-label="创作类型">
        <button
          type="button"
          :class="{ active: kind === 'image' }"
          :aria-pressed="kind === 'image'"
          :disabled="!!submission.pending"
          @click="kind = 'image'"
        >
          <ImagePlus :size="18" /><strong>图文海报</strong
          ><small>Kolors · 场景生图</small>
        </button>
        <button
          type="button"
          :class="{ active: kind === 'video' }"
          :aria-pressed="kind === 'video'"
          :disabled="!!submission.pending"
          @click="kind = 'video'"
        >
          <Clapperboard :size="18" /><strong>宣传短片</strong
          ><small>万相 · 5 秒无声画面</small>
        </button>
      </div>
      <form @submit.prevent="generate">
        <fieldset :disabled="!!submission.pending || submission.busy">
          <label v-if="options.projects.length"
            >关联项目<select v-model="form.project" @change="useProject">
              <option value="">品牌介绍／自由创作</option>
              <option v-for="p in options.projects" :value="p.id" :key="p.id">
                {{ p.title }}{{ p.simulated ? " · 演示" : "" }}
              </option>
            </select></label
          >
          <div class="mkt-presets">
            <span>灵感起点</span
            ><button type="button" @click="template('brand')">品牌介绍</button
            ><button type="button" @click="template('care')">日常护理</button
            ><button type="button" @click="template('visit')">到店邀请</button>
          </div>
          <label
            >品牌名称<input v-model="form.brand" maxlength="24" required
          /></label>
          <label
            >宣传标题<input v-model="form.title" maxlength="80" required
          /></label>
          <label
            >配套文案 <span class="mkt-field-note">模板草稿，可自由编辑</span
            ><textarea
              v-model="form.caption"
              rows="3"
              maxlength="1200"
              placeholder="写下希望传递的信息…"
            ></textarea>
          </label>
          <label
            >画面描述<textarea
              v-model="form.prompt"
              rows="4"
              minlength="5"
              maxlength="1200"
              required
              placeholder="描述人物、空间、光线与氛围…"
            ></textarea
            ><small
              >只描述宣传画面，请勿输入客户资料。画面将发送给所选生成服务。</small
            ></label
          >
          <div class="mkt-size">
            <span>画面比例</span>
            <div role="group" aria-label="画面比例">
              <button
                v-for="item in [
                  { value: 'portrait', label: '竖版 3:4' },
                  { value: 'square', label: '方形 1:1' },
                  { value: 'landscape', label: '横版 16:9' },
                ]"
                :key="item.value"
                type="button"
                :aria-pressed="form.aspect === item.value"
                :class="{ active: form.aspect === item.value }"
                @click="form.aspect = item.value as Aspect"
              >
                {{
                  kind === "video" && item.value === "portrait"
                    ? "竖版 9:16"
                    : item.label
                }}
              </button>
            </div>
          </div>
          <label v-if="kind === 'video'" class="mkt-check"
            ><input
              type="checkbox"
              v-model="form.videoCost"
            />我已核对供应商额度，确认本次生成会消耗额度；免费额度耗尽后可能计费。</label
          >
        </fieldset>
        <div class="mkt-provider">
          <span class="mkt-dot" :class="{ off: !ready }"></span
          ><span
            >{{ kind === "image" ? "Kolors 图片服务" : "万相视频服务" }} ·
            {{ ready ? "已配置" : "未配置" }}</span
          >
        </div>
        <button
          class="button primary mkt-generate"
          :disabled="
            !ready ||
            submission.busy ||
            (!submission.pending && kind === 'video' && !form.videoCost)
          "
          type="submit"
        >
          <WandSparkles :size="16" />{{
            submission.busy
              ? "正在提交…"
              : submission.pending
                ? "核实原提交"
                : kind === "image"
                  ? "生成宣传配图"
                  : "生成 5 秒短片"
          }}<ArrowUpRight :size="15" />
        </button>
        <p class="mkt-help">
          {{
            !ready
              ? kind === "image"
                ? "尚未配置真实生成接口。右侧仍可预览并导出示例版式。"
                : "视频接口尚未启用，可先编辑并导出配套文案。"
              : `当前门店每日最多提交 ${options.daily_limit} 次；任务保存后可离开页面。`
          }}
        </p>
        <p v-if="submission.pending" class="mkt-help">
          原提交结果尚未核实，重试会使用同一个请求编号，不创建重复任务。
        </p>
      </form>
    </section>
    <section class="card marketing-preview" aria-label="作品预览">
      <div class="mkt-section-heading">
        <span>02 / 作品预览</span
        ><small>{{
          kind === "image"
            ? sample
              ? "示例配图 · 非实时生成"
              : "使用已生成的配图"
            : "视频与文案独立导出"
        }}</small>
      </div>
      <div
        v-if="
          selected &&
          ['queued', 'submitting', 'running', 'unknown', 'failed'].includes(
            selected.state,
          )
        "
        class="mkt-task"
        role="status"
      >
        <Sparkles :size="17" />
        <div>
          <strong>{{ stateNames[selected.state] }}</strong>
          <p>
            {{
              selected.error_code
                ? mediaErrors[selected.error_code] ||
                  "请查看服务配置并核实任务。"
                : "任务已入队，页面会自动查询进度。"
            }}
          </p>
        </div>
      </div>
      <div v-if="assetBusy" class="mkt-loading" role="status">
        正在读取已生成素材…
      </div>
      <div v-if="kind === 'image'" class="mkt-poster-stage">
        <img
          v-if="posterUrl"
          :src="posterUrl"
          alt="当前宣传海报排版预览"
        /><span v-else>正在准备版式…</span>
      </div>
      <div v-else class="mkt-video-stage">
        <video
          v-if="assetUrl && selected?.kind === 'video'"
          :src="assetUrl"
          controls
          preload="metadata"
          aria-label="生成的宣传短片"
        ></video>
        <div v-else>
          <Clapperboard :size="38" :stroke-width="1.1" /><strong
            >让一个想法，开始流动。</strong
          >
          <p>真实生成完成后，可在这里播放。<br />当前未展示示例视频。</p>
          <span>5 SECONDS · AI VIDEO</span>
        </div>
      </div>
      <div class="mkt-preview-footer">
        <span>{{
          kind === "image"
            ? "标题与文案独立排版，修改无需重新生图。"
            : "当前接入无声短片生成，配套文案可用于后期字幕。"
        }}</span>
        <div>
          <button
            v-if="kind === 'image'"
            class="button primary"
            :disabled="!posterBlob"
            @click="downloadPoster"
          >
            <ArrowDownToLine :size="15" />{{
              sample ? "下载示例海报" : "下载海报 PNG"
            }}</button
          ><button
            v-else
            class="button primary"
            :disabled="!assetBlob || selected?.kind !== 'video'"
            @click="downloadVideo"
          >
            <ArrowDownToLine :size="15" />下载视频</button
          ><button class="button secondary" @click="downloadCopy">
            导出文案
          </button>
        </div>
        <p>
          AI
          场景素材与创作草稿，发布前请核对项目、文案与品牌信息。演示素材保留演示标识。
        </p>
      </div>
    </section>
  </div>
  <section class="card marketing-library" aria-label="营销作品库">
    <div class="mkt-library-heading">
      <div>
        <p class="eyebrow">YOUR CREATIVE COLLECTION</p>
        <h2>每一份灵感，都有迹可循。</h2>
        <p>当前门店的生成任务与作品 · 已完成 {{ totalDone }} 份</p>
      </div>
      <button
        class="button secondary"
        :disabled="!allowed || busy"
        @click="load()"
      >
        <RefreshCw :size="14" />刷新作品库
      </button>
    </div>
    <div v-if="!jobs.length" class="mkt-library-empty">
      <Layers :size="30" :stroke-width="1.1" /><strong
        >第一份作品，等你开启。</strong
      >
      <p>生成任务会保存在这里。未配置接口时，可以先试试上方的示例排版。</p>
    </div>
    <div v-else class="mkt-job-grid">
      <article
        v-for="job in jobs"
        :key="job.id"
        class="mkt-job"
        :class="{ selected: selected?.id === job.id }"
      >
        <button
          type="button"
          class="mkt-job-open"
          :disabled="!!submission.pending"
          @click="choose(job)"
        >
          <div class="mkt-job-icon">
            <component
              :is="job.kind === 'image' ? ImagePlus : Clapperboard"
              :size="25"
              :stroke-width="1.2"
            />
          </div>
          <span class="mkt-job-status" :class="job.state">{{
            stateNames[job.state]
          }}</span>
          <h3>{{ job.title }}</h3>
          <p>
            {{ job.kind === "image" ? "图文海报" : "5 秒短片" }} ·
            {{ new Date(job.created_at).toLocaleDateString("zh-CN")
            }}{{ job.simulated ? " · 演示" : "" }}
          </p>
        </button>
        <div class="mkt-job-actions">
          <button
            v-if="job.state === 'queued'"
            :disabled="busy"
            @click="action(job, 'cancel')"
          >
            取消排队</button
          ><button
            v-if="
              ['failed', 'unknown'].includes(job.state) && job.can_reconcile
            "
            :disabled="busy"
            @click="action(job, 'reconcile')"
          >
            核实原任务</button
          ><span v-if="job.state === 'succeeded'">已转存 · 可预览下载</span>
        </div>
      </article>
    </div>
    <button
      v-if="hasMore"
      class="button secondary mkt-more"
      :disabled="busy"
      @click="load(true)"
    >
      加载更早作品
    </button>
  </section>
</template>

<style scoped>
.marketing-heading {
  margin-bottom: 24px;
}
.marketing-heading h1 {
  font-size: 30px;
  letter-spacing: -0.04em;
}
.marketing-mark {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  background: #e9efdf;
  color: #81986d;
  border-radius: 18px;
}
.marketing-intro {
  display: flex;
  justify-content: space-between;
  gap: 15px;
  align-items: center;
  padding: 0 0 22px;
  font-size: 11px;
  color: #8c9785;
}
.marketing-intro > span:first-child {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #647c51;
}
.mkt-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #8ba574;
  flex-shrink: 0;
}
.mkt-dot.off {
  background: #b6b9ad;
}
.marketing-layout {
  display: grid;
  grid-template-columns: minmax(260px, 0.95fr) minmax(260px, 1fr);
  gap: 22px;
  align-items: start;
}
.marketing-editor,
.marketing-preview {
  min-width: 0;
  border-radius: 18px;
  overflow: hidden;
}
.marketing-editor {
  padding: 26px;
}
.mkt-section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: #566d46;
  margin-bottom: 22px;
}
.mkt-section-heading > span {
  font-weight: 500;
  white-space: nowrap;
}
.mkt-section-heading small {
  font-size: 9px;
  color: #9ba48f;
  text-align: right;
}
.mkt-mode {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 24px;
}
.mkt-mode button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 9px;
  border: 1px solid #e5e9df;
  border-radius: 13px;
  padding: 15px 13px;
  background: #fafbf7;
  text-align: left;
  color: #8b987e;
}
.mkt-mode button.active {
  border-color: #aabe94;
  background: #f0f5e9;
  color: #466435;
  box-shadow: 0 0 0 2px #edf2e6;
}
.mkt-mode strong {
  font-size: 12px;
  font-weight: 500;
}
.mkt-mode small {
  font-size: 9px;
  line-height: 1.6;
}
.marketing-editor fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.marketing-editor label {
  display: flex;
  flex-direction: column;
  gap: 9px;
  font-size: 11px;
  color: #617154;
  margin-bottom: 19px;
}
.marketing-editor input:not([type="checkbox"]),
.marketing-editor textarea,
.marketing-editor select {
  width: 100%;
  min-width: 0;
  padding: 12px 13px;
  background: #fcfdf9;
  border: 1px solid #e0e7d8;
  border-radius: 10px;
  font: inherit;
  font-size: 12px;
  color: #3c5332;
  outline: none;
  line-height: 1.8;
}
.marketing-editor textarea {
  resize: vertical;
}
.marketing-editor input:focus,
.marketing-editor textarea:focus,
.marketing-editor select:focus {
  border-color: #99b181;
  box-shadow: 0 0 0 3px #eaf1e3;
}
.marketing-editor label > small {
  font-size: 10px;
  color: #9aa38e;
  line-height: 1.8;
}
.mkt-field-note {
  font-size: 9px;
  color: #a0a891;
}
.mkt-presets {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 23px;
  font-size: 9px;
  color: #9ca58f;
}
.mkt-presets > span {
  margin-right: 3px;
}
.mkt-presets button {
  padding: 7px 9px;
  background: #f1f4ec;
  border-radius: 20px;
  color: #82936f;
  font-size: 9px;
}
.mkt-size {
  font-size: 11px;
  color: #617154;
  margin-bottom: 22px;
}
.mkt-size > div {
  display: flex;
  gap: 6px;
  margin-top: 11px;
}
.mkt-size button {
  flex: 1;
  min-width: 0;
  padding: 9px 2px;
  border: 1px solid #e3e9db;
  border-radius: 8px;
  font-size: 10px;
  color: #94a085;
}
.mkt-size button.active {
  background: #eef4e7;
  border-color: #bfd0ad;
  color: #516f3f;
}
.marketing-editor .mkt-check {
  flex-direction: row;
  align-items: flex-start;
  line-height: 1.8;
  font-size: 10px;
  color: #8d947e;
}
.mkt-check input {
  margin-top: 4px;
  accent-color: #436637;
}
.mkt-provider {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: #92a083;
  border-top: 1px solid #edf0e8;
  padding-top: 18px;
  margin: 10px 0 14px;
}
.mkt-generate {
  width: 100%;
  justify-content: center;
  border-radius: 12px;
}
.mkt-generate svg:last-child {
  margin-left: auto;
}
.mkt-help {
  font-size: 10px;
  line-height: 1.9;
  color: #a0a78f;
  margin: 11px 0 0;
}
.marketing-preview {
  padding: 25px 22px 0;
  background: #fff;
}
.mkt-poster-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 290px;
  padding: 20px;
  background: #f1f3ec;
  border: 1px solid #e7ebdf;
  border-radius: 12px;
}
.mkt-poster-stage img {
  display: block;
  max-width: 100%;
  max-height: 520px;
  object-fit: contain;
  box-shadow: 0 12px 35px #334d2912;
}
.mkt-preview-footer {
  padding: 19px 0 20px;
}
.mkt-preview-footer > span {
  display: block;
  font-size: 10px;
  color: #8f9b83;
  line-height: 1.8;
}
.mkt-preview-footer > div {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0;
}
.mkt-preview-footer .button {
  font-size: 10px;
  padding: 10px 13px;
}
.mkt-preview-footer > p {
  font-size: 9px;
  line-height: 1.9;
  color: #a5ab98;
  border-top: 1px solid #edf0e6;
  padding-top: 14px;
}
.mkt-video-stage {
  display: grid;
  place-items: center;
  min-height: 340px;
  background: linear-gradient(145deg, #edf2e5, #e2e9da);
  border-radius: 12px;
  color: #879a73;
}
.mkt-video-stage > div {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 30px 18px;
}
.mkt-video-stage strong {
  font-weight: 400;
  font-size: 17px;
  color: #617b4d;
  margin: 22px 0 12px;
}
.mkt-video-stage p {
  font-size: 11px;
  color: #96a085;
  line-height: 1.9;
}
.mkt-video-stage span {
  font-size: 8px;
  letter-spacing: 0.16em;
  color: #a2ae90;
  margin-top: 27px;
}
.mkt-video-stage video {
  width: 100%;
  max-height: 520px;
}
.mkt-task {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 14px;
  background: #f1f5ea;
  border: 1px solid #e1e9d6;
  border-radius: 10px;
  color: #80946a;
  margin-bottom: 17px;
}
.mkt-task strong {
  font-size: 11px;
  font-weight: 500;
}
.mkt-task p {
  font-size: 10px;
  line-height: 1.8;
  color: #98a187;
  margin-top: 4px;
}
.mkt-loading {
  font-size: 11px;
  color: #91a27e;
  padding: 10px;
}
.marketing-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  font-size: 11px;
  background: #ebf3e4;
  border-radius: 9px;
  color: #6a8455;
  margin-bottom: 18px;
}
.marketing-library {
  margin-top: 25px;
  border-radius: 18px;
  padding: 28px;
}
.mkt-library-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}
.mkt-library-heading h2 {
  font-size: 20px;
  font-weight: 500;
  letter-spacing: -0.03em;
  margin: 8px 0 9px;
}
.mkt-library-heading p:not(.eyebrow) {
  font-size: 10px;
  color: #a0a88f;
}
.mkt-library-heading > .button {
  font-size: 10px;
  padding: 10px 13px;
  flex-shrink: 0;
}
.mkt-library-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  color: #a8b49a;
  padding: 48px 15px 30px;
}
.mkt-library-empty strong {
  font-size: 14px;
  font-weight: 400;
  color: #7a9067;
  margin: 16px 0 10px;
}
.mkt-library-empty p {
  font-size: 10px;
  line-height: 1.9;
  color: #a9b19d;
}
.mkt-job-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 13px;
  margin-top: 25px;
}
.mkt-job {
  border: 1px solid #e6ebde;
  border-radius: 12px;
  overflow: hidden;
  background: #fbfcf8;
}
.mkt-job.selected {
  border-color: #b5c8a0;
}
.mkt-job-open {
  position: relative;
  display: block;
  width: 100%;
  text-align: left;
  padding: 20px 15px 15px;
}
.mkt-job-icon {
  color: #a1b08c;
  margin: 7px 0 20px;
}
.mkt-job-status {
  position: absolute;
  top: 15px;
  right: 12px;
  border-radius: 20px;
  background: #edf0e7;
  padding: 4px 7px;
  font-size: 8px;
  color: #8b987b;
}
.mkt-job-status.succeeded {
  background: #e6efdc;
  color: #6d8a50;
}
.mkt-job-status.failed,
.mkt-job-status.unknown {
  background: #f3eade;
  color: #a4865a;
}
.mkt-job-open h3 {
  font-size: 12px;
  font-weight: 500;
  line-height: 1.8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mkt-job-open p {
  font-size: 9px;
  color: #a1a98f;
  margin-top: 7px;
}
.mkt-job-actions {
  padding: 0 15px 13px;
  min-height: 24px;
  font-size: 9px;
  color: #9aa68a;
}
.mkt-job-actions button {
  padding: 5px 0;
  color: #7d9465;
  font-size: 10px;
}
.mkt-more {
  display: flex;
  margin: 22px auto 0;
  font-size: 11px;
}
@media (max-width: 1150px) {
  .marketing-editor {
    padding: 21px;
  }
  .marketing-preview {
    padding: 21px 17px 0;
  }
  .marketing-layout {
    gap: 16px;
  }
  .marketing-heading h1 {
    font-size: 26px;
  }
  .mkt-section-heading {
    flex-wrap: wrap;
  }
  .mkt-poster-stage {
    padding: 13px;
  }
  .mkt-job-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 650px) {
  .marketing-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .marketing-heading h1 {
    font-size: 24px;
  }
  .marketing-mark {
    display: none;
  }
  .marketing-intro {
    font-size: 9px;
  }
  .mkt-library-heading {
    flex-wrap: wrap;
  }
  .marketing-library {
    padding: 21px;
  }
  .mkt-job-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .mkt-poster-stage img {
    max-height: 450px;
  }
}
</style>
