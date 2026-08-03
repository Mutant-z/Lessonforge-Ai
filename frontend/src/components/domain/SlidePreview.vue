<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import type { PPTSlide, PPTTemplate } from '../../types';
import { Refresh, Microphone } from '@element-plus/icons-vue';
import { DEFAULT_PPT_TEMPLATE, pptTemplateStyle } from '../../utils/pptTemplate';

const props = defineProps<{
  slide: PPTSlide;
  slideIndex: number;
  totalSlides: number;
  template?: PPTTemplate | null;
}>();

const emit = defineEmits<{
  (e: 'regenerateSlide', slideIndex: number): void;
}>();

const PPT_CANVAS_WIDTH = 960;
const canvasFrame = ref<HTMLElement | null>(null);
const canvasScale = ref(1);
let resizeObserver: ResizeObserver | null = null;

const activeTemplate = computed(() => props.template || DEFAULT_PPT_TEMPLATE);
const bullets = computed(() => props.slide.bullet_points || props.slide.body || []);
const layoutName = computed(() => props.slide.layout_type || props.slide.layout || '标准演示页');
const pageType = computed(() => props.slide.page_type || 'concept');
const isCover = computed(() => pageType.value === 'cover' || ['title', 'cover'].includes(props.slide.layout || ''));
const isProcess = computed(() => pageType.value === 'process' || props.slide.layout === 'steps');
const isSplit = computed(() => pageType.value === 'comparison' || props.slide.layout === 'split');
const canvasClasses = computed(() => [
  `theme-${activeTemplate.value.composition}`,
  `page-${pageType.value}`,
  { 'is-cover': isCover.value, 'is-process': isProcess.value, 'is-split': isSplit.value },
]);

function syncCanvasScale(width: number) {
  if (width > 0) canvasScale.value = width / PPT_CANVAS_WIDTH;
}

onMounted(() => {
  if (!canvasFrame.value) return;
  syncCanvasScale(canvasFrame.value.clientWidth);
  resizeObserver = new ResizeObserver(([entry]) => {
    if (entry) syncCanvasScale(entry.contentRect.width);
  });
  resizeObserver.observe(canvasFrame.value);
});

onBeforeUnmount(() => resizeObserver?.disconnect());
</script>

<template>
  <div class="slide-preview-container animate-fade-in" :style="pptTemplateStyle(activeTemplate)">
    <div ref="canvasFrame" class="ppt-canvas-frame">
      <div class="ppt-canvas" :class="canvasClasses" :style="{ transform: `scale(${canvasScale})` }">
        <div class="composition-decoration" aria-hidden="true"><i /><i /><i /></div>
        <div class="ppt-header">
          <span class="slide-num-badge">PAGE {{ slide.slide_number || slideIndex + 1 }} / {{ totalSlides }}</span>
          <span class="layout-badge">{{ layoutName }}</span>
        </div>

        <div class="slide-content">
          <h2 class="slide-title">{{ slide.title || '无标题幻灯片' }}</h2>
          <p v-if="isCover && slide.purpose" class="cover-purpose">{{ slide.purpose }}</p>

          <div v-if="isProcess" class="process-layout">
            <div v-for="(bullet, bIdx) in bullets.slice(0, 4)" :key="bIdx" class="process-step">
              <span>{{ String(bIdx + 1).padStart(2, '0') }}</span>
              <p>{{ bullet }}</p>
            </div>
          </div>
          <div v-else-if="isSplit" class="split-layout">
            <ul v-for="column in 2" :key="column">
              <li v-for="(bullet, bIdx) in bullets.filter((_, index) => index % 2 === column - 1)" :key="bIdx">{{ bullet }}</li>
            </ul>
          </div>
          <ul v-else class="slide-bullets-area">
            <li v-for="(bullet, bIdx) in bullets" :key="bIdx">{{ bullet }}</li>
          </ul>
        </div>

        <div v-if="slide.visual_suggestion && !isCover" class="slide-visual-hint">
          <strong>视觉展示建议：</strong>{{ slide.visual_suggestion }}
        </div>
      </div>
    </div>

    <div class="ppt-footer-panel">
      <div class="notes-header">
        <div class="notes-title"><el-icon><Microphone /></el-icon><span>教师讲解备注</span></div>
        <el-button size="small" :icon="Refresh" @click="emit('regenerateSlide', slideIndex)">重新生成本页 PPT</el-button>
      </div>
      <p class="notes-content">{{ slide.speaker_notes || '本页无额外演说备注。' }}</p>
    </div>
  </div>
</template>

