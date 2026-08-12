<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  counts: {
    all: number;
    running: number;
    review: number;
    done: number;
    completionRate: number;
    savedHours: number;
  };
  activeFilter: string;
}>();

const emit = defineEmits<{
  (e: 'update:activeFilter', filter: string): void;
}>();

function setFilter(filter: string) {
  emit('update:activeFilter', filter);
}
</script>

<template>
  <div class="dashboard-summary-surface">
    <!-- Deliverable Readiness Banner Strip -->
    <div class="summary-meta-block">
      <div class="meta-label-group">
        <span class="meta-eyebrow">WORKFLOW OVERVIEW</span>
        <h3 class="meta-title">教学资源交付状态</h3>
      </div>

      <div class="meta-progress-box">
        <span class="progress-text-label">可交付微课：</span>
        <span class="progress-num">{{ counts.done }} / {{ counts.all }}</span>
        <div class="progress-bar-track">
          <div class="progress-bar-fill" :style="{ width: `${counts.completionRate}%` }"></div>
        </div>
        <span class="progress-pct">{{ counts.completionRate }}%</span>
      </div>
    </div>

    <!-- Integrated Metric Pills Row (Single Surface with Vertical Dividers) -->
    <div class="summary-metrics-row">
      <!-- 1. All Projects -->
      <div 
        class="metric-chip"
        :class="{ active: activeFilter === 'all' }"
        @click="setFilter('all')"
      >
        <span class="chip-val primary">{{ counts.all }}</span>
        <span class="chip-title">全部微课项目</span>
      </div>

      <div class="chip-divider"></div>

      <!-- 2. Completed -->
      <div 
        class="metric-chip"
        :class="{ active: activeFilter === 'completed' }"
        @click="setFilter('completed')"
      >
        <span class="chip-val success">{{ counts.done }}</span>
        <span class="chip-title">已打包交付</span>
      </div>

      <div class="chip-divider"></div>

      <!-- 3. Pending Review -->
      <div 
        class="metric-chip highlight-warning"
        :class="{ active: activeFilter === 'review', urgent: counts.review > 0 }"
        @click="setFilter('review')"
      >
        <div class="chip-val-wrap">
          <span class="chip-val warning">{{ counts.review }}</span>
          <span v-if="counts.review > 0" class="urgent-badge">需处理</span>
        </div>
        <span class="chip-title">待教师审核</span>
      </div>

      <div class="chip-divider"></div>

      <!-- 4. Agent Running -->
      <div 
        class="metric-chip"
        :class="{ active: activeFilter === 'running', live: counts.running > 0 }"
        @click="setFilter('running')"
      >
        <div class="chip-val-wrap">
          <span class="chip-val agent">{{ counts.running }}</span>
          <span v-if="counts.running > 0" class="live-pulse-dot animate-pulse"></span>
        </div>
        <span class="chip-title">Agent 生成中</span>
      </div>

      <div class="chip-divider"></div>

      <!-- 5. Saved Hours -->
      <div class="metric-chip static">
        <span class="chip-val mint">{{ counts.savedHours }}<small class="unit">h</small></span>
        <span class="chip-title">累计节省工时</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-summary-surface {
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 10px 18px;
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.summary-meta-block {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-light);
}

.meta-label-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.meta-eyebrow {
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  letter-spacing: 0.08em;
}

.meta-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--text-primary);
}

.meta-progress-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-text-label {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-muted);
}

.progress-num {
  font-size: 13.5px;
  font-weight: 800;
  color: var(--color-primary);
}

.progress-pct {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--text-muted);
}

.progress-bar-track {
  width: 100px;
  height: 6px;
  background: var(--surface-tertiary);
  border-radius: var(--radius-pill);
  overflow: hidden;
  border: 1px solid var(--border-soft);
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  border-radius: var(--radius-pill);
  transition: width var(--motion-slow) var(--ease-out-smooth);
}

/* Integrated Single Surface Metrics Row */
.summary-metrics-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  background: var(--surface-secondary);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-control);
  padding: 4px 8px;
}

.chip-divider {
  width: 1px;
  height: 28px;
  background: var(--border-default);
  flex-shrink: 0;
}

.metric-chip {
  flex: 1;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  transition: all var(--motion-fast) var(--ease-out-smooth);
}

.metric-chip:hover {
  background: var(--surface-primary);
  border-color: var(--color-primary-border);
}

.metric-chip.active {
  background: var(--surface-primary);
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-xs);
}

.metric-chip.static {
  cursor: default;
}
.metric-chip.static:hover {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}

.chip-val-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
}

.chip-val {
  font-size: 19px;
  font-weight: 900;
  line-height: 1;
}

.chip-val.primary { color: var(--color-primary); }
.chip-val.success { color: var(--accent-mint); }
.chip-val.warning { color: var(--accent-amber); }
.chip-val.agent { color: var(--accent-violet); }
.chip-val.mint { color: var(--accent-cyan); }

.unit {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  margin-left: 1px;
}

.chip-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-muted);
  white-space: nowrap;
}

.urgent-badge {
  font-size: 10.5px;
  font-weight: 800;
  padding: 1px 5px;
  border-radius: var(--radius-pill);
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
  border: 1px solid rgba(217, 119, 6, 0.2);
}

.live-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent-violet);
  box-shadow: 0 0 6px var(--accent-violet);
}

@media (max-width: 1024px) {
  .summary-metrics-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
  }
  .chip-divider {
    display: none;
  }
}

@media (max-width: 640px) {
  .summary-meta-block {
    flex-direction: column;
    align-items: flex-start;
  }
  .summary-metrics-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
