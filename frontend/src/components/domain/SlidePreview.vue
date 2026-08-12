<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { PPTSlide, PPTTemplate } from '../../types';
import { Refresh, Microphone } from '@element-plus/icons-vue';
import { api } from '../../api/client';
import { DEFAULT_PPT_TEMPLATE, pptTemplateStyle } from '../../utils/pptTemplate';
import { blockTexts, hybridSemanticWidth, inferSlideRenderMode, renderedLayoutElements } from '../../utils/slideRenderMode';

const props = defineProps<{
  slide: PPTSlide;
  slideIndex: number;
  totalSlides: number;
  template?: PPTTemplate | null;
  /** 紧凑渲染模式（例如侧边栏缩略图），隐藏底部控制栏和多余间距 */
  compact?: boolean;
}>();

const emit = defineEmits<{
  (e: 'regenerateSlide', slideIndex: number): void;
}>();

const PPT_CANVAS_WIDTH = 960;
const COMPACT_CANVAS_WIDTH = 108;
const canvasFrame = ref<HTMLElement | null>(null);
const canvasScale = ref(props.compact ? COMPACT_CANVAS_WIDTH / PPT_CANVAS_WIDTH : 1);
let resizeObserver: ResizeObserver | null = null;
const assetUrls = ref<Record<string, string>>({});
const failedAssets = ref<Record<string, boolean>>({});
let assetLoadEpoch = 0;

const activeTemplate = computed(() => props.template || DEFAULT_PPT_TEMPLATE);
const bullets = computed(() => props.slide.bullet_points?.length ? props.slide.bullet_points : props.slide.body || []);
const blocks = computed(() => props.slide.blocks || []);
const hasBlocks = computed(() => blocks.value.length > 0);
const supplementalBody = computed(() => {
  const represented = new Set(blocks.value.flatMap(block => blockTexts(block as unknown as Record<string, any>)).map(text => String(text).trim()));
  return bullets.value.filter(line => !represented.has(String(line).trim()));
});
const renderMode = computed(() => inferSlideRenderMode(props.slide));
const layoutElements = computed(() => renderedLayoutElements(props.slide));
const hasLayoutElements = computed(() => layoutElements.value.length > 0);
const shouldRenderSemantic = computed(() => renderMode.value !== 'absolute');
const semanticBodyStyle = computed(() => {
  const width = hybridSemanticWidth(props.slide, activeTemplate.value.id);
  return width ? { width: `${width}px` } : undefined;
});
const pageType = computed(() => props.slide.page_type || 'concept');
const slideLayout = computed(() => props.slide.layout || props.slide.layout_type || '');
const isCover = computed(() => pageType.value === 'cover' || ['title', 'cover'].includes(slideLayout.value));
const isProcess = computed(() => pageType.value === 'process' || slideLayout.value === 'steps');
const isSplit = computed(() => pageType.value === 'comparison' || slideLayout.value === 'split');
const isQa = computed(() => pageType.value === 'question' || pageType.value === 'exercise');
const coverSubtitle = computed(() => bullets.value.slice(0, 2).join(' · '));
const splitColumns = computed(() => {
  const half = Math.ceil(bullets.value.length / 2);
  return [bullets.value.slice(0, half), bullets.value.slice(half)];
});
const canvasClasses = computed(() => [
  `theme-${activeTemplate.value.composition}`,
  `theme-${activeTemplate.value.id}`,
  `page-${pageType.value}`,
  {
    'is-cover': isCover.value, 'is-process': isProcess.value, 'is-split': isSplit.value, 'is-qa': isQa.value,
    'is-hybrid': renderMode.value === 'hybrid',
  },
]);

const paletteVars: Record<string, string> = {
  primary: 'var(--ppt-primary)', secondary: 'var(--ppt-secondary)', text: 'var(--ppt-text)',
  muted: 'var(--ppt-muted)', background: 'var(--ppt-bg)', surface: 'var(--ppt-surface)',
  on_primary: 'var(--ppt-on-primary)',
};

function resolveColor(value: unknown, fallback = 'transparent') {
  if (typeof value !== 'string' || !value) return fallback;
  return paletteVars[value] || value;
}

