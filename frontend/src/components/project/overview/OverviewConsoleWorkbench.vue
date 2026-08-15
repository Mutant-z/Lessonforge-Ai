<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  Aim,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  CircleCheck,
  CollectionTag,
  Cpu,
  Document,
  Loading,
  Memo,
  Operation,
  Reading,
  RefreshRight,
  Star,
  User,
  Warning
} from '@element-plus/icons-vue';
import type { CourseProjectWorkspace, CourseTask } from '../../../types';

const props = defineProps<{
  project: CourseProjectWorkspace;
  completion: number;
  approvedCount: number;
  activeCount: number;
  attentionCount: number;
  reviewCount: number;
  tasks: CourseTask[];
  courseId: string;
}>();

const emit = defineEmits<{
  (e: 'retry-planning'): void;
  (e: 'initialize-agents'): void;
  (e: 'open-memory'): void;
}>();

const router = useRouter();

// 共享项目记忆：悬停高亮显示该 Agent 可读取的参考产物（不再展示上下游拓扑依赖）
const hoveredTaskType = ref<string | null>(null);
const showBlueprint = ref(true);

const totalTasks = computed(() => props.tasks.length || 6);

// Find first task requiring teacher review or attention
const nextActionTask = computed(() => {
  return (
    props.tasks.find(t => t.status === 'review') ||
    props.tasks.find(t => ['stale', 'failed'].includes(t.status))
  );
});

function handleNextAction() {
  if (nextActionTask.value) {
    router.push(`/courses/${props.courseId}/tasks/${nextActionTask.value.task_type}`);
  }
}

function navigateToTask(taskType: string) {
  router.push(`/courses/${props.courseId}/tasks/${taskType}`);
}

function getReferenceNames(taskType: string) {
  const task = props.tasks.find(x => x.task_type === taskType);
  const available = Object.keys(task?.available_sources || {});
  if (available.length) {
    return available.map(type => props.tasks.find(x => x.task_type === type)?.display_name || type).join('、');
  }
  return '';
}

const currentHoveredTask = computed(() => {
  if (!hoveredTaskType.value) return null;
  return props.tasks.find(t => t.task_type === hoveredTaskType.value) || null;
});

const memoryRevision = computed(() => props.project?.memory?.revision || 0);

// Blueprint formatting helpers
const formattedObjectives = computed(() => {
  const raw = props.project?.intent?.teaching_objectives || '';
  if (!raw) return [];
  const items = raw
    .split(/(?=\d+[\.．\s])|[;；]/)
    .map((s: string) => s.trim().replace(/^\d+[\.．]\s*/, ''))
    .filter(Boolean);
  return items.length > 0 ? items : [raw];
});

const qualityCheckTags = computed(() => {
  const summary = props.project?.quality?.summary || '';
  if (!summary) return ['结构校验', '引用可溯', '时长控规', '目标覆盖', '题目检测'];
  const match = summary.match(/已完成(.*?)检查/);
  if (match && match[1]) {
    return match[1].split(/[、、和]/).map((s: string) => s.trim()).filter(Boolean);
  }
  return ['结构校验', '引用可溯', '时长控规', '目标覆盖', '题目检测'];
});
</script>

