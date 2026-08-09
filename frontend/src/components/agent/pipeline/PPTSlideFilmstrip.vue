<script setup lang="ts">
import type { PPTSlide, PPTTemplate } from '../../../types';
import SlidePreview from '../../domain/SlidePreview.vue';

const props = defineProps<{
  slides: PPTSlide[];
  activeSlide: number;
  template?: PPTTemplate | null;
  modifiedSlides?: Set<number>;
  selectedSlides?: Set<number>;
}>();

const emit = defineEmits<{
  (e: 'select-slide', index: number, additive: boolean): void;
}>();
</script>

<template>
  <div class="filmstrip-container">
    <div class="filmstrip-header">
      <span class="filmstrip-title">页面索引</span>
      <span class="filmstrip-count">{{ slides.length }} 页</span>
    </div>

    <div class="filmstrip-scroll">
      <div
        v-for="(slide, index) in slides"
        :key="slide.id || index"
        class="filmstrip-item"
        :class="{ active: activeSlide === index, selected: selectedSlides?.has(index), modified: modifiedSlides?.has(index) }"
        role="button"
        tabindex="0"
        :aria-label="`切换到第 ${index + 1} 页`"
        @click.stop="emit('select-slide', index, $event.metaKey || $event.ctrlKey)"
        @keydown.enter.prevent="emit('select-slide', index, false)"
        @keydown.space.prevent="emit('select-slide', index, false)"
      >
        <div class="item-header">
          <span class="item-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span v-if="modifiedSlides?.has(index)" class="modified-dot" title="最新修订页面">
            ✨ 已更新
          </span>
        </div>

        <div class="thumbnail-aspect">
          <SlidePreview
            :slide="slide"
            :slide-index="index"
            :total-slides="slides.length"
            :template="template"
            compact
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filmstrip-container {
  width: 130px;
  height: 100%;
  border-right: 1px solid var(--border-default, #e2e8f0);
  background: #ffffff;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  user-select: none;
}

.filmstrip-header {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-default, #f1f5f9);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.filmstrip-title {
  font-size: 12px;
  font-weight: 800;
  color: var(--text-secondary, #475569);
}

.filmstrip-count {
  font-size: 11px;
  color: var(--text-muted, #94a3b8);
  font-weight: 600;
}

.filmstrip-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.filmstrip-item {
  cursor: pointer;
  border-radius: 8px;
  border: 2px solid transparent;
  padding: 4px;
  background: #f8fafc;
  transition: all 150ms ease;
  content-visibility: auto;
  contain-intrinsic-size: 104px;
}

.filmstrip-item:hover {
  border-color: #cbd5e1;
  transform: translateY(-1px);
}

.filmstrip-item.active {
  border-color: #4f46e5;
  background: #eef2ff;
  box-shadow: 0 0 0 1px #4f46e5;
}

.filmstrip-item.selected {
  border-color: #7c3aed;
  box-shadow: 0 0 0 1px #7c3aed;
}

.filmstrip-item.modified {
  border-color: #8b5cf6;
}

.item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  padding: 0 2px;
}

.item-index {
  font-size: 11px;
  font-weight: 800;
  color: #64748b;
}

.filmstrip-item.active .item-index {
  color: #4f46e5;
}

.modified-dot {
  font-size: 9px;
  font-weight: 800;
  color: #7c3aed;
  background: #f3e8ff;
  padding: 0 4px;
  border-radius: 4px;
}

.thumbnail-aspect {
  width: 100%;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  position: relative;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
}

/* 缩略图仅负责展示，整张卡片统一处理鼠标和键盘导航。 */
.thumbnail-aspect :deep(.slide-preview-container) {
  pointer-events: none;
}
</style>