function elementStyle(element: NonNullable<PPTSlide['elements']>[number]) {
  const style = (element.style || {}) as Record<string, unknown>;
  const isShape = element.kind === 'shape';
  return {
    left: `${Number(element.x || 0) * 72}px`,
    top: `${Number(element.y || 0) * 72}px`,
    width: `${Number(element.w || 0) * 72}px`,
    height: `${Number(element.h || 0) * 72}px`,
    color: resolveColor(style.color, 'var(--ppt-text)'),
    background: isShape ? resolveColor(element.fill, 'transparent') : 'transparent',
    borderColor: resolveColor(element.line, 'transparent'),
    borderRadius: element.shape_type === 'rounded' ? '12px' : element.shape_type === 'oval' ? '999px' : '0',
    fontSize: `${Number(style.size || 18)}px`,
    fontWeight: style.bold ? '800' : '400',
    textAlign: String(style.align || 'left') as 'left' | 'center' | 'right',
    fontFamily: String(style.font || 'var(--ppt-body-font)'),
    zIndex: Number(element.z ?? 0),
  };
}

const imageAssetIds = computed(() => Array.from(new Set(
  layoutElements.value
    .filter(element => element.kind === 'image' && element.asset_id)
    .map(element => String(element.asset_id)),
)));

function elementImageUrl(element: NonNullable<PPTSlide['elements']>[number]) {
  return element.asset_id ? assetUrls.value[element.asset_id] || '' : '';
}

function markImageFailed(element: NonNullable<PPTSlide['elements']>[number]) {
  if (element.asset_id) failedAssets.value[element.asset_id] = true;
}

watch(imageAssetIds, async ids => {
  const epoch = ++assetLoadEpoch;
  await Promise.all(ids.map(async id => {
    if (assetUrls.value[id] || failedAssets.value[id]) return;
    try {
      const response = await api.get(`/artifact-assets/${id}`, { responseType: 'blob' });
      if (epoch !== assetLoadEpoch) return;
      assetUrls.value[id] = URL.createObjectURL(response.data);
    } catch {
      if (epoch === assetLoadEpoch) failedAssets.value[id] = true;
    }
  }));
}, { immediate: true });

function syncCanvasScale(width: number) {
  if (width > 0) canvasScale.value = width / PPT_CANVAS_WIDTH;
}

onMounted(() => {
  // Filmstrip thumbnails have a fixed width. Creating one ResizeObserver per
  // slide caused the whole workspace to repeatedly reflow during task polling.
  if (props.compact) return;
  if (!canvasFrame.value) return;
  syncCanvasScale(canvasFrame.value.clientWidth);
  resizeObserver = new ResizeObserver(([entry]) => {
    if (entry) syncCanvasScale(entry.contentRect.width);
  });
  resizeObserver.observe(canvasFrame.value);
});

onBeforeUnmount(() => {
  assetLoadEpoch += 1;
  resizeObserver?.disconnect();
  Object.values(assetUrls.value).forEach(url => URL.revokeObjectURL(url));
});
</script>

