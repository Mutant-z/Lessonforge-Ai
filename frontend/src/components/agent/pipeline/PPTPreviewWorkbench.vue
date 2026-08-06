<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { CircleCheck, Clock, Edit, Lock, MagicStick, RefreshRight } from '@element-plus/icons-vue';
import type { PPTContent, PPTTemplate } from '../../../types';
import { DEFAULT_PPT_TEMPLATE } from '../../../utils/pptTemplate';
import PPTSlideFilmstrip from './PPTSlideFilmstrip.vue';
import PPTPreviewStage from './PPTPreviewStage.vue';

const props = defineProps<{
  pptContent: PPTContent | null;
  template: PPTTemplate | null;
  isRunning?: boolean;
  activeSlideIndex?: number;
  modifiedSlides?: Set<number>;
}>();

const emit = defineEmits<{
  (e: 'select-slide', index: number): void;
  (e: 'modify-slide', index: number): void;
  (e: 'open-template-drawer'): void;
  (e: 'open-version-drawer'): void;
  (e: 'sync-context'): void;
}>();

const slides = computed(() => props.pptContent?.slides || []);
const pptTheme = computed(() => props.template || DEFAULT_PPT_TEMPLATE);

const internalActiveSlide = ref(0);

watch(
  () => props.activeSlideIndex,
  newVal => {
    if (newVal !== undefined && newVal !== null && newVal >= 0 && newVal < slides.value.length) {
      internalActiveSlide.value = newVal;
    }
  },
  { immediate: true },
);

function handleSelectSlide(index: number) {
  internalActiveSlide.value = index;
  emit('select-slide', index);
}

function handleModifySlide(index: number) {
  emit('modify-slide', index);
}
</script>

<template>
  <div class="ppt-preview-workbench">
    <!-- Top Header Bar for Preview Pane -->
    <header class="preview-workbench-header">
      <div class="header-left-title">
        <span class="preview-badge">PPT 实时课件预览</span>
        <span v-if="slides.length" class="total-slides-chip">{{ slides.length }} 页</span>
      </div>

      <div class="header-actions">
        <el-button
          size="small"
          :icon="MagicStick"
          :disabled="isRunning"
          @click="emit('open-template-drawer')"
        >
          模板 · {{ pptTheme.short_name }}
        </el-button>
        <el-button size="small" :icon="Clock" @click="emit('open-version-drawer')">
          版本历史
        </el-button>
        <el-button size="small" :icon="RefreshRight" :disabled="isRunning" @click="emit('sync-context')">
          同步
        </el-button>
      </div>
    </header>

    <!-- Main Content: Filmstrip Sidebar + Canvas Stage -->
    <div class="preview-workbench-body">
      <template v-if="slides.length">
        <PPTSlideFilmstrip
          :slides="slides"
          :active-slide="internalActiveSlide"
          :template="pptTheme"
          :modified-slides="modifiedSlides"
          @select-slide="handleSelectSlide"
        />
        <PPTPreviewStage
          :slide="slides[internalActiveSlide] || null"
          :slide-index="internalActiveSlide"
          :total-slides="slides.length"
          :template="pptTheme"
          :is-running="isRunning"
          @change-slide="handleSelectSlide"
          @modify-slide="handleModifySlide"
        />
      </template>

      <div v-else class="preview-empty-state">
        <el-icon class="empty-icon"><MagicStick /></el-icon>
        <h3>PPT 课件尚未生成</h3>
        <p>向教学 Agent 提出修改或生成需求，生成的每页 PPT 将在此实时渲染与预览。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ppt-preview-workbench {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  min-width: 0;
  overflow: hidden;
}

.preview-workbench-header {
  height: 44px;
  border-bottom: 1px solid var(--border-default, #e2e8f0);
  padding: 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #ffffff;
  flex-shrink: 0;
}

.header-left-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-badge {
  font-size: 13px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.total-slides-chip {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 999px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.preview-workbench-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
  position: relative;
}

.preview-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
}

.empty-icon {
  font-size: 36px;
  color: #818cf8;
  margin-bottom: 12px;
}

.preview-empty-state h3 {
  margin: 0 0 6px 0;
  font-size: 15px;
  font-weight: 800;
  color: #1e293b;
}

.preview-empty-state p {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
  max-width: 320px;
  line-height: 1.5;
}
</style>