<template>
  <div class="unified-workbench-card">
    <!-- Active Planning / Agent Init Alerts -->
    <div v-if="project.planning.status !== 'ready'" class="console-alert-banner planning">
      <div class="alert-left">
        <span class="alert-badge">规划引擎</span>
        <div class="alert-text">
          <strong>{{ project.planning.status === 'failed' ? '内部规划异常' : '正在将教学意图转化为任务上下文' }}</strong>
          <p>{{ project.planning.error?.message || '完成后将自动调度教学设计、PPT、任务单和练习 Agent。' }}</p>
        </div>
      </div>
      <div class="alert-right">
        <button v-if="project.planning.status === 'failed'" type="button" class="retry-btn" @click="emit('retry-planning')">
          <el-icon><RefreshRight /></el-icon> 重试内部规划
        </button>
        <span v-else class="progress-pct-badge">{{ project.planning.progress }}%</span>
      </div>
    </div>

    <div v-if="project.agent_initialization.status !== 'ready'" class="console-alert-banner agent-init">
      <div class="alert-left">
        <span class="alert-badge init">Agent 初始化</span>
        <div class="alert-text">
          <strong>{{ project.agent_initialization.status === 'failed' ? 'Agent 矩阵初始化失败' : '正在初始化 6 大项目专属 Agent 工位' }}</strong>
          <p>{{ project.agent_initialization.error?.message || '正在提取各任务的目标、重点、呈现风格与质量约束。' }}</p>
        </div>
      </div>
      <div class="alert-right">
        <button v-if="project.agent_initialization.status === 'failed'" type="button" class="retry-btn" @click="emit('initialize-agents')">
          <el-icon><RefreshRight /></el-icon> 重新初始化
        </button>
        <span v-else class="progress-pct-badge">{{ project.agent_initialization.progress }}%</span>
      </div>
    </div>

    <!-- 1. Integrated Console Top Bar (Project Identity, Dual Progress, Quality Score, Action CTA) -->
    <header class="console-top-header">
      <div class="console-identity">
        <div class="meta-pills-row">
          <span class="chip id-chip">
            <el-icon><Cpu /></el-icon>
            ID / {{ project.course.id.slice(0, 8).toUpperCase() }}
          </span>
          <span class="chip blueprint-chip">V{{ project.course.current_blueprint_version || 1 }} 蓝图</span>
          <span class="chip memory-chip">
            <el-icon><Memo /></el-icon>
            项目记忆 V{{ memoryRevision }}
          </span>
          <span class="chip active-tag">
            <span class="pulse-dot" />
            6 Agent 并行协同
          </span>
          <button type="button" class="memory-open-btn" @click="emit('open-memory')">
            <el-icon><CollectionTag /></el-icon>
            项目记忆
          </button>
        </div>
        <h1 class="console-title">{{ project.intent.headline || project.course.title }}</h1>
        <p class="console-subtext">
          <span class="subtext-dot" /> 多 Agent 课程交付控制台：六类 Agent 共享项目记忆、并行推进，点击工位卡片可直接进入对话工作台
        </p>
      </div>

      <!-- Right: Dual Progress Engine & Action Box -->
      <div class="console-metrics-cluster">
        <!-- Dual Progress Bars -->
        <div class="progress-cluster-box">
          <!-- Phase 1: AI Generation -->
          <div class="metric-row">
            <div class="metric-label">
              <span class="label-title">阶段一 · AI 矩阵推演</span>
              <strong class="gen-pct">{{ completion }}%</strong>
            </div>
            <div class="track">
              <div class="fill gen-fill" :style="{ width: `${completion}%` }" />
            </div>
          </div>

          <!-- Phase 2: Teacher Delivery Approval -->
          <div class="metric-row">
            <div class="metric-label">
              <span class="label-title">阶段二 · 教师交付确认</span>
              <span class="approval-val">
                <strong>{{ approvedCount }}</strong>/{{ totalTasks }} 项
              </span>
            </div>
            <div class="track">
              <div class="fill approval-fill" :style="{ width: `${(approvedCount / totalTasks) * 100}%` }" />
            </div>
          </div>
        </div>

        <!-- Operations & Action Command Box -->
        <div class="action-dispatch-box">
          <div class="score-badge">
            <div class="score-val-row">
              <span class="score-num">{{ project.quality.score ?? 100 }}</span>
              <span class="score-unit">分</span>
            </div>
            <span class="score-label">AI质量</span>
          </div>

          <div class="dispatch-info">
            <div class="status-indicator-pills">
              <span v-if="reviewCount > 0" class="pill review-pill">
                <el-icon><CircleCheck /></el-icon> {{ reviewCount }} 待确认
              </span>
              <span v-if="attentionCount > 0" class="pill warning-pill">
                <el-icon><Warning /></el-icon> {{ attentionCount }} 需处理
              </span>
              <span v-if="activeCount > 0" class="pill active-pill">
                <span class="mini-pulse" /> {{ activeCount }} 推演中
              </span>
              <span v-if="reviewCount === 0 && attentionCount === 0 && activeCount === 0" class="pill ready-pill">
                <el-icon><Check /></el-icon> 全部完成
              </span>
            </div>

            <button
              v-if="nextActionTask"
              type="button"
              class="primary-action-btn"
              @click="handleNextAction"
            >
              <span>{{ nextActionTask.status === 'review' ? `处理确认：${nextActionTask.display_name}` : `处理：${nextActionTask.display_name}` }}</span>
              <el-icon><ArrowRight /></el-icon>
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- 2. Teaching Blueprint Drawer Bar & Expandable Content -->
    <section class="blueprint-integrated-section">
      <div class="blueprint-toggle-bar" @click="showBlueprint = !showBlueprint">
        <div class="toggle-left">
          <div class="icon-wrap indigo">
            <el-icon><Aim /></el-icon>
          </div>
          <div>
            <span class="toggle-title">已确认的教学设计基准蓝图</span>
            <span class="toggle-subtext">教师输入与 AI 矩阵对齐的元数据与质量规约</span>
          </div>
        </div>

        <div class="toggle-right">
          <div class="quality-badge-pill">
            <el-icon><Check /></el-icon>
            <span>AI 质量合规校验通过</span>
          </div>
          <button type="button" class="expand-btn">
            <span>{{ showBlueprint ? '收起蓝图' : '展开蓝图' }}</span>
            <el-icon><ArrowUp v-if="showBlueprint" /><ArrowDown v-else /></el-icon>
          </button>
        </div>
      </div>

      <!-- Collapsible Body -->
      <div v-show="showBlueprint" class="blueprint-content-body">
        <!-- Core Task & Audience -->
        <div class="blueprint-row task-audience-row">
          <div class="task-block">
            <span class="block-title task">
              <el-icon><Reading /></el-icon> 课程核心任务
            </span>
            <p class="task-headline">{{ project.intent.course_task || '围绕课程主题完成概念理解与基础应用' }}</p>
          </div>

          <div class="audience-block">
            <span class="block-title audience">
              <el-icon><User /></el-icon> 授课对象与场景
            </span>
            <div class="tag-row">
              <span class="chip audience-chip">{{ project.intent.audience }}</span>
              <span class="chip scenario-chip">{{ project.intent.scenario }}</span>
            </div>
          </div>
        </div>

        <!-- Objectives -->
        <div class="blueprint-row objectives-row">
          <span class="block-title obj">
            <el-icon><Aim /></el-icon> 教学目标与能力维度
          </span>
          <div v-if="formattedObjectives.length > 0" class="objectives-list">
            <div v-for="(obj, idx) in formattedObjectives" :key="idx" class="obj-item">
              <span class="obj-index">{{ idx + 1 }}</span>
              <span class="obj-text">{{ obj }}</span>
            </div>
          </div>
          <p v-else class="fallback-text">{{ project.intent.teaching_objectives }}</p>
        </div>

        <!-- Focus Callout & Methods/Style -->
        <div class="blueprint-row bottom-grid">
          <div class="focus-dual-callout">
            <span class="block-title focus">
              <el-icon><Star /></el-icon> 重点与难点攻坚
            </span>
            <div class="focus-boxes">
              <div class="focus-box key-box">
                <span class="focus-tag key-tag">重点</span>
                <p>{{ project.intent.key_points || '核心概念与关键算法步骤' }}</p>
              </div>
              <div class="focus-box diff-box">
                <span class="focus-tag diff-tag">难点</span>
                <p>{{ project.intent.difficulty_points || '在新情境中灵活应用方法' }}</p>
              </div>
            </div>
          </div>

          <div class="method-style-card">
            <div class="ms-row">
              <div class="ms-item">
                <span class="block-title method">
                  <el-icon><Operation /></el-icon> 教学方式
                </span>
                <p class="ms-val">{{ project.intent.teaching_method || '情境驱动、讲练结合' }}</p>
              </div>
              <div class="ms-item">
                <span class="block-title style">
                  <el-icon><CollectionTag /></el-icon> 呈现风格
                </span>
                <p class="ms-val">{{ project.intent.style_requirements || '清晰、可讲解、适合课堂投放' }}</p>
              </div>
            </div>

            <div class="quality-rules-row">
              <span class="rules-label">AI 规则校验：</span>
              <div class="chips-flex">
                <span v-for="(tag, idx) in qualityCheckTags" :key="idx" class="q-chip">
                  <el-icon><Check /></el-icon> {{ tag }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 3. Multi-Agent Production Delivery Pipeline Matrix -->
    <section class="agent-pipeline-integrated-section">
      <header class="pipeline-header">
        <div class="header-left">
          <div class="icon-wrap violet">
            <el-icon><Memo /></el-icon>
          </div>
          <div>
            <div class="title-row">
              <h3>多 Agent 生产交付矩阵</h3>
              <span class="count-chip">6 大专属 Agent 工位</span>
            </div>
            <p class="subtitle">
              共享项目记忆 · 各 Agent 并行生成，工作中按需读取其他 Agent 的产物；悬停任意 Agent 可查看其可读取的参考内容
            </p>
          </div>
        </div>

        <!-- Hover Memory Reference Banner -->
        <div v-if="currentHoveredTask" class="hover-flow-banner">
          <span class="hover-task-name">{{ currentHoveredTask.display_name }}</span>
          <span class="relation-tip">
            <span v-if="getReferenceNames(currentHoveredTask.task_type)" class="rel-tag up">
              可读取 {{ getReferenceNames(currentHoveredTask.task_type) }}
            </span>
            <span v-else class="rel-tag root">独立生成 · 仅依赖蓝图</span>
            <span v-if="currentHoveredTask.last_context_revision" class="rel-tag ref">
              记忆 V{{ currentHoveredTask.last_context_revision }}
            </span>
          </span>
        </div>
      </header>

      <!-- 2D Matrix Grid of 6 Agents -->
      <div class="pipeline-grid">
        <div
          v-for="task in tasks"
          :key="task.id"
          class="agent-card"
          :class="[
            task.status,
            { highlighted: hoveredTaskType === task.task_type }
          ]"
          @mouseenter="hoveredTaskType = task.task_type"
          @mouseleave="hoveredTaskType = null"
          @click="navigateToTask(task.task_type)"
        >
          <!-- Card Top -->
          <div class="card-top">
            <div class="index-row">
              <span class="folio-index">{{ String(task.display_order).padStart(2, '0') }}</span>
            </div>

            <span class="status-pill" :class="task.status">
              <el-icon v-if="task.status === 'approved'"><CircleCheck /></el-icon>
              <el-icon v-else-if="['failed','stale'].includes(task.status)"><Warning /></el-icon>
              <el-icon v-else-if="task.status === 'running'" class="spinning"><Loading /></el-icon>
              <el-icon v-else-if="task.status === 'stale'"><RefreshRight /></el-icon>
              <el-icon v-else><Document /></el-icon>
              <span>
                {{ 
                  task.status === 'review' ? '待教师确认' : 
                  task.status === 'approved' ? '已确认交付' : 
                  task.status === 'stale' ? '项目记忆已更新' : 
                  task.status === 'failed' ? '生成失败' : 
                  task.status === 'running' ? `推演中 ${task.progress}%` : 
                  task.status === 'queued' ? '排队中' : '待生成' 
                }}
              </span>
            </span>
          </div>

          <!-- Card Body -->
          <div class="card-body">
            <h4 class="agent-title">{{ task.display_name }}</h4>
            <div class="agent-meta">
              <span class="agent-spec">
                <el-icon><Cpu /></el-icon>
                {{ task.agent_name }} · V{{ task.agent_profile_version || 1 }}
              </span>
            </div>

            <!-- Activity Strip -->
            <div v-if="task.current_activity && ['running', 'queued'].includes(task.status)" class="activity-strip">
              <span class="activity-pulse" />
              <span class="activity-text">{{ task.current_activity.label }}: {{ task.current_activity.detail || '推理计算中...' }}</span>
            </div>
          </div>

          <!-- Card Progress Track -->
          <div v-if="['running', 'queued'].includes(task.status)" class="card-progress-track">
            <div class="progress-bar-fill" :style="{ width: `${task.progress || 0}%` }" />
          </div>

          <!-- Shared Project Memory Reference -->
          <div class="card-dependencies">
            <span class="dep-chip" :class="{ active: hoveredTaskType === task.task_type }">
              <span class="dot" />
              <template v-if="Object.keys(task.available_sources || {}).length">
                可读取: {{ getReferenceNames(task.task_type) }}
              </template>
              <template v-else>
                独立生成 · 读取项目记忆 V{{ task.last_context_revision || memoryRevision }}
              </template>
            </span>
          </div>

          <!-- Card CTA -->
          <div class="card-cta">
            <span class="cta-label">
              {{ 
                task.status === 'review' ? '进入确认' : 
                task.status === 'stale' ? '读取最新项目记忆' : 
                task.status === 'failed' ? '重新生成' : '进入对话工作台' 
              }}
            </span>
            <div class="cta-icon">
              <el-icon><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.unified-workbench-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  box-shadow: 0 4px 24px rgba(15, 23, 42, 0.04);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* Alert Banners */