<template>
  <div class="slide-preview-container animate-fade-in" :class="{ compact }" :style="pptTemplateStyle(activeTemplate)">
    <div ref="canvasFrame" class="ppt-canvas-frame">
      <div class="ppt-canvas" :class="canvasClasses" :style="{ transform: `scale(${canvasScale})` }">
        <!-- 1. 模板装饰形状（对齐 pptx_renderer._decorate） -->
        <div class="ppt-decoration" aria-hidden="true">
          <i class="dec-main" /><i class="dec-accent" /><i class="dec-dot" /><i class="dec-ticks" />
        </div>

        <!-- 2. 页眉页码 -->
        <span class="ppt-folio">{{ String(slideIndex + 1).padStart(2, '0') }}</span>

        <!-- 3. LLM 生成的可执行布局；旧 Artifact 无元素几何时回退到语义版式。 -->
        <div v-if="hasLayoutElements" class="agentic-layout" :class="{ 'is-hybrid-layout': renderMode === 'hybrid' }">
          <div
            v-for="(element, index) in layoutElements"
            :key="element.id || `${element.role || element.kind}-${index}`"
            class="agentic-element"
            :class="[`kind-${element.kind}`, `role-${element.role || 'content'}`]"
            :style="elementStyle(element)"
          >
            <span v-if="element.kind === 'textbox'">{{ element.text }}</span>
            <template v-else-if="element.kind === 'image'">
              <img
                v-if="elementImageUrl(element) && !failedAssets[element.asset_id || '']"
                class="visual-element-image"
                :src="elementImageUrl(element)"
                :alt="element.role || 'PPT 页面配图'"
                @error="markImageFailed(element)"
              >
              <span v-else class="visual-element-label">
                {{ failedAssets[element.asset_id || ''] ? '配图加载失败' : '配图准备中' }}
              </span>
              <span v-if="element.degraded" class="visual-degraded-badge">替代图</span>
            </template>
            <span v-else-if="element.kind === 'chart'" class="visual-element-label">数据图表</span>
          </div>
        </div>

        <div v-if="shouldRenderSemantic" class="ppt-body" :style="semanticBodyStyle">
          <h2 class="slide-title">{{ slide.title || '无标题幻灯片' }}</h2>

          <template v-if="isCover">
            <p v-if="coverSubtitle" class="cover-subtitle">{{ coverSubtitle }}</p>
            <p v-if="slide.purpose" class="cover-purpose">{{ slide.purpose }}</p>
            <span v-if="isCover" class="ppt-brand">LESSONFORGE</span>
          </template>

          <div v-else-if="hasBlocks" class="blocks-area">
            <ul v-if="supplementalBody.length" class="block-bullets supplemental-body">
              <li v-for="(line, index) in supplementalBody" :key="`body-${index}`">{{ line }}</li>
            </ul>
            <div v-for="(block, bIdx) in blocks" :key="bIdx" :class="`block-${block.kind}`" class="ppt-block">
              <template v-if="block.kind === 'lead'">
                <p class="block-lead">{{ block.text }}</p>
                <p v-if="block.sub" class="block-sub">{{ block.sub }}</p>
              </template>

              <ul v-else-if="block.kind === 'bullets'" class="block-bullets" :class="{ numbered: block.numbered }">
                <li v-for="(item, i) in block.items" :key="i" :class="{ 'is-emphasis': item.emphasize }">{{ item.text }}</li>
              </ul>

              <div v-else-if="block.kind === 'steps'" class="block-steps">
                <div v-for="(step, i) in block.steps" :key="i" class="block-step">
                  <span class="step-num">{{ String(i + 1).padStart(2, '0') }}</span>
                  <i class="step-rule" />
                  <p class="step-title">{{ step.title }}</p>
                  <p v-if="step.detail" class="step-detail">{{ step.detail }}</p>
                </div>
              </div>

              <div v-else-if="block.kind === 'compare'" class="block-compare">
                <div class="compare-col">
                  <p v-if="block.left.heading" class="compare-heading">{{ block.left.heading }}</p>
                  <p v-for="(t, i) in block.left.items" :key="i" class="compare-item">{{ t }}</p>
                </div>
                <div class="compare-col is-second">
                  <p v-if="block.right.heading" class="compare-heading">{{ block.right.heading }}</p>
                  <p v-for="(t, i) in block.right.items" :key="i" class="compare-item">{{ t }}</p>
                </div>
              </div>

              <blockquote v-else-if="block.kind === 'quote'" class="block-quote">
                <p class="quote-text">{{ block.text }}</p>
                <cite v-if="block.citation">{{ block.citation }}</cite>
              </blockquote>

              <div v-else-if="block.kind === 'visual'" class="block-visual">
                <p class="visual-label">图示占位：{{ block.diagram || 'visual' }}</p>
                <p v-if="block.caption" class="visual-caption">{{ block.caption }}</p>
              </div>

              <p v-else-if="block.kind === 'note'" class="block-note">{{ block.text }}</p>
            </div>
          </div>

          <div v-else-if="isProcess" class="process-layout">
            <div v-for="(bullet, bIdx) in bullets.slice(0, 4)" :key="bIdx" class="process-step">
              <span class="step-num">{{ String(bIdx + 1).padStart(2, '0') }}</span>
              <i class="step-rule" />
              <p>{{ bullet }}</p>
            </div>
          </div>

          <div v-else-if="isQa" class="qa-box">
            <div v-for="(bullet, bIdx) in bullets.slice(0, 4)" :key="bIdx" class="qa-row">
              <span class="qa-badge">{{ bIdx + 1 }}</span>
              <p>{{ bullet }}</p>
            </div>
          </div>

          <div v-else-if="isSplit" class="split-layout">
            <div v-for="(column, cIdx) in splitColumns" :key="cIdx" class="split-column" :class="{ 'is-second': cIdx === 1 }">
              <p v-for="(bullet, bIdx) in column" :key="bIdx">{{ bullet }}</p>
            </div>
          </div>

          <ul v-else class="slide-bullets-area">
            <li v-for="(bullet, bIdx) in bullets" :key="bIdx">{{ bullet }}</li>
          </ul>
        </div>

        <!-- 4. 配图建议条 -->
        <div v-if="slide.visual_suggestion && !isCover && renderMode !== 'absolute'" class="ppt-visual-hint">{{ slide.visual_suggestion }}</div>

        <!-- 5. 页脚页码 -->
        <span class="ppt-footer">{{ slideIndex + 1 }} / {{ totalSlides }}</span>
      </div>
    </div>

    <div v-if="!compact" class="ppt-footer-panel">
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
.slide-preview-container.compact { gap: 0; }
.slide-preview-container.compact .ppt-footer-panel { display: none; }
.ppt-canvas-frame { width: 100%; aspect-ratio: 16 / 9; position: relative; overflow: hidden; background: var(--ppt-bg); }
.ppt-canvas {
  width: 960px; height: 540px; box-sizing: border-box; position: absolute; inset: 0 auto auto 0;
  overflow: hidden; transform-origin: top left; will-change: transform;
  background: var(--ppt-bg); color: var(--ppt-text); font-family: var(--ppt-body-font);
}
.agentic-layout { position: absolute; inset: 0; z-index: 2; }
.agentic-layout.is-hybrid-layout { z-index: 2; pointer-events: none; }
.agentic-element { position: absolute; box-sizing: border-box; overflow: hidden; white-space: pre-wrap; line-height: 1.25; }
.agentic-element.kind-shape { border-width: 1px; border-style: solid; }
.agentic-element.kind-image,
.agentic-element.kind-chart { display: flex; align-items: center; justify-content: center; border: 1px dashed var(--ppt-secondary); background: var(--ppt-surface); color: var(--ppt-muted); }
.agentic-element.kind-image { border-style: solid; }
.visual-element-image { width: 100%; height: 100%; display: block; object-fit: cover; }
.visual-element-label { font: 700 13px/1 var(--ppt-body-font); letter-spacing: .08em; }
.visual-degraded-badge {
  position: absolute; right: 8px; bottom: 8px; padding: 4px 7px; border-radius: 999px;
  background: rgb(15 23 42 / .78); color: #fff; font: 600 10px/1 var(--ppt-body-font);
}

