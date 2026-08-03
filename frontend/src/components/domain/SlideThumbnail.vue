<script setup lang="ts">
import { computed } from 'vue';
import type { PPTSlide, PPTTemplate } from '../../types';
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
      <span class="thumb-num">{{ index + 1 }}</span>
      <div class="thumb-copy">
        <div class="thumb-title">{{ slide.title || '无标题幻灯片' }}</div>
        <i v-for="(_, bulletIndex) in bullets.slice(0, 2)" :key="bulletIndex" :style="{ width: bulletIndex ? '58%' : '78%' }" />
      </div>
    </div>
  </button>
</template>

<style scoped>
.slide-thumbnail-card { width: 100%; cursor: pointer; border-radius: var(--radius-md); border: 2px solid transparent; padding: 4px; background: transparent; transition: border-color var(--motion-fast), transform var(--motion-fast); }
.slide-thumbnail-card:hover { border-color: var(--border-active); transform: translateY(-1px); }
.slide-thumbnail-card.active { border-color: var(--color-primary); }
.thumb-aspect { width: 100%; aspect-ratio: 16 / 9; overflow: hidden; background: var(--ppt-bg); color: var(--ppt-text); position: relative; display: flex; flex-direction: column; justify-content: flex-end; padding: 10px; box-sizing: border-box; border: 1px solid color-mix(in srgb, var(--ppt-muted) 28%, transparent); }
.thumb-num { position: absolute; top: 6px; left: 8px; font: 800 10px/1 var(--ppt-latin-font); color: var(--ppt-primary); }
.thumb-copy { position: relative; z-index: 1; }
.thumb-title { font-family: var(--ppt-heading-font); font-size: 10px; line-height: 1.25; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--ppt-text); margin-bottom: 7px; }
.thumb-copy i { display: block; height: 2px; margin-top: 3px; background: var(--ppt-muted); opacity: .55; }
.theme-swiss_rail .thumb-aspect { border-top: 4px solid var(--ppt-primary); }
.theme-nordic_field .thumb-aspect { border-radius: 8px; box-shadow: inset -26px 24px 0 -12px var(--ppt-secondary); }
.theme-academic_offset .thumb-aspect { border-left: 22px solid var(--ppt-primary); }
.theme-academic_offset .thumb-num { left: -18px; color: var(--ppt-on-primary); }
.theme-editorial_margin .thumb-aspect { outline: 1px solid var(--ppt-secondary); outline-offset: -7px; }
.theme-science_signal .thumb-aspect { border-top: 3px solid var(--ppt-primary); box-shadow: inset 4px 0 0 var(--ppt-secondary); }
.theme-primary_blocks .thumb-aspect { border-radius: 9px; box-shadow: inset 28px 25px 0 -19px var(--ppt-secondary), inset -28px -25px 0 -19px var(--ppt-primary); }
.theme-primary_blocks .thumb-num { color: var(--ppt-on-primary); }
</style>