.console-alert-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  background: #fffdf5;
  border-bottom: 1px solid #e2e8f0;
}

.console-alert-banner.planning { border-left: 4px solid #4f46e5; }
.console-alert-banner.agent-init { border-left: 4px solid #0284c7; }

.alert-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.alert-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 6px;
  background: #eef2ff;
  color: #4338ca;
  white-space: nowrap;
}

.alert-badge.init {
  background: #e0f2fe;
  color: #0369a1;
}

.alert-text strong {
  font-size: 13.5px;
  font-weight: 700;
  color: #0f172a;
}

.alert-text p {
  margin: 2px 0 0;
  font-size: 12px;
  color: #64748b;
}

.retry-btn {
  border: 0;
  background: #f1f5f9;
  color: #4338ca;
  font-size: 12px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}

.progress-pct-badge {
  font-size: 16px;
  font-weight: 900;
  color: #4f46e5;
}

/* 1. Console Top Header */
.console-top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  padding: 24px 28px;
  background: radial-gradient(130% 160% at 92% 0%, rgba(99, 102, 241, 0.08) 0%, rgba(124, 58, 237, 0.03) 60%, #ffffff 100%);
  border-bottom: 1px solid #f1f5f9;
  position: relative;
}

.console-top-header::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #4f46e5 0%, #7c3aed 40%, #06b6d4 100%);
}

