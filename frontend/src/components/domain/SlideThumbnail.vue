<script setup lang="ts">
import type { PPTSlide, PPTTemplate } from '../../types';
import SlidePreview from './SlidePreview.vue';

// 定义缩略图组件属性：支持在侧边栏直接复用 SlidePreview 的紧凑模式
const props = defineProps<{
  slide: PPTSlide;
  index: number;
  totalSlides: number;
  isActive: boolean;
  template?: PPTTemplate | null;
}>();

const emit = defineEmits<{ (e: 'select', index: number): void }>();

function selectSlide() {
  emit('select', props.index);
}
</script>

<template>
  <div
    class="slide-thumbnail-card"
    :class="{ active: isActive }"
    role="button"
    tabindex="0"
    :aria-label="`第 ${index + 1} 页：${slide.title || '无标题'}`"
    @click="selectSlide"
    @keydown.enter.prevent="selectSlide"
    @keydown.space.prevent="selectSlide"
  >
    <div class="thumb-aspect">
      <SlidePreview
        :slide="slide"
        :slide-index="index"
        :total-slides="totalSlides"
        :template="template"
        compact
      />
    </div>
  </div>
</template>

<style scoped>
.slide-thumbnail-card {
  width: 100%;
  cursor: pointer;
  border-radius: var(--radius-md, 8px);
  border: 2px solid transparent;
  padding: 4px;
  background: transparent;
  transition: border-color var(--motion-fast, 150ms), transform var(--motion-fast, 150ms);
  box-sizing: border-box;
  display: block;
  text-align: left;
  outline: none;
}

.slide-thumbnail-card:hover,
.slide-thumbnail-card:focus-visible {
  border-color: var(--border-active, #818cf8);
  transform: translateY(-1px);
}

.slide-thumbnail-card.active {
  border-color: var(--color-primary, #4f46e5);
  box-shadow: 0 0 0 1px var(--color-primary, #4f46e5);
}

.thumb-aspect {
  width: 100%;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  position: relative;
  background: var(--ppt-bg, #ffffff);
  border: 1px solid color-mix(in srgb, var(--ppt-muted, #94a3b8) 28%, transparent);
  border-radius: 4px;
}

.thumb-aspect :deep(.slide-preview-container) {
  width: 100%;
}

.thumb-aspect :deep(.ppt-canvas-frame) {
  width: 100%;
  height: auto;
}

.thumb-aspect :deep(.ppt-canvas) {
  max-width: none;
}
</style>
