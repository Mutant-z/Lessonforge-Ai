<script setup lang="ts">
import type { PPTSlide } from '../../types';

defineProps<{
  slide: PPTSlide;
  index: number;
  isActive: boolean;
}>();

const emit = defineEmits<{
  (e: 'select', index: number): void;
}>();
</script>

<template>
  <div 
    class="slide-thumbnail-card" 
    :class="{ active: isActive }" 
    @click="emit('select', index)"
  >
    <div class="thumb-aspect">
      <span class="thumb-num">{{ index + 1 }}</span>
      <div class="thumb-title">{{ slide.title || 'PPT Page' }}</div>
    </div>
  </div>
</template>

<style scoped>
.slide-thumbnail-card {
  width: 100%;
  cursor: pointer;
  border-radius: var(--radius-md);
  border: 2px solid transparent;
  padding: 4px;
  transition: all var(--motion-fast);
}

.slide-thumbnail-card:hover {
  border-color: var(--border-active);
}

.slide-thumbnail-card.active {
  border-color: var(--color-primary);
}

.thumb-aspect {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #1e1b4b;
  border-radius: var(--radius-sm);
  padding: 10px;
  color: #fff;
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.thumb-num {
  position: absolute;
  top: 6px;
  left: 6px;
  font-size: 10px;
  font-weight: 800;
  background: rgba(255, 255, 255, 0.2);
  padding: 1px 6px;
  border-radius: 4px;
}

.thumb-title {
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #e0e7ff;
}
</style>