.console-identity {
  flex: 1;
  min-width: 0;
}

.meta-pills-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.chip {
  font-size: 12px;
  font-weight: 700;
  padding: 4px 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: all 180ms ease;
}

.id-chip {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  letter-spacing: 0.02em;
}

.blueprint-chip {
  background: #eef2ff;
  color: #4338ca;
  border: 1px solid #c7d2fe;
}

.memory-open-btn {
  border: 1px solid #ddd6fe;
  background: #ffffff;
  color: #7c3aed;
  font-size: 12px;
  font-weight: 800;
  padding: 3px 12px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  transition: all 150ms ease;
}

.memory-open-btn:hover {
  background: #f5f3ff;
  border-color: #c4b5fd;
}

.memory-chip {
  background: #f5f3ff;
  color: #7c3aed;
  border: 1px solid #ddd6fe;
}

.active-tag {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  animation: pulse-ring 1.8s infinite;
}

.console-title {
  margin: 0 0 8px;
  font-size: clamp(20px, 2vw, 24px);
  font-weight: 800;
  color: #0f172a;
  line-height: 1.35;
  letter-spacing: -0.015em;
}

.console-subtext {
  margin: 0;
  font-size: 13.5px;
  color: #64748b;
  line-height: 1.5;
  display: flex;
  align-items: center;
  gap: 6px;
}

