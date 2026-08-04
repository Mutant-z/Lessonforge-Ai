<script setup lang="ts">
import { computed } from 'vue';
import type { PPTSlide, PPTBlock, PPTTemplate } from '../../types';
import { DEFAULT_PPT_TEMPLATE, pptTemplateStyle } from '../../utils/pptTemplate';

const props = defineProps<{
  slide: PPTSlide;
  index: number;
  isActive: boolean;
  template?: PPTTemplate | null;
}>();

const emit = defineEmits<{ (e: 'select', index: number): void }>();

const activeTemplate = computed(() => props.template || DEFAULT_PPT_TEMPLATE);
const bullets = computed(() => props.slide.bullet_points || props.slide.body || []);
const coverSubtitle = computed(() => bullets.value.slice(0, 2).join(' · '));
const pageType = computed(() => props.slide.page_type || 'concept');
const slideLayout = computed(() => props.slide.layout || props.slide.layout_type || '');
const isCover = computed(() => pageType.value === 'cover' || ['title', 'cover'].includes(slideLayout.value));
const isProcess = computed(() => pageType.value === 'process' || slideLayout.value === 'steps');
const isSplit = computed(() => pageType.value === 'comparison' || slideLayout.value === 'split');
function blockPreviewText(blocks: PPTBlock[]): string[] {
  const out: string[] = [];
  for (const block of blocks) {
    switch (block.kind) {
      case 'lead': out.push(block.text); break;
      case 'bullets': out.push(...block.items.slice(0, 2).map((item) => item.text)); break;
      case 'steps': out.push(...block.steps.slice(0, 2).map((step) => step.title)); break;
      case 'compare': out.push(block.left.items[0] || ''); out.push(block.right.items[0] || ''); break;
      case 'quote': out.push(block.text); break;
      case 'visual': out.push(`图示：${block.diagram || 'visual'}`); break;
      case 'note': break;
    }
  }
  return out.filter(Boolean).slice(0, 2);
}

const previewBullets = computed(() => {
  const structured = props.slide.blocks || [];
  if (structured.length) {
    return blockPreviewText(structured);
  }
  if (isSplit.value) {
    const half = Math.ceil(bullets.value.length / 2);
    return half > 0 ? [bullets.value[0], bullets.value[half]].filter(Boolean) : [];
  }
  return bullets.value.slice(0, 2);
});
</script>

<template>
  <button
    type="button"
    class="slide-thumbnail-card"
    :class="[{ active: isActive }, `theme-${activeTemplate.composition}`]"
    :style="pptTemplateStyle(activeTemplate)"
    :aria-label="`第 ${index + 1} 页：${slide.title || '无标题'}`"
    @click="emit('select', index)"
  >
    <div class="thumb-aspect">
      <!-- 1. 顶部页码 -->
      <span class="thumb-num">P{{ slide.slide_number || index + 1 }}</span>
      
      <!-- 2. 中间卡片真实内容容器 -->
      <div class="thumb-content" :class="{ 'is-cover': isCover }">
        <!-- 标题 -->
        <div class="thumb-title">{{ slide.title || '无标题幻灯片' }}</div>

        <!-- 封面：学科·学段副标题 + purpose（与主视窗/真实导出一致） -->
        <template v-if="isCover">
          <p v-if="coverSubtitle" class="thumb-subtitle">{{ coverSubtitle }}</p>
          <p v-else-if="slide.purpose" class="thumb-subtitle">{{ slide.purpose }}</p>
          <p v-if="slide.purpose && coverSubtitle" class="thumb-purpose">{{ slide.purpose }}</p>
        </template>

        <!-- 其余页型：对比页每栏取一条、流程页带编号，其余取前 2 条 -->
        <ul v-else-if="previewBullets.length" class="thumb-bullets">
          <li v-for="(bullet, bIdx) in previewBullets" :key="bIdx">
            <span v-if="isProcess" class="step-no">{{ String(bIdx + 1).padStart(2, '0') }}</span>
            {{ bullet }}
          </li>
        </ul>
      </div>
    </div>
  </button>
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
}

.slide-thumbnail-card:hover {
  border-color: var(--border-active, #818cf8);
  transform: translateY(-1px);
}

.slide-thumbnail-card.active {
  border-color: var(--color-primary, #4f46e5);
  box-shadow: 0 0 0 1px var(--color-primary, #4f46e5);
}

/* 建立标准 16:9 卡片容器 */
.thumb-aspect {
  width: 100%;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: var(--ppt-bg, #ffffff);
  color: var(--ppt-text, #0f172a);
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 8px 10px;
  box-sizing: border-box;
  border: 1px solid color-mix(in srgb, var(--ppt-muted, #94a3b8) 28%, transparent);
  border-radius: 4px;
}

/* 页码角标 */
.thumb-num {
  position: absolute;
  top: 5px;
  right: 6px;
  font: 800 9px/1 var(--ppt-latin-font, sans-serif);
  color: var(--ppt-primary, #4f46e5);
  background: color-mix(in srgb, var(--ppt-primary, #4f46e5) 12%, transparent);
  padding: 2px 4px;
  border-radius: 3px;
  z-index: 2;
}

/* 内容布局区 */
.thumb-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
  padding-right: 20px; /* 留出页码空间 */
}

/* 标题样式：最高展示 2 行，超长溢出省略 */
.thumb-title {
  font-family: var(--ppt-heading-font, sans-serif);
  font-size: 11px;
  line-height: 1.25;
  font-weight: 800;
  color: var(--ppt-text, #0f172a);
  margin-bottom: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-all;
}

/* 真实要点列表：用真正的文字渲染 */
.thumb-bullets {
  margin: 0;
  padding: 0 0 0 10px;
  list-style-type: disc;
}

.thumb-bullets li {
  font-size: 9px;
  line-height: 1.2;
  color: var(--ppt-text, #334155);
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0.85;
}

.thumb-bullets li::marker {
  color: var(--ppt-primary, #4f46e5);
  font-size: 8px;
}

.thumb-purpose {
  font-size: 9px;
  line-height: 1.2;
  color: var(--ppt-primary, #4f46e5);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 封面副标题（与主视窗 .cover-purpose 对应） */
.thumb-subtitle {
  font-size: 8px;
  line-height: 1.3;
  color: var(--ppt-primary, #4f46e5);
  font-weight: 600;
  margin: 0 0 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.thumb-content.is-cover .thumb-title {
  font-size: 13px;
}

/* 流程页步骤编号（与主视窗编号卡片对应） */
.step-no {
  display: inline-block;
  font: 800 8px/1 var(--ppt-latin-font, sans-serif);
  color: var(--ppt-primary, #4f46e5);
  margin-right: 4px;
}

/* 兼容各主题的修饰边框样式 */
.theme-swiss_rail .thumb-aspect { border-top: 4px solid var(--ppt-primary); }
.theme-nordic_field .thumb-aspect { border-radius: 6px; }
.theme-academic_offset .thumb-aspect { border-left: 14px solid var(--ppt-primary); }
.theme-academic_offset .thumb-num { right: auto; left: -10px; color: var(--ppt-on-primary); background: transparent; }
.theme-editorial_margin .thumb-aspect { outline: 1px solid var(--ppt-secondary); outline-offset: -4px; }
.theme-science_signal .thumb-aspect { border-top: 3px solid var(--ppt-primary); }
.theme-primary_blocks .thumb-aspect { border-radius: 6px; }
</style>
