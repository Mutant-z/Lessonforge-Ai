<script setup lang="ts">
import AgentNode from '../visual/AgentNode.vue';
import { Cpu, Select } from '@element-plus/icons-vue';
</script>

<template>
  <div class="auth-agent-preview-card card-hover">
    <div class="preview-header">
      <div class="header-tag">
        <el-icon><Cpu /></el-icon>
        <span>实时 Multi-Agent 状态示例</span>
      </div>
      <span class="preview-topic">主题: 牛顿第二定律</span>
    </div>

    <div class="preview-nodes-stack">
      <AgentNode 
        name="课程蓝图 Master Agent"
        role="事实源锁定 · 目标与时序规划"
        status="completed"
        color="primary"
      />

      <AgentNode 
        name="16:9 PPT 课件 Agent"
        role="幻灯片生成中 (Slide 08/18)"
        status="running"
        color="violet"
      />

      <AgentNode 
        name="质量巡检 Agent"
        role="自动检查教学规范与格式对齐"
        status="reviewing"
        color="amber"
      />
    </div>

    <div class="preview-footer">
      <div class="footer-badge">
        <el-icon><Select /></el-icon>
        <span>5 个核心 Agent 深度并行推理中</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-agent-preview-card {
  background: var(--surface-dark-card);
  border: 1px solid var(--border-glass);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-radius: var(--radius-card);
  padding: 16px 20px;
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.header-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 800;
  color: #a5b4fc;
  background: rgba(165, 180, 252, 0.12);
  padding: 3px 10px;
  border-radius: var(--radius-pill);
}

.preview-topic {
  font-size: 12px;
  color: #cbd5e1;
  font-weight: 600;
}

.preview-nodes-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-footer {
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.footer-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 700;
  color: #34d399;
}
</style>
