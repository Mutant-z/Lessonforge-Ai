<script setup lang="ts">
import { computed, ref } from 'vue';
import { CircleCheck, Clock, Edit, Loading, Lock, MagicStick, RefreshRight } from '@element-plus/icons-vue';
import type { PPTContent, PPTTemplate } from '../../../types';
import { DEFAULT_PPT_TEMPLATE } from '../../../utils/pptTemplate';
import PPTSlideFilmstrip from './PPTSlideFilmstrip.vue';
import PPTPreviewStage from './PPTPreviewStage.vue';
import { normalizeSlideIndex } from '../../../utils/slideNavigation';
import { inferSlideRenderMode, visibleSemanticTexts } from '../../../utils/slideRenderMode';

const props = defineProps<{
  pptContent: PPTContent | null;
  template: PPTTemplate | null;
  isRunning?: boolean;
  activeSlideIndex?: number;
  modifiedSlides?: Set<number>;
  draftSlideIndex?: number;
  selectedSlides?: Set<number>;
  loading?: boolean;
}>();

const emit = defineEmits<{
  (e: 'select-slide', index: number, additive?: boolean): void;
  (e: 'modify-slide', index: number): void;
  (e: 'open-template-drawer'): void;
  (e: 'open-version-drawer'): void;
  (e: 'sync-context'): void;
}>();

const slides = computed(() => props.pptContent?.slides || []);
const pptTheme = computed(() => props.template || DEFAULT_PPT_TEMPLATE);

const viewMode = ref<'preview' | 'content' | 'structure'>('preview');
const activeSlide = computed(() => normalizeSlideIndex(props.activeSlideIndex, slides.value.length));
const currentSlide = computed(() => slides.value[activeSlide.value] || null);
const semanticLines = computed(() => {
  if (!currentSlide.value) return [];
  const excluded = new Set([currentSlide.value.title, currentSlide.value.purpose].filter(Boolean));
  return visibleSemanticTexts(currentSlide.value).filter(line => !excluded.has(line));
});
const currentBlocks = computed(() => currentSlide.value?.blocks || []);
const currentElements = computed(() => currentSlide.value?.elements || []);
const currentRenderMode = computed(() => currentSlide.value ? inferSlideRenderMode(currentSlide.value) : 'semantic');

function handleSelectSlide(index: number, additive = false) {
  emit('select-slide', normalizeSlideIndex(index, slides.value.length), additive);
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
        <span v-if="draftSlideIndex !== undefined" class="draft-chip">正在生成第 {{ draftSlideIndex + 1 }} 页</span>
      </div>

      <div class="header-actions">
        <div class="view-mode-switch" role="tablist" aria-label="页面查看模式">
          <button v-for="mode in (['preview', 'content', 'structure'] as const)" :key="mode" type="button"
                  :class="{ active: viewMode === mode }" @click="viewMode = mode">
            {{ mode === 'preview' ? '预览' : mode === 'content' ? '内容' : '结构' }}
          </button>
        </div>
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
          :active-slide="activeSlide"
          :template="pptTheme"
          :modified-slides="modifiedSlides"
          :selected-slides="selectedSlides"
          @select-slide="handleSelectSlide"
        />
        <PPTPreviewStage
          v-if="viewMode === 'preview'"
          :slide="slides[activeSlide] || null"
          :slide-index="activeSlide"
          :total-slides="slides.length"
          :template="pptTheme"
          :is-running="isRunning"
          @change-slide="handleSelectSlide"
          @modify-slide="handleModifySlide"
        />
        <section v-else-if="viewMode === 'content'" class="slide-inspector">
          <span class="inspector-kicker">第 {{ activeSlide + 1 }} 页 · 页面内容</span>
          <h2>{{ currentSlide?.title || '未命名页面' }}</h2>
          <p v-if="currentSlide?.purpose" class="purpose">讲授目标：{{ currentSlide.purpose }}</p>
          <ul><li v-for="(line, index) in semanticLines" :key="index">{{ line }}</li></ul>
          <p v-if="currentSlide?.visual_suggestion" class="visual-note">视觉建议：{{ currentSlide.visual_suggestion }}</p>
        </section>
        <section v-else class="slide-inspector structure-inspector">
          <span class="inspector-kicker">第 {{ activeSlide + 1 }} 页 · 页面结构</span>
          <h2>{{ currentSlide?.title || '未命名页面' }}</h2>
          <p class="purpose">渲染模式：{{ currentRenderMode }}</p>
          <h3>语义层</h3>
          <div v-if="currentBlocks.length" class="element-list">
            <article v-for="(block, index) in currentBlocks" :key="index">
              <strong>{{ block.kind }}</strong>
              <span>{{ semanticLines[index] || '结构化教学内容' }}</span>
            </article>
          </div>
          <p v-else class="purpose">正文：{{ (currentSlide?.body || []).join('；') || '无' }}</p>
          <h3>视觉 / 几何层</h3>
          <div v-if="currentElements.length" class="element-list">
            <article v-for="(element, index) in currentElements" :key="element.id || index">
              <strong>{{ element.kind || 'element' }}</strong>
              <span>
                {{ element.role || element.text || '结构元素' }}
                <template v-if="element.content_ref"> · ref={{ element.content_ref }}</template>
                <template v-if="element.visual_slot"> · slot={{ element.visual_slot }}</template>
              </span>
            </article>
          </div>
          <p v-else class="purpose">当前页没有绝对定位视觉元素。</p>
        </section>
      </template>

      <div v-if="loading && !slides.length" class="preview-empty-state preview-restoring-state">
        <el-icon class="empty-icon is-loading"><Loading /></el-icon>
        <h3>正在恢复 PPT 课件</h3>
        <p>正在读取上一次正式版本与页面预览，恢复期间不会清空或覆盖已有课件。</p>
      </div>

      <div v-else-if="!slides.length" class="preview-empty-state">
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
.draft-chip { font-size: 11px; color: #4f46e5; background: #eef2ff; padding: 2px 8px; border-radius: 999px; }

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.view-mode-switch { display: inline-flex; padding: 2px; border-radius: 8px; background: #f1f5f9; }
.view-mode-switch button { border: 0; background: transparent; color: #64748b; font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 6px; cursor: pointer; }
.view-mode-switch button.active { color: #4338ca; background: #fff; box-shadow: 0 1px 3px rgba(15,23,42,.12); }
.slide-inspector { flex: 1; overflow: auto; padding: 36px clamp(28px, 7vw, 90px); background: #f8fafc; color: #1e293b; }
.slide-inspector h2 { margin: 10px 0 18px; font-size: 26px; }
.slide-inspector li { margin: 10px 0; line-height: 1.7; }
.inspector-kicker { color: #6366f1; font-size: 12px; font-weight: 800; }
.purpose, .visual-note { color: #64748b; line-height: 1.7; }
.element-list { display: grid; gap: 10px; }
.element-list article { display: flex; gap: 16px; padding: 12px 14px; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; }
.element-list strong { min-width: 100px; color: #4f46e5; }

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
