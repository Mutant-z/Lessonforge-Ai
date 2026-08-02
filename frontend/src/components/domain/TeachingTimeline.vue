<script setup lang="ts">
import { Clock } from '@element-plus/icons-vue';

interface ActivityStage {
  stage: string;
  duration_minutes: number;
  teacher_activity: string;
  student_activity: string;
  design_intent: string;
  assessment: string;
}

defineProps<{
  activities: ActivityStage[];
}>();
</script>

<template>
  <div class="teaching-timeline">
    <div v-for="(act, idx) in activities" :key="idx" class="timeline-row lf-card">
      <div class="stage-sidebar">
        <span class="stage-num">0{{ idx + 1 }}</span>
        <h4 class="stage-name">{{ act.stage }}</h4>
        <span class="stage-time">
          <el-icon><Clock /></el-icon> {{ act.duration_minutes }} 分钟
        </span>
      </div>

      <div class="stage-body">
        <div class="activity-grid">
          <div class="act-box teacher">
            <h5>👨‍🏫 教师活动与引导</h5>
            <p>{{ act.teacher_activity }}</p>
          </div>

          <div class="act-box student">
            <h5>👩‍🎓 活学活用与探究</h5>
            <p>{{ act.student_activity }}</p>
          </div>
        </div>

        <div class="intent-footer">
          <div class="intent-item">
            <strong>🎯 设计意图:</strong> {{ act.design_intent }}
          </div>
          <div v-if="act.assessment" class="intent-item assessment">
            <strong>📋 学习证据/评价:</strong> {{ act.assessment }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.teaching-timeline {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin: 16px 0;
}

.timeline-row {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 20px;
  padding: 20px;
}

@media (max-width: 768px) {
  .timeline-row {
    grid-template-columns: 1fr;
  }
}

.stage-sidebar {
  border-right: 1px solid var(--border-light);
  padding-right: 16px;
  display: flex;
  flex-direction: column;
}

.stage-num {
  font-size: 12px;
  font-weight: 800;
  color: var(--color-primary);
}

.stage-name {
  margin: 4px 0 8px;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.stage-time {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}

.activity-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 14px;
}

@media (max-width: 640px) {
  .activity-grid {
    grid-template-columns: 1fr;
  }
}

.act-box h5 {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.act-box p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.intent-footer {
  padding-top: 10px;
  border-top: 1px dashed var(--border-default);
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.intent-item {
  color: var(--text-secondary);
}

.intent-item.assessment {
  color: var(--color-primary);
}
</style>
