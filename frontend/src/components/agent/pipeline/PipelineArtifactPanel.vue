<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { PPTContent, PPTTemplate } from '../../../types';
import SlidePreview from '../../domain/SlidePreview.vue';
import SlideThumbnail from '../../domain/SlideThumbnail.vue';
import { DEFAULT_PPT_TEMPLATE } from '../../../utils/pptTemplate';

const props = defineProps<{
  pptContent: PPTContent | null;
  template: PPTTemplate | null;
}>();

const pptSlides = computed(() => props.pptContent?.slides || []);
const pptTheme = computed(() => props.template || DEFAULT_PPT_TEMPLATE);
const activeSlide = ref(0);

watch(() => pptSlides.value.length, count => {
  if (activeSlide.value >= count) activeSlide.value = 0;
});
</script>

<template>
  <div class="artifact-panel">
    <div class="panel-head">
      <span class="panel-title">PPT 预览</span>
      <span v-if="pptSlides.length" class="panel-count">{{ pptSlides.length }} 页</span>
    </div>
    <div class="ppt-thumbs">
      <SlideThumbnail v-for="(slide, index) in pptSlides" :key="slide.id || index"
                      :slide="slide" :index="index" :total-slides="pptSlides.length"
                      :is-active="activeSlide === index" :template="pptTheme"
                      @select="activeSlide = $event" />
    </div>
    <div v-if="pptSlides.length" class="ppt-main">
      <SlidePreview :slide="pptSlides[activeSlide]" :slide-index="activeSlide" :total-slides="pptSlides.length" :template="pptTheme" />
      <div class="slide-caption">第 {{ activeSlide + 1 }} / {{ pptSlides.length }} 页</div>
    </div>
    <div v-else class="a-empty">PPT 尚未生成。流水线完成后在此预览每一页。</div>
  </div>
</template>

<style scoped>
.artifact-panel { height: 100%; overflow-y: auto; padding: 10px 12px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.panel-title { font-size: 14px; font-weight: 600; color: #111827; }
.panel-count { font-size: 12px; color: #9ca3af; }
.ppt-thumbs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.ppt-main { border: 1px solid #eef0f3; border-radius: 10px; padding: 12px; }
.slide-caption { text-align: center; font-size: 12px; color: #6b7280; margin-top: 8px; }
.a-empty { text-align: center; color: #9ca3af; font-size: 12px; padding: 48px 12px; }
</style>
