<script setup lang="ts">
import { Cpu, DataAnalysis, MagicStick, DocumentCopy, Reading, Aim } from '@element-plus/icons-vue';
import type { IntakeMessage } from '../../types';
import MarkdownRenderer from '../content-renderers/MarkdownRenderer.vue';

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
          <MarkdownRenderer :content="message.content" />
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
        <div v-if="streamedText">
          <MarkdownRenderer :content="streamedText" is-streaming />
          <span class="stream-cursor" />
        </div>
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
  gap: 16px;
  padding: 16px 20px;
}

.message {
  max-width: 90%;
  display: flex;
  flex-direction: column;
  animation: fadeIn 240ms var(--ease-out-smooth, ease);
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
  border: 1px solid #fecdd3;
  border-radius: 14px;
  background: #fff1f2;
  color: #991b1b;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  box-shadow: 0 4px 12px rgba(225, 29, 72, 0.06);
}

.task-failure-card strong { font-size: 13px; font-weight: 700; }
.task-failure-card p { margin: 3px 0 0; color: #b91c1c; font-size: 12px; line-height: 1.5; }
.failure-actions { display: flex; flex-shrink: 0; gap: 8px; }

@media (max-width: 640px) {
  .task-failure-card { width: 100%; align-items: stretch; flex-direction: column; }
}

.role-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.mini-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  font-weight: 800;
}

.mini-avatar.assistant {
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.35);
}

.mini-avatar.user {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
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
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.welcome-turn {
  width: 100%;
  max-width: 100%;
}

.welcome-card {
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 50%, #eef2ff 100%);
  border: 1.5px solid #e2e8f0;
  border-radius: 18px;
  padding: 18px 22px;
  box-shadow: 0 4px 18px rgba(15, 23, 42, 0.04);
  position: relative;
  overflow: hidden;
}

.welcome-card::before { content: none; }

.welcome-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}

.agent-avatar-badge {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  display: grid;
  place-items: center;
  font-size: 20px;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.3);
  flex-shrink: 0;
}

.header-info h3 {
  margin: 2px 0 0;
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.agent-name-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 800;
  color: #4f46e5;
}

.version-badge {
  background: #e0e7ff;
  color: #4338ca;
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 800;
  border: 1px solid #c7d2fe;
}

.welcome-desc {
  margin: 0 0 14px;
  color: #334155;
  font-size: 13.5px;
  line-height: 1.6;
}

.capability-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.cap-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ffffff;
  border: 1px solid #c7d2fe;
  color: #4338ca;
  padding: 5px 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.06);
  transition: all 180ms ease;
}

.cap-chip:hover {
  transform: translateY(-1px);
  background: #f5f3ff;
  border-color: #a5b4fc;
}

.quick-starters {
  margin-top: 12px;
  padding-top: 14px;
  border-top: 1px dashed #cbd5e1;
}

.starters-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #334155;
  font-size: 12.5px;
  font-weight: 800;
  margin-bottom: 12px;
}

.starter-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

@media (max-width: 1024px) {
  .starter-grid {
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  }
}

.starter-card {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px 14px;
  text-align: left;
  cursor: pointer;
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
}

.starter-card:hover {
  border-color: #4f46e5;
  background: linear-gradient(135deg, #ffffff 0%, #f5f3ff 100%);
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(79, 70, 229, 0.12);
}

.card-title-line {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #4f46e5;
  margin-bottom: 4px;
}

.card-title-line strong {
  font-size: 13px;
  font-weight: 800;
}

.starter-card p {
  margin: 0;
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.5;
}

.message-bubble {
  position: relative;
  padding: 12px 18px;
  font-size: 14.5px;
  line-height: 1.65;
  white-space: normal;
  min-width: 0;
  max-width: 100%;
}

.message.assistant .message-bubble {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 18px 18px 18px 4px;
  color: #0f172a;
  box-shadow: 0 3px 14px rgba(15, 23, 42, 0.04);
}

.message.user .message-bubble {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  border: 0;
  color: #ffffff;
  border-radius: 18px 18px 4px 18px;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.22);
  font-weight: 500;
}

.message.user .message-bubble :deep(.markdown-rendered-body),
.message.user .message-bubble :deep(.markdown-rendered-body) strong {
  color: #ffffff;
}

.message.user .message-bubble :deep(.markdown-rendered-body code) {
  background: rgba(255, 255, 255, 0.16);
  border-color: rgba(255, 255, 255, 0.28);
  color: #ffffff;
}

.message.user .message-bubble :deep(.markdown-rendered-body a) {
  color: #dbeafe;
}

.activity {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #334155 !important;
  font-weight: 600;
}

.activity-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
}

.stream-cursor {
  display: inline-block;
  width: 2.5px;
  height: 16px;
  background: #4f46e5;
  margin-left: 4px;
  vertical-align: middle;
  animation: blink 0.9s infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

.failed-alert {
  border-radius: 12px;
}
</style>
