<script setup lang="ts">
import { Cpu, DataAnalysis, MagicStick, DocumentCopy, Reading, Aim } from '@element-plus/icons-vue';
import type { IntakeMessage } from '../../types';

defineProps<{
  messages: IntakeMessage[];
  streamedText?: string;
  activityMessage?: string;
  failedMessage?: string;
  taskFailureMessage?: string;
  taskRetryable?: boolean;
}>();

const emit = defineEmits<{
  selectTemplate: [prompt: string];
  retry: [];
  switchModel: [];
}>();

const starterTemplates = [
  {
    title: '初中物理 · 浮力产生的原因',
    desc: '面向八年级学生，强调实验观察与原理拆解，10分钟短视频。',
    prompt: '请帮我制作一节初中八年级物理微课《阿基米德原理与浮力产生的原因》，时长10分钟，重点包含阿基米德实验演示与公式推导，面向物理基础一般的初二学生。',
  },
  {
    title: '高一化学 · 氧化还原本质',
    desc: '从电子转移视角剖析化合价升降，突破高一概念难点。',
    prompt: '我需要设计一节高一化学微课《氧化还原反应的本质》，时长12分钟。希望从宏观化合价变化引申到微观电子转移，配有双线桥法示意图。',
  },
  {
    title: '职教技能 · Python 数据处理',
    desc: '结合真实数据清洗案例，实操与任务驱动型微课。',
    prompt: '设计针对高职软件专业学生的微课《Python Pandas 缺失值处理》，时长15分钟，场景为电商销售数据分析，强调动手实操与代码演示。',
  },
];
</script>

<template>
  <div class="conversation" aria-live="polite">
    <!-- Initial Assistant Greeting & Starter Studio -->
    <div class="message assistant welcome-turn">
      <div class="welcome-card">
        <div class="welcome-header">
          <div class="agent-avatar-badge">
            <el-icon><Cpu /></el-icon>
          </div>
          <div class="header-info">
            <div class="agent-name-tag">
              <span>课程需求 Copilot</span>
              <span class="version-badge">v2.0</span>
            </div>
            <h3>老师您好！我是您的微课需求分析 Agent</h3>
          </div>
        </div>

        <p class="welcome-desc">
          请用自然语言描述您的微课想法、授课对象、时长或教学重点。我会持续整理<strong>对教学意图的理解</strong>，确认后为您创建六个专属 Agent 任务。
        </p>

        <!-- Agent Capabilities Badges -->
        <div class="capability-row">
          <div class="cap-chip">
            <el-icon><MagicStick /></el-icon>
            <span>实时提取属性</span>
          </div>
          <div class="cap-chip">
            <el-icon><Aim /></el-icon>
            <span>智能补充缺失</span>
          </div>
          <div class="cap-chip">
            <el-icon><DocumentCopy /></el-icon>
            <span>支持教案解析</span>
          </div>
        </div>

        <!-- Quick Starter Prompt Cards (Only visible when conversation is empty) -->
        <div v-if="!messages.length" class="quick-starters">
          <span class="starters-label">
            <el-icon><Reading /></el-icon>
            快捷场景选择（点击一键开始）：
          </span>
          <div class="starter-grid">
            <button
              v-for="(item, idx) in starterTemplates"
              :key="idx"
              type="button"
              class="starter-card"
              @click="emit('selectTemplate', item.prompt)"
            >
              <div class="card-title-line">
                <el-icon><DataAnalysis /></el-icon>
                <strong>{{ item.title }}</strong>
              </div>
              <p>{{ item.desc }}</p>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- History Messages -->
    <template v-for="message in messages" :key="message.id">
      <div v-if="message.role !== 'system'" class="message" :class="message.role">
        <div class="role-meta">
          <div class="mini-avatar" :class="message.role">
            <el-icon v-if="message.role === 'assistant'"><Cpu /></el-icon>
            <span v-else>师</span>
          </div>
          <span class="message-role">{{ message.role === 'user' ? '教师' : '需求 Agent' }}</span>
        </div>
        <div class="message-bubble">
          <p>{{ message.content }}</p>
        </div>
      </div>
    </template>

    <!-- Streaming / Processing Message -->
    <div v-if="activityMessage || streamedText" class="message assistant streaming">
      <div class="role-meta">
        <div class="mini-avatar assistant pulse">
          <el-icon><Cpu /></el-icon>
        </div>
        <span class="message-role">需求 Agent 分析中...</span>
      </div>
      <div class="message-bubble">
        <p v-if="streamedText">{{ streamedText }}<span class="stream-cursor" /></p>
        <p v-else class="activity">
          <span class="activity-dot animate-ping" />
          <span>{{ activityMessage }}</span>
        </p>
      </div>
    </div>

    <div v-if="taskFailureMessage" class="task-failure-card" role="alert">
      <div>
        <strong>本轮需求分析未完成</strong>
        <p>{{ taskFailureMessage }}</p>
      </div>
      <div class="failure-actions">
        <el-button v-if="taskRetryable !== false" type="primary" plain size="small" @click="emit('retry')">重试本轮</el-button>
        <el-button size="small" @click="emit('switchModel')">切换模型</el-button>
      </div>
    </div>

    <el-alert v-if="failedMessage" :title="failedMessage" type="error" show-icon :closable="false" class="failed-alert" />
  </div>