/* 1. 模板装饰形状（对齐 pptx_renderer._decorate，坐标按 72px/英寸换算） */
.ppt-decoration { position: absolute; inset: 0; pointer-events: none; z-index: 1; }
.ppt-decoration i { position: absolute; display: block; }

.theme-swiss_rail .dec-main { left: 39.6px; top: 39.6px; width: 5.8px; height: 459.4px; background: var(--ppt-primary); }
.theme-swiss_rail .dec-accent { left: 129.6px; top: 39.6px; width: 781.2px; height: 1.5px; background: var(--ppt-secondary); }

.theme-nordic_field .dec-dot { left: 802.8px; top: 13px; width: 133.2px; height: 133.2px; border-radius: 50%; background: var(--ppt-secondary); }
.theme-nordic_field .dec-main { left: 50.4px; bottom: 14px; width: 223.2px; height: 5.8px; background: var(--ppt-primary); }

.theme-academic_offset .dec-main { left: 0; top: 0; width: 144px; height: 540px; background: var(--ppt-primary); }
.theme-academic_offset .dec-accent { left: 144px; top: 0; width: 8.6px; height: 540px; background: var(--ppt-secondary); }

.theme-editorial_margin .dec-main { left: 51.8px; top: 46.8px; width: 2.2px; height: 442.8px; background: var(--ppt-primary); }
.theme-editorial_margin .dec-accent { left: 72px; top: 95px; width: 831.6px; height: 1.5px; background: var(--ppt-secondary); }
.theme-editorial_margin .dec-dot { left: 72px; top: 476.6px; width: 831.6px; height: 1.5px; background: var(--ppt-secondary); }

.theme-science_signal .dec-main { left: 0; top: 0; width: 960px; height: 8px; background: var(--ppt-primary); }
.theme-science_signal .dec-accent { left: 51.8px; top: 49px; width: 4.3px; height: 428.4px; background: var(--ppt-primary); }
.theme-science_signal .dec-ticks { left: 655.2px; top: 493.2px; width: 30.2px; height: 2.5px; background: var(--ppt-secondary); box-shadow: 50.4px 0 0 var(--ppt-secondary), 100.8px 0 0 var(--ppt-secondary), 151.2px 0 0 var(--ppt-secondary), 201.6px 0 0 var(--ppt-secondary); }

