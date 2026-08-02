<script setup lang="ts">
import type { VerbatimSegment } from '../../types';

defineProps<{
  segment: VerbatimSegment;
  index: number;
  isTeleprompter?: boolean;
}>();
</script>

<template>
  <div :class="['verbatim-segment-card', { teleprompter: isTeleprompter }]">
    <div class="segment-header">
      <span class="slide-ref-tag">对应 PPT 第 {{ segment.slide_ref }} 页</span>
      <span class="time-marker">{{ segment.time_marker }}</span>
    </div>

    <p class="speech-body">{{ segment.speech_text }}</p>

    <div v-if="segment.pedagogical_tip" class="pedagogical-tip">
      💡 教学互动提示: {{ segment.pedagogical_tip }}
    </div>
  </div>
</template>

<style scoped>
.verbatim-segment-card {
  padding: 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  margin-bottom: 16px;
}

.verbatim-segment-card.teleprompter {
  background: #090d16;
  border-color: #1e293b;
  color: #f8fafc;
}

.segment-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.slide-ref-tag {
  font-size: 12px;
  font-weight: 800;
  color: var(--color-primary);
}

.teleprompter .slide-ref-tag {
  color: #818cf8;
}

.time-marker {
  font-size: 12px;
  color: var(--text-muted);
  font-family: monospace;
}

.speech-body {
  margin: 0;
  font-size: 16px;
  line-height: 1.8;
  color: var(--text-primary);
}

.teleprompter .speech-body {
  font-size: 22px;
  line-height: 1.9;
  color: #ffffff;
}

.pedagogical-tip {
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--color-warning-soft);
  color: var(--color-warning);
  border-radius: var(--radius-sm);
  font-size: 12px;
}

.teleprompter .pedagogical-tip {
  background: rgba(217, 119, 6, 0.2);
  color: #fcd34d;
}
</style>
