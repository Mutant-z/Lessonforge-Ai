<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import AgentNode from '../visual/AgentNode.vue';
import { Cpu, MagicStick, Document, VideoCamera, Select, Reading, Files, Download } from '@element-plus/icons-vue';

const activeStage = ref(1);
let timer: any = null;

onMounted(() => {
  timer = setInterval(() => {
    activeStage.value = (activeStage.value % 4) + 1;
  }, 3200);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="agent-workflow-console card-hover">
    <!-- Header bar of console -->
    <div class="console-header">
      <div class="header-dots">
        <span class="dot red"></span>
        <span class="dot yellow"></span>
        <span class="dot green"></span>
      </div>
      <div class="console-title">
        <el-icon><Cpu /></el-icon>
        <span>LessonForge Multi-Agent Workstation</span>
      </div>
      <div class="console-status-badge">
        <span class="live-pulse"></span>
        <span>Parallel Mode</span>
      </div>
    </div>

    <!-- Step 1: Input Banner -->
    <div class="console-input-banner">
      <div class="input-tag">教师需求输入</div>
      <div class="input-query">
        <span class="query-topic">《高中物理：牛顿第二定律》</span>
        <span class="query-meta">15分钟微课 · 高一 · 实验引入 + 梯度练习</span>
      </div>
    </div>

    <!-- Flow Diagram Node Grid -->
    <div class="workflow-grid">
      <!-- Master Blueprint Node -->
      <div class="blueprint-master-row">
        <AgentNode 
          name="课程蓝图 Agent"
          role="拆解教学目标、分配时长与事实源"
          :status="activeStage >= 1 ? 'completed' : 'pending'"
          color="primary"
          detail="核心蓝图锁定 (Blueprint Source of Truth)"
        />
      </div>

      <!-- Connector line -->
      <div class="flow-connector-vertical">
        <svg class="connector-svg" width="100%" height="24">
          <line x1="50%" y1="0" x2="50%" y2="24" stroke="var(--color-primary-border)" stroke-width="2" stroke-dasharray="4 4" />
        </svg>
      </div>

      <!-- Parallel Generating Agents -->
      <div class="parallel-nodes-grid">
        <AgentNode 
          name="教学设计 Agent"
          role="规范案 + 步骤规划"
          :status="activeStage === 1 ? 'running' : 'completed'"
          color="cyan"
        />

        <AgentNode 
          name="PPT 课件 Agent"
          role="16:9 页面 + 视觉排版"
          :status="activeStage === 2 ? 'running' : activeStage > 2 ? 'completed' : 'pending'"
          color="violet"
        />

        <AgentNode 
          name="任务单 Agent"
          role="导学卡 + 问题链"
          :status="activeStage === 3 ? 'running' : activeStage > 3 ? 'completed' : 'pending'"
          color="mint"
        />

        <AgentNode 
          name="梯度练习 Agent"
          role="分层题型 + 逐字稿"
          :status="activeStage === 4 ? 'running' : 'pending'"
          color="amber"
        />
      </div>

      <!-- Quality Checker & Output preview -->
      <div class="output-preview-bar">
        <div class="quality-check-badge">
          <el-icon><Select /></el-icon>
          <span>多维度质量巡检 Agent 校验通过</span>
        </div>
        <div class="resource-pill-group">
          <span class="res-pill pptx"><el-icon><Files /></el-icon> 16:9 PPTX</span>
          <span class="res-pill docx"><el-icon><Document /></el-icon> 教学设计.docx</span>
          <span class="res-pill script"><el-icon><VideoCamera /></el-icon> 脚本&逐字稿</span>
          <span class="res-pill zip"><el-icon><Download /></el-icon> 资源打包.zip</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-workflow-console {
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-hero);
  box-shadow: var(--shadow-floating);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 10;
}

.console-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  background: var(--surface-secondary);
  border-bottom: 1px solid var(--border-light);
}

.header-dots {
  display: flex;
  gap: 6px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.dot.red { background: #ff5f56; }
.dot.yellow { background: #ffbd2e; }
.dot.green { background: #27c93f; }

.console-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}

.console-status-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
}

.live-pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 8px var(--color-primary);
  animation: pulseGlow 1.8s infinite;
}

.console-input-banner {
  padding: 14px 20px;
  background: linear-gradient(135deg, rgba(91, 92, 240, 0.06) 0%, rgba(139, 92, 246, 0.06) 100%);
  border-bottom: 1px dashed var(--border-default);
  display: flex;
  align-items: center;
  gap: 12px;
}

.input-tag {
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--surface-primary);
  padding: 3px 8px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--color-primary-border);
  flex-shrink: 0;
}

.input-query {
  display: flex;
  flex-direction: column;
}

.query-topic {
  font-size: 13px;
  font-weight: 800;
  color: var(--text-primary);
}

.query-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.workflow-grid {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--surface-secondary);
}

.blueprint-master-row {
  width: 100%;
}

.flow-connector-vertical {
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.parallel-nodes-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

@media (max-width: 640px) {
  .parallel-nodes-grid {
    grid-template-columns: 1fr;
  }
}

.output-preview-bar {
  margin-top: 8px;
  padding: 12px 14px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quality-check-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-mint);
}

.resource-pill-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.res-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.res-pill.pptx { background: var(--accent-violet-soft); color: var(--accent-violet); }
.res-pill.docx { background: var(--accent-cyan-soft); color: var(--accent-cyan); }
.res-pill.script { background: var(--accent-amber-soft); color: var(--accent-amber); }
.res-pill.zip { background: var(--color-primary-soft); color: var(--color-primary); }
</style>