.theme-primary_blocks .dec-dot { left: 5.8px; top: 5.8px; width: 85px; height: 85px; border-radius: 50%; background: var(--ppt-secondary); }
.theme-primary_blocks .dec-main { left: 877px; top: 459.4px; width: 64.8px; height: 64.8px; border-radius: 50%; background: var(--ppt-primary); }

/* 成品 deck 模板：内容填入真实 PPT 版式，页面内用简洁的品牌条与角标做预览 */
.theme-deck .dec-main { left: 0; top: 0; width: 960px; height: 6px; background: var(--ppt-primary); }
.theme-deck .dec-accent { left: 45px; top: 45px; width: 6px; height: 104px; background: var(--ppt-secondary); }
.theme-deck .dec-dot { right: 45px; bottom: 45px; width: 86px; height: 86px; border-radius: 50%; background: var(--ppt-secondary); }

/* ===== 6 套成品模板的独立预览版式：内容区域/标题/封面按模板明显不同 ===== */

/* 学术科研：左侧主色竖栏，正文右移单列 */
.theme-lessonforge_deck_academic .dec-main { left: 0; top: 0; width: 13px; height: 540px; background: var(--ppt-primary); }
.theme-lessonforge_deck_academic .dec-accent { left: 13px; top: 0; width: 3px; height: 540px; background: var(--ppt-secondary); }
.theme-lessonforge_deck_academic .ppt-body { left: 158px; width: 720px; }
/* 页码放在正文栏左侧的安全边距内，避免与标题（content_ref=title，起始 x≈2.2in）重叠 */
.theme-lessonforge_deck_academic .ppt-folio { left: 27px; }
.theme-lessonforge_deck_academic .ppt-visual-hint { left: 158px; width: 720px; }
.theme-lessonforge_deck_academic.is-cover .slide-title { top: 210px; }
.theme-lessonforge_deck_academic.is-cover .cover-subtitle { top: 320px; }

/* AI 未来：顶部霓虹条，内容 2×2 卡片网格 */
.theme-lessonforge_deck_ai_future .dec-main { left: 0; top: 0; width: 960px; height: 5px; background: var(--ppt-primary); }
.theme-lessonforge_deck_ai_future .dec-accent { right: 40px; top: 28px; width: 26px; height: 26px; border-radius: 50%; background: var(--ppt-secondary); }
.theme-lessonforge_deck_ai_future .ppt-body { left: 76px; width: 820px; }
.theme-lessonforge_deck_ai_future .slide-title { top: 62px; }
.theme-lessonforge_deck_ai_future .slide-bullets-area,
.theme-lessonforge_deck_ai_future .block-bullets {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-content: start;
}
.theme-lessonforge_deck_ai_future .slide-bullets-area li,
.theme-lessonforge_deck_ai_future .block-bullets li {
  margin: 0; padding: 14px 16px; border-radius: 12px; background: var(--ppt-surface);
  border: 1px solid var(--ppt-secondary);
}
.theme-lessonforge_deck_ai_future .slide-bullets-area li::before,
.theme-lessonforge_deck_ai_future .block-bullets li::before { content: none; }
.theme-lessonforge_deck_ai_future.is-cover .slide-title { top: 240px; font-size: 46px; }
.theme-lessonforge_deck_ai_future.is-cover .cover-subtitle { top: 360px; }

/* 商务培训：顶部强调条，内容双栏 */
.theme-lessonforge_deck_business .dec-main { left: 0; top: 0; width: 960px; height: 7px; background: var(--ppt-primary); }
.theme-lessonforge_deck_business .dec-accent { left: 88px; bottom: 40px; width: 780px; height: 2px; background: var(--ppt-secondary); }
.theme-lessonforge_deck_business .ppt-body { left: 88px; width: 800px; }
.theme-lessonforge_deck_business .slide-bullets-area,
.theme-lessonforge_deck_business .block-bullets {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px 40px; align-content: start;
}
.theme-lessonforge_deck_business .slide-bullets-area li,
.theme-lessonforge_deck_business .block-bullets li { margin: 0; padding-left: 22px; }
.theme-lessonforge_deck_business.is-cover .slide-title { top: 220px; font-size: 48px; }
.theme-lessonforge_deck_business.is-cover .cover-subtitle { top: 340px; }

