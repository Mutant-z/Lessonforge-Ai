<script setup lang="ts">
import { computed, ref } from 'vue';
import { ArrowLeft, ArrowRight, Edit, FullScreen, ZoomIn, ZoomOut } from '@element-plus/icons-vue';
import type { PPTSlide, PPTTemplate } from '../../../types';
import SlidePreview from '../../domain/SlidePreview.vue';

const props = defineProps<{
  slide: PPTSlide | null;
  slideIndex: number;
  totalSlides: number;
  template?: PPTTemplate | null;
  isRunning?: boolean;
}>();

const emit = defineEmits<{
  (e: 'change-slide', index: number): void;
  (e: 'modify-slide', index: number): void;
}>();

const zoomLevel = ref<number>(100);
const isFullscreen = ref(false);

function prevSlide() {
  if (props.slideIndex > 0) {
    emit('change-slide', props.slideIndex - 1);
  }
}

function nextSlide() {
  if (props.slideIndex < props.totalSlides - 1) {
    emit('change-slide', props.slideIndex + 1);
  }
}

function handleZoomIn() {
  if (zoomLevel.value < 150) zoomLevel.value += 15;
}

function handleZoomOut() {
  if (zoomLevel.value > 50) zoomLevel.value -= 15;
}

function resetZoom() {
  zoomLevel.value = 100;
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value;
}
</script>

<template>
  <div class="stage-container" :class="{ fullscreen: isFullscreen }">
    <!-- Stage Header Toolbar -->
    <div class="stage-toolbar">
      <!-- Left: Page Badge + Slide Title -->
      <div class="toolbar-left">
        <div class="page-title-badge" title="当前页数">
          <span class="badge-dot"></span>
          第 {{ slideIndex + 1 }} / {{ totalSlides }} 页
        </div>
        <span
          v-if="slide?.title"
          class="slide-title-text"
          :title="slide.title"
        >
          {{ slide.title }}
        </span>
      </div>

      <!-- Center: Slide Navigation -->
      <div class="toolbar-center">
        <button
          type="button"
          class="nav-btn"
          :disabled="slideIndex <= 0"
          title="上一页 (←)"
          @click="prevSlide"
        >
          <el-icon><ArrowLeft /></el-icon>
        </button>

        <div class="nav-counter" title="当前页 / 总页数">
          <span class="counter-curr">{{ slideIndex + 1 }}</span>
          <span class="counter-slash">/</span>
          <span class="counter-total">{{ totalSlides }}</span>
        </div>

        <button
          type="button"
          class="nav-btn"
          :disabled="slideIndex >= totalSlides - 1"
          title="下一页 (→)"
          @click="nextSlide"
        >
          <el-icon><ArrowRight /></el-icon>
        </button>
      </div>

      <!-- Right: Actions & View Controls -->
      <div class="toolbar-right">
        <!-- Modify Slide Primary Trigger Button -->
        <button
          type="button"
          class="modify-page-btn"
          :disabled="isRunning"
          title="修改本页 AI 内容与排版"
          @click="emit('modify-slide', slideIndex)"
        >
          <el-icon class="btn-icon"><Edit /></el-icon>
          <span>修改本页</span>
        </button>

        <!-- Zoom Controls Capsule -->
        <div class="zoom-controls">
          <button
            type="button"
            class="zoom-btn"
            :disabled="zoomLevel <= 50"
            title="缩小 (50%)"
            @click="handleZoomOut"
          >
            <el-icon><ZoomOut /></el-icon>
          </button>

          <button
            type="button"
            class="zoom-text-btn"
            title="点击重置缩放 (100%)"
            @click="resetZoom"
          >
            <el-icon class="search-icon"><ZoomIn /></el-icon>
            <span class="zoom-val">{{ zoomLevel }}%</span>
          </button>

          <button
            type="button"
            class="zoom-btn"
            :disabled="zoomLevel >= 150"
            title="放大 (150%)"
            @click="handleZoomIn"
          >
            <el-icon><ZoomIn /></el-icon>
          </button>
        </div>

        <!-- Fullscreen Presentation Button -->
        <button
          type="button"
          class="tool-icon-btn"
          :class="{ active: isFullscreen }"
          :title="isFullscreen ? '退出全屏' : '全屏演示'"
          @click="toggleFullscreen"
        >
          <el-icon><FullScreen /></el-icon>
        </button>
      </div>
    </div>

    <!-- Stage Main Canvas Container -->
    <div class="stage-viewport">
      <div
        v-if="slide"
        class="stage-canvas-scaler"
        :style="{ transform: `scale(${zoomLevel / 100})` }"
      >
        <div class="stage-canvas-frame">
          <SlidePreview
            :slide="slide"
            :slide-index="slideIndex"
            :total-slides="totalSlides"
            :template="template"
          />
        </div>
      </div>

      <div v-else class="stage-empty-state">
        <p>尚未选择 PPT 页面</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stage-container {
  flex: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f8fafc;
  position: relative;
  overflow: hidden;
}

.stage-container.fullscreen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  background: #0f172a;
}