.subtext-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #6366f1;
  flex-shrink: 0;
}

/* Metrics Cluster */
.console-metrics-cluster {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-shrink: 0;
}

.progress-cluster-box {
  width: 240px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 24px;
  border-right: 1px solid #f1f5f9;
}

.metric-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.metric-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
}

.label-title {
  font-weight: 700;
  color: #475569;
}

.gen-pct {
  font-size: 17px;
  font-weight: 900;
  color: #4f46e5;
  font-variant-numeric: tabular-nums;
}

.approval-val {
  font-size: 13px;
  color: #64748b;
  font-weight: 600;
}

.approval-val strong {
  font-size: 17px;
  font-weight: 900;
  color: #059669;
}

.track {
  height: 6px;
  background: #f1f5f9;
  border-radius: 999px;
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.03);
}

.fill {
  height: 100%;
  border-radius: 999px;
  transition: width 400ms cubic-bezier(0.16, 1, 0.3, 1);
}

.fill.gen-fill {
  background: linear-gradient(90deg, #6366f1 0%, #4f46e5 50%, #7c3aed 100%);
}

.fill.approval-fill {
  background: linear-gradient(90deg, #10b981 0%, #059669 100%);
}

/* Action Dispatch Box */
.action-dispatch-box {
  display: flex;
  align-items: center;
  gap: 14px;
  background: rgba(248, 250, 252, 0.85);
  border: 1px solid rgba(226, 232, 240, 0.8);
  padding: 8px 14px;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.03);
  backdrop-filter: blur(12px);
  transition: all 200ms ease;
}

.action-dispatch-box:hover {
  border-color: #c7d2fe;
  box-shadow: 0 6px 20px rgba(79, 70, 229, 0.08);
}

.score-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 66px;
  height: 60px;
  border-radius: 14px;
  background: linear-gradient(135deg, #059669 0%, #10b981 100%);
  color: #ffffff;
  box-shadow: 0 4px 16px rgba(16, 185, 129, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.25);
  flex-shrink: 0;
  padding: 4px;
  box-sizing: border-box;
  transition: transform 200ms ease;
}

.score-badge:hover {
  transform: scale(1.04);
}

.score-val-row {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 1px;
}

.score-num {
  font-size: 21px;
  font-weight: 900;
  line-height: 1;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.score-unit {
  font-size: 11px;
  opacity: 0.9;
  font-weight: 800;
}

.score-label {
  font-size: 10.5px;
  font-weight: 800;
  margin-top: 3px;
  letter-spacing: 0.04em;
  opacity: 0.95;
}

.dispatch-info {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.status-indicator-pills {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pill {
  font-size: 12px;
  font-weight: 800;
  padding: 4px 11px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.review-pill {
  background: #eff6ff;
  color: #2563eb;
  border: 1px solid #bfdbfe;
}

.warning-pill {
  background: #fff1f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

.active-pill {
  background: #f5f3ff;
  color: #7c3aed;
  border: 1px solid #ddd6fe;
}

.ready-pill {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.primary-action-btn {
  border: 0;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  font-size: 13.5px;
  font-weight: 800;
  padding: 8px 18px;
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  box-shadow: 0 3px 12px rgba(79, 70, 229, 0.28);
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
  white-space: nowrap;
}

.primary-action-btn:hover {
  transform: translateY(-1.5px);
  box-shadow: 0 6px 18px rgba(79, 70, 229, 0.38);
}

.primary-action-btn .el-icon {
  transition: transform 180ms ease;
}

.primary-action-btn:hover .el-icon {
  transform: translateX(3px);
}

/* 2. Integrated Blueprint Section */
.blueprint-integrated-section {
  border-bottom: 1px solid #f1f5f9;
  background: #ffffff;
}

.blueprint-toggle-bar {
  padding: 16px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid #f1f5f9;
  transition: background 150ms ease;
}

.blueprint-toggle-bar:hover {
  background: #f1f5f9;
}

.toggle-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 18px;
  flex-shrink: 0;
}

.icon-wrap.indigo { background: #eef2ff; color: #4f46e5; border: 1px solid #c7d2fe; }
.icon-wrap.violet { background: #f5f3ff; color: #7c3aed; border: 1px solid #ddd6fe; }

.toggle-title {
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
}

.toggle-subtext {
  display: block;
  font-size: 13px;
  color: #64748b;
  margin-top: 2px;
}

.toggle-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.quality-badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 4px 14px;
  border-radius: 999px;
}

.expand-btn {
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  font-size: 13px;
  font-weight: 700;
  padding: 5px 14px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  transition: all 150ms ease;
}

.expand-btn:hover {
  background: #e0e7ff;
  color: #4338ca;
  border-color: #c7d2fe;
}

.blueprint-content-body {
  padding: 24px 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 22px;
  background: #ffffff;
}

.block-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14.5px;
  font-weight: 800;
  margin-bottom: 8px;
  letter-spacing: 0.01em;
}

.block-title .el-icon {
  font-size: 16px;
}

.block-title.task { color: #4338ca; }
.block-title.audience { color: #0369a1; }
.block-title.obj { color: #6d28d9; }
.block-title.focus { color: #b45309; }
.block-title.method { color: #047857; }
.block-title.style { color: #0284c7; }

.task-audience-row {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 28px;
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f5f9;
  align-items: start;
}

.task-headline {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.65;
  color: #0f172a;
}

.tag-row { display: flex; flex-direction: column; gap: 8px; margin-top: 2px; }
.chip.audience-chip {
  font-size: 13.5px;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 10px;
  background: #e0f2fe;
  color: #0369a1;
  border: 1px solid #bae6fd;
  line-height: 1.45;
}
.chip.scenario-chip {
  font-size: 13.5px;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 10px;
  background: #f0f9ff;
  color: #0284c7;
  border: 1px solid #e0f2fe;
  display: inline-block;
  width: fit-content;
}

.objectives-row {
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f5f9;
}

.objectives-list { display: flex; flex-direction: column; gap: 10px; margin-top: 6px; }
.obj-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: #f8fafc;
  padding: 12px 18px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  transition: all 180ms ease;
}

.obj-item:hover {
  background: #ffffff;
  border-color: #a5b4fc;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08);
}

.obj-index {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  font-size: 13px;
  font-weight: 900;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.obj-text { font-size: 15px; line-height: 1.55; color: #0f172a; font-weight: 700; }
.fallback-text { margin: 6px 0 0; font-size: 15px; color: #64748b; }

.bottom-grid {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 24px;
}

.focus-boxes { display: flex; flex-direction: column; gap: 10px; margin-top: 6px; }
.focus-box { padding: 12px 16px; border-radius: 12px; display: flex; gap: 12px; align-items: flex-start; }
.focus-box.key-box { background: #fffbeb; border: 1px solid #fde68a; }
.focus-box.diff-box { background: #fff1f2; border: 1px solid #fecdd3; }
.focus-tag { font-size: 12.5px; font-weight: 800; padding: 3px 9px; border-radius: 6px; flex-shrink: 0; margin-top: 1px; }
.key-tag { background: #fef3c7; color: #b45309; }
.diff-tag { background: #ffe4e6; color: #be123c; }
.focus-box p { margin: 0; font-size: 14.5px; line-height: 1.55; color: #1e293b; font-weight: 700; }

.method-style-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 14px;
}

.ms-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.ms-val { margin: 4px 0 0; font-size: 14.5px; color: #1e293b; line-height: 1.6; font-weight: 600; }
.quality-rules-row { display: flex; align-items: center; gap: 10px; border-top: 1px dashed #cbd5e1; padding-top: 10px; }
.rules-label { font-size: 13px; font-weight: 700; color: #475569; white-space: nowrap; }
.chips-flex { display: flex; flex-wrap: wrap; gap: 6px; }
.q-chip { font-size: 12.5px; font-weight: 700; color: #047857; background: #ffffff; border: 1px solid #a7f3d0; padding: 3px 10px; border-radius: 999px; display: inline-flex; align-items: center; gap: 4px; }

/* 3. Integrated Pipeline Matrix Section */
.agent-pipeline-integrated-section {
  padding: 22px 28px 28px;
  background: #ffffff;
}

.pipeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
  gap: 16px;
  flex-wrap: wrap;
}

.header-left { display: flex; align-items: center; gap: 12px; }
.title-row { display: flex; align-items: center; gap: 10px; }
.pipeline-header h3 { margin: 0; font-size: 17.5px; font-weight: 800; color: #0f172a; }
.count-chip { font-size: 12px; font-weight: 700; color: #4338ca; background: #eef2ff; border: 1px solid #c7d2fe; padding: 3px 10px; border-radius: 999px; }
.subtitle { margin: 2px 0 0; font-size: 13px; color: #64748b; }

.hover-flow-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid #c7d2fe;
  padding: 5px 14px;
  border-radius: 999px;
  animation: fadeIn 150ms ease;
}

.hover-task-name { font-size: 13px; font-weight: 800; color: #4f46e5; }
.relation-tip { display: flex; gap: 6px; }
.rel-tag { font-size: 11.5px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.rel-tag.up { background: #e0e7ff; color: #4338ca; }
.rel-tag.ref { background: #f5f3ff; color: #7c3aed; }
.rel-tag.root { background: #f1f5f9; color: #475569; }

/* 2D Pipeline Grid */
.pipeline-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

@media (max-width: 1280px) {
  .pipeline-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 640px) {
  .pipeline-grid { grid-template-columns: 1fr; }
}

.agent-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  cursor: pointer;
  position: relative;
  transition: all 220ms cubic-bezier(0.16, 1, 0.3, 1);
  box-sizing: border-box;
}

.agent-card:hover {
  background: #ffffff;
  border-color: #818cf8;
  box-shadow: 0 8px 24px rgba(79, 70, 229, 0.12);
  transform: translateY(-3px);
}

.agent-card.self {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.25), 0 8px 24px rgba(79, 70, 229, 0.14);
  background: #ffffff;
}

.agent-card.highlighted {
  border-color: #818cf8;
  background: #eef2ff;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.index-row { display: flex; align-items: center; gap: 6px; }
.folio-index { font-size: 13px; font-weight: 900; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #4f46e5; background: #e0e7ff; border: 1px solid #c7d2fe; padding: 2px 8px; border-radius: 999px; }
.relation-badge { font-size: 11px; font-weight: 800; padding: 2px 7px; border-radius: 4px; }
.relation-badge.upstream { background: #4f46e5; color: #ffffff; }
.relation-badge.downstream { background: #c026d3; color: #ffffff; }

.status-pill { display: inline-flex; align-items: center; gap: 4px; font-size: 12.5px; font-weight: 700; padding: 3px 10px; border-radius: 999px; background: #f1f5f9; color: #475569; }
.status-pill.approved { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.status-pill.review { background: #eef2ff; color: #4338ca; border: 1px solid #c7d2fe; }
.status-pill.stale { background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }
.status-pill.failed { background: #fff1f2; color: #b91c1c; border: 1px solid #fecdd3; }
.status-pill.running { background: #eef2ff; color: #4f46e5; border: 1px solid #c7d2fe; }

.card-body { display: flex; flex-direction: column; gap: 5px; }
.agent-title { margin: 0; font-size: 16px; font-weight: 800; color: #0f172a; line-height: 1.35; }
.agent-meta { display: flex; align-items: center; gap: 8px; }
.agent-spec { font-size: 12.5px; color: #64748b; display: inline-flex; align-items: center; gap: 4px; font-weight: 600; }

.activity-strip { display: flex; align-items: center; gap: 6px; background: #eef2ff; border: 1px solid #c7d2fe; padding: 5px 10px; border-radius: 6px; margin-top: 4px; }
.activity-pulse { width: 6px; height: 6px; border-radius: 50%; background: #4f46e5; animation: pulse-ring 1.5s infinite; flex-shrink: 0; }
.activity-text { font-size: 12px; font-weight: 700; color: #4338ca; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.card-progress-track { height: 5px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #4f46e5 0%, #7c3aed 100%); border-radius: 999px; transition: width 300ms ease; }

.card-dependencies { display: flex; align-items: center; }
.dep-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; color: #64748b; background: #ffffff; border: 1px solid #e2e8f0; padding: 4px 10px; border-radius: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.dep-chip.active { background: #e0e7ff; color: #4338ca; border-color: #c7d2fe; }
.dot { width: 5px; height: 5px; border-radius: 50%; background: #94a3b8; flex-shrink: 0; }

.card-cta { display: flex; align-items: center; justify-content: space-between; margin-top: 2px; padding-top: 8px; border-top: 1px dashed #e2e8f0; }
.cta-label { font-size: 13px; font-weight: 700; color: #4f46e5; }
.cta-icon { width: 22px; height: 22px; border-radius: 50%; background: #ffffff; border: 1px solid #e2e8f0; display: grid; place-items: center; color: #64748b; font-size: 11px; transition: all 180ms ease; }
.agent-card:hover .cta-icon { background: #4f46e5; color: #ffffff; border-color: #4f46e5; transform: translateX(2px); }

.spinning { animation: spin 1s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse-ring {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(79, 70, 229, 0.6); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(79, 70, 229, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(79, 70, 229, 0); }
}

@media (max-width: 1100px) {
  .console-top-header { flex-direction: column; align-items: stretch; gap: 16px; }
  .console-metrics-cluster { justify-content: space-between; }
  .progress-cluster-box { flex: 1; }
}

@media (max-width: 640px) {
  .console-metrics-cluster { flex-direction: column; align-items: stretch; }
  .progress-cluster-box { width: 100%; border-right: 0; border-bottom: 1px solid #f1f5f9; padding-right: 0; padding-bottom: 12px; }
  .task-audience-row { grid-template-columns: 1fr; }
  .bottom-grid { grid-template-columns: 1fr; }
  .console-top-header, .blueprint-content-body, .agent-pipeline-integrated-section { padding-left: 14px; padding-right: 14px; }
}
</style>
