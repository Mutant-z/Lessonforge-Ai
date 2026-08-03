<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import type { PPTSlide } from '../../types';
import { Refresh, Microphone } from '@element-plus/icons-vue';

const props = defineProps<{
  slide: PPTSlide;
  slideIndex: number;
  totalSlides: number;
}>();

const emit = defineEmits<{
  (e: 'regenerateSlide', slideIndex: number): void;
}>();

const PPT_CANVAS_WIDTH = 960;
const canvasFrame = ref<HTMLElement | null>(null);
const canvasScale = ref(1);
let resizeObserver: ResizeObserver | null = null;

const bullets = computed(() => props.slide.bullet_points || (props.slide as unknown as { body?: string[] }).body || []);
const layoutName = computed(() => props.slide.layout_type || (props.slide as unknown as { layout?: string }).layout || '标准演示页');

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
  <div class="slide-preview-container animate-fade-in">
    <!-- 16:9 Presentation Canvas -->
    <div ref="canvasFrame" class="ppt-canvas-frame">
      <div class="ppt-canvas" :style="{ transform: `scale(${canvasScale})` }">
        <div class="ppt-header">
          <span class="slide-num-badge">PAGE {{ slide.slide_number || slideIndex + 1 }} / {{ totalSlides }}</span>
          <span class="layout-badge">{{ layoutName }}</span>
        </div>

        <h2 class="slide-title">{{ slide.title || '无标题幻灯片' }}</h2>

        <div class="slide-bullets-area">
          <ul>
            <li v-for="(bullet, bIdx) in bullets" :key="bIdx">
              {{ bullet }}
            </li>
          </ul>
        </div>

        <div v-if="slide.visual_suggestion" class="slide-visual-hint">
          <strong>视觉展示建议：</strong> {{ slide.visual_suggestion }}
        </div>
      </div>
    </div>

    <!-- Speaker Notes & Controls Footer -->
    <div class="ppt-footer-panel">
      <div class="notes-header">
        <div class="notes-title">
          <el-icon><Microphone /></el-icon>
          <span>教师讲解备注</span>
        </div>
        <div class="slide-actions">
          <el-button size="small" :icon="Refresh" @click="emit('regenerateSlide', slideIndex)">
            重新生成本页 PPT
          </el-button>
        </div>
      </div>
      <p class="notes-content">{{ slide.speaker_notes || '本页无额外演说备注。' }}</p>
    </div>
  </div>
</template>

<style scoped>
.slide-preview-container {
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ppt-canvas-frame {
  width: 100%;
  aspect-ratio: 16 / 9;
  position: relative;
  overflow: hidden;
  background: #ffffff;
}

.ppt-canvas {
  width: 960px;
  height: 540px;
  box-sizing: border-box;
  background: #ffffff;
  color: #18191d;
  border: 1px solid #cfd2d9;
  border-top: 8px solid #002fa7;
  border-radius: 0;
  padding: 40px;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  position: absolute;
  inset: 0 auto auto 0;
  overflow: hidden;
  transform-origin: top left;
  will-change: transform;
}

.ppt-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.slide-num-badge {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.1em;
  color: #002fa7;
  background: transparent;
  padding: 4px 12px;
  border-radius: 0;
}

.layout-badge {
  font-size: 12px;
  color: #656a73;
}

.slide-title {
  font-size: 32px;
  font-weight: 800;
  margin: 0 0 24px;
  line-height: 1.2;
  color: #18191d;
}

.slide-bullets-area {
  flex: 1;
  overflow-y: auto;
}

.slide-bullets-area ul {
  margin: 0;
  padding-left: 24px;
}

.slide-bullets-area li {
  font-size: 18px;
  line-height: 1.8;
  color: #34373d;
  margin-bottom: 12px;
}

.slide-visual-hint {
  margin-top: auto;
  padding: 12px 16px;
  background: #f7f7f8;
  border-left: 3px solid #002fa7;
  border-radius: 0;
  font-size: 13px;
  color: #51545b;
}

.ppt-footer-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 0;
  padding: 20px;
}

.notes-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.notes-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #002fa7;
}

.notes-content {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}
</style>