/* Toolbar Bar Styling */
.stage-toolbar {
  height: 48px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  z-index: 10;
  user-select: none;
}

.stage-container.fullscreen .stage-toolbar {
  background: #1e293b;
  border-bottom-color: #334155;
  color: #ffffff;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
}

.toolbar-left,
.toolbar-center,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Left: Page Title Badge & Title */
.page-title-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid rgba(99, 102, 241, 0.18);
  padding: 3px 12px;
  border-radius: 9999px;
  white-space: nowrap;
  letter-spacing: 0.2px;
  transition: all 0.2s ease;
}

.page-title-badge .badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366f1;
}

.slide-title-text {
  font-size: 13.5px;
  font-weight: 700;
  color: #0f172a;
  max-width: 240px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.1px;
}

.stage-container.fullscreen .slide-title-text {
  color: #f8fafc;
}

.stage-container.fullscreen .page-title-badge {
  background: rgba(99, 102, 241, 0.2);
  color: #818cf8;
  border-color: rgba(129, 140, 248, 0.3);
}

/* Center: Navigation Buttons */
.nav-btn {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.nav-btn:hover:not(:disabled) {
  background: #f8fafc;
  color: #4f46e5;
  border-color: #818cf8;
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(99, 102, 241, 0.18);
}

.nav-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.95);
}

.nav-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  border-color: #e2e8f0;
}

.stage-container.fullscreen .nav-btn {
  background: #334155;
  border-color: #475569;
  color: #cbd5e1;
}

.stage-container.fullscreen .nav-btn:hover:not(:disabled) {
  background: #475569;
  color: #ffffff;
  border-color: #818cf8;
}

.nav-counter {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 13px;
  padding: 0 4px;
}

.counter-curr {
  font-weight: 800;
  color: #0f172a;
}

.counter-slash {
  color: #94a3b8;
  font-weight: 500;
}

.counter-total {
  font-weight: 700;
  color: #64748b;
}

.stage-container.fullscreen .counter-curr {
  color: #f8fafc;
}

.stage-container.fullscreen .counter-total {
  color: #94a3b8;
}

/* Right: Modify Button & Controls */
.modify-page-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 16px;
  border-radius: 9999px;
  border: none;
  background: linear-gradient(135deg, #6366f1 0%, #7c3aed 100%);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.2px;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(99, 102, 241, 0.35);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.modify-page-btn .btn-icon {
  font-size: 14px;
}

.modify-page-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #4f46e5 0%, #6d28d9 100%);
  box-shadow: 0 5px 14px rgba(99, 102, 241, 0.45);
  transform: translateY(-1px);
}

.modify-page-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.3);
}

.modify-page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

/* Zoom Controls Capsule */
.zoom-controls {
  display: inline-flex;
  align-items: center;
  height: 32px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 9999px;
  padding: 2px 8px;
  gap: 4px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.zoom-controls:hover {
  border-color: #94a3b8;
}

.stage-container.fullscreen .zoom-controls {
  background: #334155;
  border-color: #475569;
}

.zoom-btn {
  border: none;
  background: transparent;
  color: #64748b;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.zoom-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #4f46e5;
}

.zoom-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.stage-container.fullscreen .zoom-btn {
  color: #cbd5e1;
}

.stage-container.fullscreen .zoom-btn:hover:not(:disabled) {
  background: #475569;
  color: #ffffff;
}

.zoom-text-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.zoom-text-btn:hover {
  background: #f1f5f9;
}

.stage-container.fullscreen .zoom-text-btn:hover {
  background: #475569;
}

.zoom-text-btn .search-icon {
  font-size: 12px;
  color: #64748b;
}

.zoom-val {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  min-width: 36px;
  text-align: center;
}

.stage-container.fullscreen .zoom-val,
.stage-container.fullscreen .search-icon {
  color: #f8fafc;
}

/* Fullscreen Button */
.tool-icon-btn {
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  cursor: pointer;
  font-size: 15px;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.tool-icon-btn:hover {
  background: #eef2ff;
  border-color: #818cf8;
  color: #4f46e5;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.15);
  transform: translateY(-1px);
}

.tool-icon-btn:active {
  transform: translateY(0) scale(0.95);
}

.tool-icon-btn.active {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #ffffff;
}

.stage-container.fullscreen .tool-icon-btn {
  background: #334155;
  border-color: #475569;
  color: #cbd5e1;
}

.stage-container.fullscreen .tool-icon-btn:hover {
  background: #475569;
  border-color: #818cf8;
  color: #ffffff;
}

/* Canvas Viewport */
.stage-viewport {
  flex: 1;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  position: relative;
}

.stage-canvas-scaler {
  transition: transform 150ms ease-out;
  transform-origin: center center;
  display: flex;
  align-items: center;
  justify-content: center;
  max-width: 100%;
}

.stage-canvas-frame {
  width: 820px;
  max-width: 90vw;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.15);
  border-radius: 10px;
  overflow: hidden;
  background: #ffffff;
}

.stage-empty-state {
  color: #94a3b8;
  font-size: 13px;
}
</style>