/* 卡通启蒙：徽章标题 + 圆角徽章卡片 */
.theme-lessonforge_deck_cartoon .dec-dot { right: 34px; top: 28px; width: 26px; height: 26px; border-radius: 50%; background: var(--ppt-secondary); box-shadow: -40px 0 0 var(--ppt-primary); }
.theme-lessonforge_deck_cartoon .ppt-body { left: 88px; width: 800px; }
.theme-lessonforge_deck_cartoon .slide-title {
  display: inline-block; max-width: 100%; top: 56px;
  padding: 10px 24px; border-radius: 999px; background: var(--ppt-primary); color: var(--ppt-on-primary);
}
.theme-lessonforge_deck_cartoon .slide-bullets-area,
.theme-lessonforge_deck_cartoon .block-bullets {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-content: start;
}
.theme-lessonforge_deck_cartoon .slide-bullets-area li,
.theme-lessonforge_deck_cartoon .block-bullets li {
  margin: 0; padding: 12px 16px; border-radius: 14px; background: var(--ppt-surface);
  border: 1px solid var(--ppt-secondary);
}
.theme-lessonforge_deck_cartoon .slide-bullets-area li::before,
.theme-lessonforge_deck_cartoon .block-bullets li::before { content: none; }
.theme-lessonforge_deck_cartoon.is-cover .slide-title { top: 210px; font-size: 42px; }
.theme-lessonforge_deck_cartoon.is-cover .cover-subtitle { top: 330px; }

/* 中国文化：纸墨竖排，居中标题与内容 */
.theme-lessonforge_deck_chinese_culture .dec-main { left: 0; top: 0; width: 11px; height: 540px; background: var(--ppt-primary); }
.theme-lessonforge_deck_chinese_culture .dec-accent { left: 11px; top: 0; width: 3px; height: 540px; background: var(--ppt-secondary); }
.theme-lessonforge_deck_chinese_culture .ppt-body { left: 0; width: 960px; }
.theme-lessonforge_deck_chinese_culture .slide-title { left: 0; width: 100%; text-align: center; top: 72px; }
.theme-lessonforge_deck_chinese_culture .slide-bullets-area { left: 120px; width: 720px; top: 170px; text-align: center; }
.theme-lessonforge_deck_chinese_culture .slide-bullets-area li { padding-left: 0; }
.theme-lessonforge_deck_chinese_culture .slide-bullets-area li::before { content: none; }
.theme-lessonforge_deck_chinese_culture .blocks-area { left: 120px; width: 720px; top: 160px; }
.theme-lessonforge_deck_chinese_culture .ppt-visual-hint { left: 120px; width: 720px; }
.theme-lessonforge_deck_chinese_culture.is-cover .slide-title { top: 210px; text-align: center; }
.theme-lessonforge_deck_chinese_culture.is-cover .cover-subtitle { top: 330px; text-align: center; }

/* 智慧课堂：紫色渐变侧栏，内容右移双栏 */
.theme-lessonforge_deck_smart_ai .dec-main { left: 0; top: 0; width: 112px; height: 540px; background: var(--ppt-primary); }
.theme-lessonforge_deck_smart_ai .dec-accent { left: 112px; top: 0; width: 4px; height: 540px; background: var(--ppt-secondary); }
.theme-lessonforge_deck_smart_ai .ppt-body { left: 176px; width: 716px; }
.theme-lessonforge_deck_smart_ai .ppt-visual-hint { left: 176px; width: 716px; }
/* 页码移到左侧主色栏上（与品牌位置一致），避免与正文栏标题（起始 x=2.45in）重叠 */
.theme-lessonforge_deck_smart_ai .ppt-folio { left: 34px; color: var(--ppt-on-primary); }
.theme-lessonforge_deck_smart_ai .slide-bullets-area,
.theme-lessonforge_deck_smart_ai .block-bullets {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px 30px; align-content: start;
}
.theme-lessonforge_deck_smart_ai .slide-bullets-area li,
.theme-lessonforge_deck_smart_ai .block-bullets li { margin: 0; padding-left: 20px; }
.theme-lessonforge_deck_smart_ai .ppt-brand { display: block; position: absolute; left: 34px; top: 520px; font: 800 9px/1 var(--ppt-latin-font); color: var(--ppt-on-primary); z-index: 3; }
.theme-lessonforge_deck_smart_ai.is-cover .slide-title { left: 176px; top: 220px; }
.theme-lessonforge_deck_smart_ai.is-cover .cover-subtitle { left: 176px; top: 340px; }
.theme-lessonforge_deck_smart_ai.is-cover .cover-purpose { left: 176px; top: 440px; }