<style scoped>
.slide-preview-container { width: 100%; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.ppt-canvas-frame { width: 100%; aspect-ratio: 16 / 9; position: relative; overflow: hidden; background: var(--ppt-bg); }
.ppt-canvas {
  width: 960px; height: 540px; box-sizing: border-box; position: absolute; inset: 0 auto auto 0;
  overflow: hidden; transform-origin: top left; will-change: transform; padding: 40px 54px 36px 72px;
  color: var(--ppt-text); background: var(--ppt-bg); border: 1px solid color-mix(in srgb, var(--ppt-muted) 28%, transparent);
  font-family: var(--ppt-body-font); display: flex; flex-direction: column;
}
.ppt-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; position: relative; z-index: 2; }
.slide-num-badge { font: 800 12px/1 var(--ppt-latin-font); letter-spacing: .1em; color: var(--ppt-primary); }
.layout-badge { font-size: 12px; color: var(--ppt-muted); }
.slide-content { position: relative; z-index: 2; flex: 1; min-height: 0; display: flex; flex-direction: column; }
.slide-title { font-family: var(--ppt-heading-font); font-size: 32px; font-weight: 800; margin: 0 0 24px; line-height: 1.2; color: var(--ppt-text); }
.cover-purpose { margin: auto 0 0; color: var(--ppt-primary); font-size: 17px; font-weight: 700; }
.slide-bullets-area { flex: 1; overflow: hidden; margin: 0; padding-left: 24px; }
.slide-bullets-area li { font-size: 18px; line-height: 1.7; color: var(--ppt-text); margin-bottom: 10px; }
.slide-bullets-area li::marker { color: var(--ppt-primary); }
.slide-visual-hint { position: relative; z-index: 2; margin-top: 14px; padding: 10px 14px; background: var(--ppt-surface); border-left: 3px solid var(--ppt-primary); font-size: 12px; color: var(--ppt-muted); }
.slide-visual-hint strong { color: var(--ppt-text); }
.process-layout { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 14px; }
.process-step { min-width: 0; border-top: 4px solid var(--ppt-secondary); padding-top: 14px; }
.process-step span { font: 800 25px/1 var(--ppt-latin-font); color: var(--ppt-primary); }
.process-step p { margin: 16px 0 0; font-size: 17px; line-height: 1.45; font-weight: 700; }
.split-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.split-layout ul { margin: 0; padding: 18px 20px 18px 38px; border-top: 4px solid var(--ppt-primary); background: var(--ppt-surface); }
.split-layout ul + ul { border-top-color: var(--ppt-secondary); }
.split-layout li { margin-bottom: 14px; font-size: 17px; line-height: 1.5; }
.composition-decoration { position: absolute; inset: 0; pointer-events: none; }

.theme-swiss_rail { border-top: 8px solid var(--ppt-primary); }
.theme-swiss_rail::before { content: ''; position: absolute; left: 32px; top: 34px; bottom: 34px; width: 6px; background: var(--ppt-primary); }
.theme-nordic_field { padding-left: 62px; }
.theme-nordic_field .composition-decoration i:first-child { position: absolute; width: 250px; height: 250px; right: -90px; top: -110px; border-radius: 50%; background: var(--ppt-secondary); }
.theme-nordic_field .slide-visual-hint { border-left: 0; border-radius: 18px; }
.theme-academic_offset { padding-left: 190px; }
.theme-academic_offset::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 150px; background: var(--ppt-primary); }
.theme-academic_offset .slide-num-badge { position: absolute; left: -145px; color: var(--ppt-on-primary); }
.theme-academic_offset .slide-title { color: var(--ppt-primary); }
.theme-editorial_margin { padding-left: 84px; border: 12px solid var(--ppt-bg); outline: 1px solid var(--ppt-secondary); outline-offset: -24px; }
.theme-editorial_margin::before { content: ''; position: absolute; left: 44px; top: 36px; bottom: 36px; width: 2px; background: var(--ppt-primary); }
.theme-editorial_margin .slide-title { font-weight: 700; letter-spacing: .04em; }
.theme-science_signal { border-top: 7px solid var(--ppt-primary); }
.theme-science_signal::before { content: ''; position: absolute; left: 38px; top: 34px; bottom: 34px; width: 3px; background: var(--ppt-primary); box-shadow: 7px 0 0 var(--ppt-secondary); }
.theme-science_signal .slide-title { color: var(--ppt-text); text-shadow: 0 0 18px color-mix(in srgb, var(--ppt-primary) 30%, transparent); }
.theme-science_signal .slide-visual-hint { border: 1px solid var(--ppt-secondary); }
.theme-primary_blocks::before { content: ''; position: absolute; width: 170px; height: 170px; left: -75px; top: -72px; border-radius: 50%; background: var(--ppt-secondary); }
.theme-primary_blocks::after { content: ''; position: absolute; width: 145px; height: 145px; right: -66px; bottom: -62px; border-radius: 50%; background: var(--ppt-primary); }
.theme-primary_blocks .slide-title { font-size: 35px; }
.theme-primary_blocks .slide-num-badge { color: var(--ppt-on-primary); }
.theme-primary_blocks .slide-visual-hint { border-left: 0; border-radius: 18px; }
.is-cover .ppt-header { margin-bottom: 82px; }
.is-cover .slide-title { max-width: 760px; font-size: 44px; line-height: 1.16; }
.is-cover .slide-bullets-area { display: flex; flex: initial; gap: 10px; padding: 0; list-style: none; }
.is-cover .slide-bullets-area li { color: var(--ppt-muted); }

.ppt-footer-panel { background: var(--bg-surface); border: 1px solid var(--border-default); padding: 20px; }
.notes-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.notes-title { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #002fa7; }
.notes-content { margin: 0; font-size: 14px; line-height: 1.6; color: var(--text-secondary); }
</style>
