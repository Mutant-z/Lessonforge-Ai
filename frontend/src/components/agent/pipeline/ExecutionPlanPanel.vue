<script setup lang="ts">
import { computed } from 'vue';
import { VideoPlay, VideoPause, RefreshRight } from '@element-plus/icons-vue';
import type { CourseTask } from '../../../types';
import { AGENT_PIPELINE_LABELS, PIPELINE_STATUS_LABELS } from '../../../types/agentPipeline';

const props = defineProps<{
  task: CourseTask | null;
  plan: Array<{ key?: string; role?: string }>;
  status: string;
  doneAgents: string[];
  currentAgent: string;
  paused: boolean;
}>();

const emit = defineEmits<{ (e: 'pause'): void; (e: 'resume'): void; (e: 'retry'): void }>();

const statusLabel = computed(() => PIPELINE_STATUS_LABELS[props.status] || props.status || '未运行');
const statusType = computed(() => {
  if (props.status === 'running') return 'primary';
  if (props.status === 'completed') return 'success';
  if (props.status === 'paused') return 'warning';
  if (props.status === 'failed') return 'danger';
  return 'info';
});
const planAgents = computed(() => {
  if (props.plan.length) return props.plan;
  return [
    { key: 'narrative', role: '演示叙事' }, { key: 'template_analysis', role: '模板分析' },
    { key: 'slide_content', role: '页面内容' }, { key: 'visual_plan', role: '视觉规划' },
    { key: 'layout', role: '页面布局' }, { key: 'media', role: '图片图表' },
    { key: 'ppt_editor', role: 'PPT 编辑' }, { key: 'visual_qa', role: '视觉 QA' },
  ];
});
</script>

<template>
  <div class="plan-panel">
    <div class="panel-head">
      <div class="panel-title">{{ task?.display_name || 'PPT 生成' }}</div>
      <el-tag :type="statusType" size="small">{{ statusLabel }}</el-tag>
    </div>
    <div class="panel-sub">{{ task?.agent_name || '' }} · 多 Agent 流水线</div>

    <div class="controls">
      <el-button v-if="!paused && status === 'running'" size="small" @click="emit('pause')">
        <el-icon><VideoPause /></el-icon>&nbsp;暂停
      </el-button>
      <el-button v-else-if="paused" size="small" type="primary" @click="emit('resume')">
        <el-icon><VideoPlay /></el-icon>&nbsp;继续
      </el-button>
      <el-button v-if="status === 'failed'" size="small" type="warning" @click="emit('retry')">
        <el-icon><RefreshRight /></el-icon>&nbsp;重试
      </el-button>
    </div>

    <div class="section-title">执行计划</div>
    <div class="agent-list">
      <div v-for="agent in planAgents" :key="agent.key" class="agent-row"
           :class="{
             done: doneAgents.includes(agent.key || ''),
             current: currentAgent === agent.key,
           }">
        <span class="agent-dot" />
        <span class="agent-name">{{ AGENT_PIPELINE_LABELS[agent.key || ''] || agent.role || agent.key }}</span>
        <span class="agent-state">
          <span v-if="currentAgent === agent.key" class="live">进行中</span>
          <span v-else-if="doneAgents.includes(agent.key || '')" class="done-tag">✓</span>
        </span>
      </div>
    </div>

    <div class="section-title">运行说明</div>
    <div class="notes">
      <p>· 内容来自已确认的课程蓝图与教学设计等上游产物</p>
      <p>· 模板仅作为设计语言来源，页面由布局 Agent 动态计算元素位置</p>
      <p>· 生成后会渲染并执行视觉 QA，问题自动路由到对应 Agent 修订</p>
    </div>
  </div>
</template>

<style scoped>
.plan-panel { padding: 16px 14px; height: 100%; overflow-y: auto; }
.panel-head { display: flex; align-items: center; justify-content: space-between; }
.panel-title { font-size: 16px; font-weight: 700; color: #111827; }
.panel-sub { font-size: 12px; color: #6b7280; margin-top: 4px; }
.controls { display: flex; gap: 8px; margin: 14px 0; }
.section-title { font-size: 12px; color: #9ca3af; font-weight: 600; margin: 14px 0 8px; letter-spacing: 0.02em; }
.agent-list { display: flex; flex-direction: column; gap: 4px; }
.agent-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 8px; font-size: 13px; color: #374151;
  border: 1px solid transparent;
}
.agent-row.current { background: #eef2ff; border-color: #c7d2fe; color: #4338ca; }
.agent-row.done .agent-dot { background: #22c55e; }
.agent-row.current .agent-dot { background: #4f46e5; }
.agent-dot { width: 8px; height: 8px; border-radius: 50%; background: #d1d5db; }
.agent-name { flex: 1; }
.agent-state { font-size: 12px; }
.live { color: #4f46e5; font-weight: 600; }
.done-tag { color: #22c55e; }
.notes p { font-size: 12px; color: #6b7280; margin: 4px 0; line-height: 1.6; }
</style>