/* 各模板封面 title 下移后，purpose 同步下移避免重叠 */
.theme-lessonforge_deck_academic.is-cover .cover-purpose { top: 400px; }
.theme-lessonforge_deck_ai_future.is-cover .cover-purpose { top: 450px; }
.theme-lessonforge_deck_business.is-cover .cover-purpose { top: 430px; }
.theme-lessonforge_deck_cartoon.is-cover .cover-purpose { top: 420px; }
.theme-lessonforge_deck_chinese_culture.is-cover .cover-purpose { top: 420px; }

/* 2. 页眉页码 */
.ppt-folio { position: absolute; left: 59px; top: 44.6px; font: 800 16px/1 var(--ppt-latin-font); color: var(--ppt-primary); z-index: 3; }
.theme-academic_offset .ppt-folio { left: 27.4px; color: var(--ppt-on-primary); }
.theme-primary_blocks .ppt-folio { left: 31.7px; color: var(--ppt-on-primary); }

/* 3. 页面主体 */
.ppt-body { position: absolute; left: 97.2px; top: 0; width: 763.2px; height: 540px; z-index: 2; }
.theme-academic_offset .ppt-body { left: 183.6px; width: 698.4px; }

.slide-title { position: absolute; top: 66px; left: 0; width: 100%; margin: 0; font: 800 34px/1.15 var(--ppt-heading-font); color: var(--ppt-text); }

.is-cover .slide-title { top: 157px; font-size: 42px; }
.cover-subtitle { position: absolute; top: 246.2px; left: 0; width: 100%; margin: 0; font: 400 22px/1.3 var(--ppt-body-font); color: var(--ppt-muted); }
.cover-purpose { position: absolute; top: 404.6px; left: 0; margin: 0; font: 700 16px/1.3 var(--ppt-body-font); color: var(--ppt-primary); }

.ppt-brand { display: none; }
.theme-academic_offset .ppt-brand { display: block; position: absolute; left: 28px; top: 428px; font: 800 10px/1 var(--ppt-latin-font); letter-spacing: .04em; color: var(--ppt-on-primary); z-index: 3; }

/* 流程步骤卡片 */
.process-layout { position: absolute; top: 152.6px; left: 0; width: 100%; display: flex; gap: 15.8px; }
.process-step { flex: 1; min-width: 0; }
.process-step .step-num { font: 800 26px/1 var(--ppt-latin-font); color: var(--ppt-primary); }
.process-step .step-rule { display: block; height: 2.9px; margin: 13px 0 12px; background: var(--ppt-secondary); }
.process-step p { margin: 0; font: 700 20px/1.4 var(--ppt-body-font); color: var(--ppt-text); }

/* 问答/练习徽章框 */
.qa-box { position: absolute; top: 144px; left: 0; width: 100%; height: 273.6px; box-sizing: border-box; border-radius: 12px; background: var(--ppt-surface); border: 1px solid var(--ppt-secondary); padding: 25.2px 24px 0; }
.qa-row { display: flex; align-items: center; gap: 16px; margin-bottom: 26px; }
.qa-badge { flex: none; width: 30.2px; height: 30.2px; border-radius: 50%; background: var(--ppt-primary); color: var(--ppt-on-primary); display: flex; align-items: center; justify-content: center; font: 800 15px/1 var(--ppt-latin-font); }
.qa-row p { margin: 0; font: 400 20px/1.3 var(--ppt-body-font); color: var(--ppt-text); }

/* 对比分栏 */
.split-layout { position: absolute; top: 149.8px; left: 0; width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 21.6px; }
.split-column { min-width: 0; }
.split-column::before { content: ''; display: block; height: 4.3px; background: var(--ppt-primary); margin-bottom: 24px; }
.split-column.is-second::before { background: var(--ppt-secondary); }
.split-column p { margin: 0 0 20px; font: 400 20px/1.35 var(--ppt-body-font); color: var(--ppt-text); }

/* 标准要点列表 */
.slide-bullets-area { position: absolute; top: 144px; left: 0; width: 100%; margin: 0; padding: 0; list-style: none; }
.slide-bullets-area li { position: relative; padding-left: 24px; margin-bottom: 15px; font: 400 21px/1.4 var(--ppt-body-font); color: var(--ppt-text); }
.slide-bullets-area li::before { content: '•'; position: absolute; left: 0; color: var(--ppt-text); }

