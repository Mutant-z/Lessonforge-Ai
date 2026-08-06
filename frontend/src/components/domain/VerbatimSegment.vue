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
      <div class="header-left">
        <span class="seg-chip">🚀 SEG {{ String(index + 1).padStart(2, '0') }}</span>
        <span class="time-marker">⏱️ {{ segment.time_marker }}</span>
      </div>
      <span class="slide-ref-tag">📑 对应 PPT 第 {{ segment.slide_ref }} 页</span>
    </div>

    <p class="speech-body">{{ segment.speech_text }}</p>

    <div v-if="segment.pedagogical_tip" class="pedagogical-tip">
      <span class="tip-badge">🎭 教学互动提示</span>
      <p class="tip-text">{{ segment.pedagogical_tip }}</p>
    </div>
  </div>
</template>

<style scoped>
.verbatim-segment-card {
  padding: 20px 24px;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  border: 1.5px solid #cbd5e1;
  border-left: 5px solid #4f46e5;
  border-radius: 14px;
  margin-bottom: 20px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
  transition: all 0.2s ease;
}

.verbatim-segment-card:hover {
  box-shadow: 0 4px 16px rgba(79, 70, 229, 0.1);
  border-color: #a5b4fc;
}

.verbatim-segment-card.teleprompter {
  background: #090d16;
  border-color: #1e293b;
  border-left-color: #6366f1;
  color: #f8fafc;
}

.segment-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.seg-chip {
  font-size: 12px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  padding: 4px 12px;
  border-radius: 999px;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.3);
}

.time-marker {
  font-size: 12px;
  font-weight: 800;
  color: #3730a3;
  background: #e0e7ff;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
}

.teleprompter .time-marker {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  border-color: rgba(99, 102, 241, 0.4);
}

.slide-ref-tag {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  padding: 3px 10px;
  border-radius: 8px;
}

.teleprompter .slide-ref-tag {
  background: #1e293b;
  color: #cbd5e1;
  border-color: #334155;
}

.speech-body {
  margin: 0;
  font-size: 15.5px;
  line-height: 1.85;
  color: #0f172a;
}

.teleprompter .speech-body {
  font-size: 22px;
  line-height: 1.9;
  color: #ffffff;
}

.pedagogical-tip {
  margin-top: 16px;
  padding: 14px 18px;
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
  border: 1.5px solid #bae6fd;
  border-left: 5px solid #0284c7;
  border-radius: 12px;
}

.teleprompter .pedagogical-tip {
  background: rgba(2, 132, 199, 0.15);
  border-color: rgba(2, 132, 199, 0.3);
  border-left-color: #38bdf8;
}

.tip-badge {
  display: inline-block;
  font-size: 12px;
  font-weight: 800;
  color: #0369a1;
  background: #e0f2fe;
  padding: 3px 10px;
  border-radius: 999px;
  margin-bottom: 6px;
}

.teleprompter .tip-badge {
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.2);
}

.tip-text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.65;
  color: #0369a1;
}

.teleprompter .tip-text {
  color: #bae6fd;
}
</style>