</template>

<style scoped>
.conversation {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 16px;
}

.message {
  max-width: 92%;
  display: flex;
  flex-direction: column;
  animation: fadeIn 240ms var(--ease-out-smooth);
}

.message.user {
  align-self: flex-end;
  align-items: flex-end;
}

.message.assistant {
  align-self: flex-start;
  align-items: flex-start;
}

.task-failure-card {
  width: min(680px, 92%);
  box-sizing: border-box;
  border: 1px solid #fecaca;
  border-radius: 12px;
  background: #fff7f7;
  color: #991b1b;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.task-failure-card strong { font-size: 13px; }
.task-failure-card p { margin: 3px 0 0; color: #b91c1c; font-size: 12px; line-height: 1.5; }
.failure-actions { display: flex; flex-shrink: 0; }

@media (max-width: 640px) {
  .task-failure-card { width: 100%; align-items: stretch; flex-direction: column; }
}

.role-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.mini-avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-weight: 800;
}

.mini-avatar.assistant {
  background: #002fa7;
  color: #ffffff;
  box-shadow: 0 2px 5px rgba(99, 102, 241, 0.25);
}

.mini-avatar.user {
  background: #002fa7;
  color: #ffffff;
}

.mini-avatar.pulse {
  animation: pulseAvatar 1.5s infinite ease-in-out;
}

@keyframes pulseAvatar {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4); }
  50% { transform: scale(1.08); box-shadow: 0 0 0 6px rgba(99, 102, 241, 0); }
}

.message-role {
  color: var(--text-muted);
  font-size: 11.5px;
  font-weight: 700;
}

.welcome-turn {
  width: 100%;
  max-width: 100%;
}

.welcome-card {
  background: #f7f7f8;
  border: 1px solid #cfd2d9;
  border-radius: 0;
  padding: 10px 14px;
  box-shadow: 0 3px 12px rgba(99, 102, 241, 0.04);
  position: relative;
  overflow: hidden;
}

.welcome-card::before { content: none; }

.welcome-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.agent-avatar-badge {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: #002fa7;
  color: #ffffff;
  display: grid;
  place-items: center;
  font-size: 13.5px;
  box-shadow: none;
  flex-shrink: 0;
}

.header-info h3 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 800;
  color: #1e1b4b;
  letter-spacing: -0.01em;
}

.agent-name-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 800;
  color: #002fa7;
}

.version-badge {
  background: #e0e7ff;
  color: #4338ca;
  font-size: 9px;
  padding: 0px 4px;
  border-radius: 6px;
}

.welcome-desc {
  margin: 0 0 6px;
  color: #334155;
  font-size: 12.5px;
  line-height: 1.45;
}

.capability-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 6px;
}

.cap-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid #c7d2fe;
  color: #4338ca;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 1px 3px rgba(99, 102, 241, 0.03);
}

.quick-starters {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #cbd5e1;
}

.starters-label {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #475569;
  font-size: 11px;
  font-weight: 800;
  margin-bottom: 6px;
}

.starter-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 6px;
}

.starter-card {
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  padding: 6px 10px;
  text-align: left;
  cursor: pointer;
  transition: all 180ms var(--ease-out-smooth);
}

.starter-card:hover {
  border-color: #002fa7;
  background: #f2f5ff;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.08);
}

.card-title-line {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #002fa7;
  margin-bottom: 1px;
}

.card-title-line strong {
  font-size: 11.5px;
  font-weight: 800;
}

.starter-card p {
  margin: 0;
  font-size: 10.5px;
  color: #64748b;
  line-height: 1.35;
}

.message-bubble {
  position: relative;
}

.message-bubble p {
  margin: 0;
  padding: 12px 18px;
  font-size: 14.5px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.message.assistant .message-bubble p {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0;
  color: var(--text-primary);
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
}

.message.user .message-bubble p {
  background: #002fa7;
  border: 0;
  color: #ffffff;
  border-radius: 0;
  box-shadow: none;
  font-weight: 500;
}

.activity {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary) !important;
  font-weight: 600;
}

.activity-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #002fa7;
  box-shadow: none;
}

.stream-cursor {
  display: inline-block;
  width: 2.5px;
  height: 16px;
  background: #002fa7;
  margin-left: 4px;
  vertical-align: middle;
  animation: blink 0.9s infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

.failed-alert {
  border-radius: var(--radius-control);
}
</style>