/* 3b. 结构化内容块（blocks）设计系统 */
.blocks-area { position: absolute; top: 144px; left: 0; width: 100%; display: flex; flex-direction: column; gap: 20px; overflow: hidden; }
.ppt-block { min-width: 0; }

.block-lead { margin: 0; font: 700 24px/1.4 var(--ppt-body-font); color: var(--ppt-primary); }
.block-sub { margin: 4px 0 0; font: 400 16px/1.4 var(--ppt-body-font); color: var(--ppt-muted); }

.block-bullets { margin: 0; padding: 0; list-style: none; }
.block-bullets li { position: relative; padding-left: 24px; margin-bottom: 12px; font: 400 20px/1.4 var(--ppt-body-font); color: var(--ppt-text); }
.block-bullets li::before { content: '•'; position: absolute; left: 0; color: var(--ppt-text); }
.block-bullets.numbered li { list-style: decimal; padding-left: 4px; margin-left: 24px; }
.block-bullets.numbered li::before { content: none; }
.block-bullets li.is-emphasis { font-weight: 700; color: var(--ppt-primary); }

.block-steps { display: flex; gap: 16px; }
.block-step { flex: 1; min-width: 0; }
.block-step .step-num { font: 800 26px/1 var(--ppt-latin-font); color: var(--ppt-primary); }
.block-step .step-rule { display: block; height: 3px; margin: 12px 0 10px; background: var(--ppt-secondary); }
.block-step .step-title { margin: 0 0 4px; font: 700 20px/1.4 var(--ppt-body-font); color: var(--ppt-text); }
.block-step .step-detail { margin: 0; font: 400 14px/1.5 var(--ppt-body-font); color: var(--ppt-muted); }

.block-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }
.compare-col { min-width: 0; }
.compare-col::before { content: ''; display: block; height: 4px; background: var(--ppt-primary); margin-bottom: 14px; }
.compare-col.is-second::before { background: var(--ppt-secondary); }
.compare-heading { margin: 0 0 8px; font: 700 18px/1.3 var(--ppt-body-font); color: var(--ppt-primary); }
.compare-item { margin: 0 0 10px; font: 400 20px/1.35 var(--ppt-body-font); color: var(--ppt-text); }

.block-quote { margin: 0; padding: 4px 0 4px 18px; border-left: 4px solid var(--ppt-primary); }
.block-quote .quote-text { margin: 0 0 4px; font: 500 22px/1.45 var(--ppt-body-font); color: var(--ppt-text); }
.block-quote cite { font: 400 13px/1.4 var(--ppt-body-font); color: var(--ppt-muted); font-style: normal; }

.block-visual { padding: 16px 18px; border: 2px dashed var(--ppt-secondary); border-radius: 10px; background: var(--ppt-surface); }
.visual-label { margin: 0 0 4px; font: 700 16px/1.4 var(--ppt-body-font); color: var(--ppt-primary); }
.visual-caption { margin: 0; font: 400 13px/1.4 var(--ppt-body-font); color: var(--ppt-muted); }

.block-note { margin: 0; font: 400 13px/1.4 var(--ppt-body-font); color: var(--ppt-muted); }

/* 4. 配图建议条 */
.ppt-visual-hint { position: absolute; left: 97.2px; top: 443.5px; width: 763.2px; height: 36px; box-sizing: border-box; display: flex; align-items: center; padding: 0 11.5px; background: var(--ppt-surface); font: 400 10px/1 var(--ppt-body-font); color: var(--ppt-muted); z-index: 2; }
.theme-academic_offset .ppt-visual-hint { left: 183.6px; width: 698.4px; }

/* 5. 页脚页码 */
.ppt-footer { position: absolute; right: 71px; bottom: 13px; font: 400 9px/1 var(--ppt-latin-font); color: var(--ppt-muted); z-index: 3; }
.theme-primary_blocks .ppt-footer { right: 103px; }

/* 底部教师讲解备注面板 */
.ppt-footer-panel { background: var(--bg-surface); border: 1px solid var(--border-default); padding: 20px; }
.notes-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.notes-title { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; color: #002fa7; }
.notes-content { margin: 0; font-size: 14px; line-height: 1.6; color: var(--text-secondary); }
</style>
