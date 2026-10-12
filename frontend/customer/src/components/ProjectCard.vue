<script setup lang="ts">
import { ArrowUpRight } from "lucide-vue-next";
import type { Project } from "../types";
defineProps<{ project: Project; compact?: boolean }>();
</script>
<template>
  <article
    class="project-card"
    :class="[
      project.category === 'medical' ? 'mist' : 'sage',
      { 'compact-project': compact },
    ]"
  >
    <a
      class="project-open"
      :href="project.detail_url"
      :aria-label="`了解${project.title}`"
    >
      <div class="project-art">
        <img
          :src="project.image_url"
          :alt="project.image_alt"
          loading="lazy"
          width="1536"
          height="1024"
        />
        <div class="project-top">
          <span>{{
            project.category === "care" ? "美容护理了解入口" : "医美了解入口"
          }}</span
          ><span class="sample-label">AI 示意</span>
        </div>
      </div>
      <div class="project-copy">
        <span class="project-english">{{
          project.simulated ? "演示服务 · 虚构供给与价格" : "公开资料 · 了解入口"
        }}</span>
        <h3>{{ project.title }}</h3>
        <p>{{ project.summary }}</p>
        <span class="project-more"
          >查看当前详情 <span><ArrowUpRight :size="17" /></span
        ></span>
      </div>
    </a>
  </article>
</template>
