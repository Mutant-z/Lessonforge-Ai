<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  Aim,
  ArrowRight,
  Check,
  CircleCheck,
  Cpu,
  DataAnalysis,
  Document,
  Reading,
  Star,
  Warning,
} from '@element-plus/icons-vue';
import { useProjectStore } from '../stores/project';
import ProjectShell from '../components/project/ProjectShell.vue';

const route = useRoute();
const router = useRouter();
const store = useProjectStore();
const courseId = route.params.id as string;

const approvedCount = computed(() => store.tasks.filter(task => task.status === 'approved').length);
const activeCount = computed(() => store.tasks.filter(task => ['queued', 'running'].includes(task.status)).length);
const attentionCount = computed(() => store.tasks.filter(task => ['failed', 'stale'].includes(task.status)).length);

onMounted(() => store.open(courseId));
onUnmounted(() => store.disconnect());
</script>

<template>
  <div v-if="store.loading && !store.project" class="project-loading">
    <el-skeleton :rows="8" animated />
  </div>
  <ProjectShell v-else-if="store.project">
    <div class="overview-scroll">
      <!-- Top Hero Lead Card -->
      <section class="overview-hero-card">
        <div class="hero-main">
          <div class="hero-badge-row">
            <span class="project-id-chip">
              <el-icon><Cpu /></el-icon>
              PROJECT / {{ store.project.course.id.slice(0, 8).toUpperCase() }}
            </span>
            <span class="status-active-tag">6 个 Agent 矩阵协同中</span>
          </div>
          <h2>{{ store.project.intent.headline }}</h2>
          <p>专属 Agent 矩阵正在按任务依赖联动推演并维护交付文件。点击下方任意任务模块即可进入该 Agent 独立对话工作台进行调整。</p>
        </div>

        <div class="hero-progress-block">
          <div class="progress-ring-box">
            <strong>{{ store.completion }}%</strong>
            <div class="progress-bar-track">
              <div class="progress-bar-fill" :style="{ width: `${store.completion}%` }" />
            </div>
          </div>
          <span class="progress-label">整体联调生成进度</span>
        </div>
      </section>

      <!-- Planning Alert (if applicable) -->
      <section v-if="store.project.planning.status !== 'ready'" class="planning-card">
        <div class="planning-index">00</div>
        <div class="planning-info">
          <strong>{{ store.project.planning.status === 'failed' ? '内部规划失败' : '正在将教学意图转化为任务上下文' }}</strong>
          <p>{{ store.project.planning.error?.message || '完成后将自动启动教学设计、PPT、任务单和练习 Agent。' }}</p>
          <button v-if="store.project.planning.status === 'failed'" type="button" class="planning-retry" @click="store.retryPlanning(courseId)">
            重试内部规划
          </button>
        </div>
        <div class="planning-pct">{{ store.project.planning.progress }}%</div>
      </section>

      <section v-if="store.project.agent_initialization.status !== 'ready'" class="planning-card agent-init-card">
        <div class="planning-index">AI</div>
        <div class="planning-info">
          <strong>{{ store.project.agent_initialization.status === 'failed' ? '六个专属 Agent 初始化失败' : '正在初始化六个项目专属 Agent' }}</strong>
          <p>{{ store.project.agent_initialization.error?.message || '正在从教师意图、课程蓝图与参考材料中提取各任务的目标、重点、风格和质量约束。' }}</p>
          <button v-if="store.project.agent_initialization.status === 'failed'" type="button" class="planning-retry" @click="store.initializeAgents(courseId)">
            重新初始化六个 Agent
          </button>
        </div>
        <div class="planning-pct">{{ store.project.agent_initialization.progress }}%</div>
      </section>

      <!-- Grid Layout: Intent Matrix + Summary Stats -->
      <div class="overview-grid">
        <!-- Left: Confirmed Intent Matrix Card -->
        <section class="intent-card">
          <header class="card-header">
            <div class="header-title-box">
              <el-icon class="header-icon"><Aim /></el-icon>
              <h3>已确认的教学意图</h3>
            </div>
            <span class="version-pill">V{{ store.project.course.current_blueprint_version || 1 }}</span>
          </header>

          <div class="intent-items-grid">
            <div class="intent-box">
              <span class="intent-label"><el-icon><Reading /></el-icon> 课程核心任务</span>
              <p class="intent-value">{{ store.project.intent.course_task || '围绕课程主题完成理解与基础应用' }}</p>
            </div>

            <div class="intent-box">
              <span class="intent-label"><el-icon><DataAnalysis /></el-icon> 授课对象与场景</span>
              <p class="intent-value">{{ store.project.intent.audience }} · {{ store.project.intent.scenario }}</p>
            </div>

            <div class="intent-box full-width">
              <span class="intent-label"><el-icon><Aim /></el-icon> 教学目标</span>
              <p class="intent-value">{{ store.project.intent.teaching_objectives || '由内部规划结合课程任务形成可观察学习目标' }}</p>
            </div>

            <div class="intent-box full-width">
              <span class="intent-label"><el-icon><Star /></el-icon> 重点与难点</span>
              <p class="intent-value">
                <strong>重点：</strong>{{ store.project.intent.key_points || '核心概念与关键关系' }}<br>
                <strong>难点：</strong>{{ store.project.intent.difficulty_points || '在新情境中应用方法' }}
              </p>
            </div>

            <div class="intent-box">
              <span class="intent-label"><el-icon><Cpu /></el-icon> 教学方式</span>
              <p class="intent-value">{{ store.project.intent.teaching_method || '情境驱动、讲练结合' }}</p>
            </div>

            <div class="intent-box">
              <span class="intent-label"><el-icon><Document /></el-icon> 呈现风格</span>
              <p class="intent-value">{{ store.project.intent.style_requirements || '清晰、可讲解、适合课堂投放' }}</p>
            </div>
          </div>
        </section>

        <!-- Right: Project Summary & Quality Score Card -->
        <aside class="summary-card">
          <header class="card-header">
            <div class="header-title-box">
              <el-icon class="header-icon"><DataAnalysis /></el-icon>
              <h3>项目协作状态</h3>
            </div>
          </header>

          <div class="summary-content">
            <div class="approved-metric-box">
              <div class="metric-num">
                <strong>{{ approvedCount }}</strong>
                <span>/ 6 项已确认</span>
              </div>
              <div class="metric-bar">
                <div class="metric-fill" :style="{ width: `${(approvedCount / 6) * 100}%` }" />
              </div>
            </div>

            <div class="stat-list-group">
              <div class="stat-row">
                <span class="stat-key">运行中的 Agent</span>
                <span class="stat-val active">{{ activeCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-key">需要教师处理</span>
                <span class="stat-val" :class="{ warn: attentionCount > 0 }">{{ attentionCount }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-key">质量得分</span>
                <span class="stat-val score">
                  {{ store.project.quality.score ?? '—' }}
                  <small v-if="store.project.quality.score">分</small>
                </span>
              </div>
            </div>

            <div class="quality-summary-box">
              <span class="quality-tag"><el-icon><Check /></el-icon> 质量校验</span>
              <p>{{ store.project.quality.summary }}</p>
            </div>
          </div>
        </aside>
      </div>

      <!-- Task Deliverable Grid Section -->
      <section class="task-deliverables-section">
        <header class="section-header">
          <div>
            <h3>交付任务模块</h3>
            <p>点击进入对应 Agent 的智能工作台进行对话微调</p>
          </div>
        </header>

        <div class="task-cards-list">
          <button
            v-for="task in store.tasks"
            :key="task.id"
            type="button"
            class="task-card-item"
            @click="router.push(`/courses/${courseId}/tasks/${task.task_type}`)"
          >
            <div class="task-card-left">
              <div class="task-folio-badge">{{ String(task.display_order).padStart(2, '0') }}</div>
              <div class="task-meta">
                <strong>{{ task.display_name }}</strong>
                <span class="agent-name-tag">{{ task.agent_name }}<template v-if="task.agent_profile_version"> · 专属配置 V{{ task.agent_profile_version }}</template></span>
              </div>
            </div>

            <div class="task-card-mid">
              <span class="task-dep-text">
                {{ task.dependency_types.length ? `依赖：${task.dependency_types.map(type => store.tasks.find(x => x.task_type === type)?.display_name).join('、')}` : '内部规划完成后自动启动' }}
              </span>
            </div>

            <div class="task-card-right">
              <span class="status-pill" :class="task.status">
                <el-icon v-if="task.status === 'approved'"><CircleCheck /></el-icon>
                <el-icon v-else-if="['failed','stale'].includes(task.status)"><Warning /></el-icon>
                <el-icon v-else><Document /></el-icon>
                {{ task.status === 'review' ? '待确认' : task.status === 'approved' ? '已确认' : task.status === 'stale' ? '待同步' : task.status === 'failed' ? '需重试' : task.status === 'running' ? `${task.progress}%` : task.status === 'queued' ? '排队中' : '等待依赖' }}
              </span>
              <el-icon class="arrow-icon"><ArrowRight /></el-icon>
            </div>
          </button>
        </div>
      </section>
    </div>
  </ProjectShell>
</template>

<style scoped>
.project-loading {
  padding: 32px;
}

.overview-scroll {
  height: 100%;
  overflow-y: auto;
  padding: 24px 28px 40px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

/* Hero Lead Card */
.overview-hero-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 28px;
  padding: 24px 28px;
  background: #ffffff;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 18px);
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.04));
}

.hero-main {
  display: flex;
  flex-direction: column;
}

.hero-badge-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.project-id-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 800;
  color: var(--primary-700, #4338ca);
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--primary-200, #c7d2fe);
  padding: 2px 10px;
  border-radius: 999px;
  letter-spacing: 0.05em;
}

.status-active-tag {
  font-size: 11px;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 2px 10px;
  border-radius: 999px;
}

.hero-main h2 {
  margin: 4px 0 8px;
  font-size: clamp(22px, 2.5vw, 32px);
  font-weight: 800;
  line-height: 1.25;
  color: var(--text-primary, #0f172a);
}

.hero-main p {
  margin: 0;
  color: var(--text-muted, #64748b);
  font-size: 13.5px;
  line-height: 1.6;
}

.hero-progress-block {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-end;
  border-left: 1px solid #f1f5f9;
  padding-left: 24px;
}

.progress-ring-box {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.progress-ring-box strong {
  font-size: 42px;
  font-weight: 900;
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.progress-bar-track {
  width: 100%;
  height: 6px;
  background: #f1f5f9;
  border-radius: 999px;
  margin-top: 10px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%);
  border-radius: 999px;
  transition: width 300ms ease;
}

.progress-label {
  margin-top: 8px;
  color: var(--text-muted, #64748b);
  font-size: 12px;
  font-weight: 600;
}

/* Planning Line */
.planning-card {
  display: grid;
  grid-template-columns: 44px 1fr auto;
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  background: #ffffff;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: 14px;
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.04));
}

.planning-index {
  font-size: 20px;
  font-weight: 900;
  color: var(--primary-600, #4f46e5);
}

.planning-info strong {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text-primary, #0f172a);
}

.planning-info p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.planning-retry {
  margin-top: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--primary-600, #4f46e5);
  font-weight: 700;
  cursor: pointer;
}

.planning-pct {
  font-size: 18px;
  font-weight: 800;
  color: var(--primary-600, #4f46e5);
}

/* Overview Grid */
.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 20px;
}

.intent-card, .summary-card {
  background: #ffffff;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 18px);
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.04));
  overflow: hidden;
}

.card-header {
  min-height: 52px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.header-title-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-icon {
  color: var(--primary-600, #4f46e5);
  font-size: 16px;
}

.header-title-box h3 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.version-pill {
  font-size: 11px;
  font-weight: 800;
  color: var(--primary-700, #4338ca);
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--primary-200, #c7d2fe);
  padding: 1px 8px;
  border-radius: 999px;
}

.intent-items-grid {
  padding: 18px 20px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.intent-box {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 12px 14px;
}

.intent-box.full-width {
  grid-column: span 2;
}

.intent-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-muted, #64748b);
  margin-bottom: 4px;
}

.intent-value {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-primary, #0f172a);
}

.summary-content {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.approved-metric-box {
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 12px;
  padding: 14px;
}

.metric-num {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.metric-num strong {
  font-size: 32px;
  font-weight: 900;
  color: var(--primary-600, #4f46e5);
  line-height: 1;
}

.metric-num span {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  font-weight: 600;
}

.metric-bar {
  height: 5px;
  background: #e2e8f0;
  border-radius: 999px;
  margin-top: 10px;
  overflow: hidden;
}

.metric-fill {
  height: 100%;
  background: var(--primary-600, #4f46e5);
  border-radius: 999px;
  transition: width 300ms ease;
}

.stat-list-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.stat-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
}

.stat-key {
  color: var(--text-muted, #64748b);
  font-weight: 600;
}

.stat-val {
  font-weight: 700;
  color: var(--text-primary, #0f172a);
}

.stat-val.active { color: var(--primary-600, #4f46e5); }
.stat-val.warn { color: #dc2626; }
.stat-val.score { font-size: 16px; font-weight: 800; color: #059669; }

.quality-summary-box {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 12px;
  padding: 12px;
}

.quality-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 800;
  color: #047857;
  margin-bottom: 4px;
}

.quality-summary-box p {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: #065f46;
}

/* Deliverables Section */
.task-deliverables-section {
  background: #ffffff;
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 18px);
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.04));
  padding: 20px;
}

.section-header {
  margin-bottom: 14px;
}

.section-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.section-header p {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.task-cards-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-card-item {
  width: 100%;
  display: grid;
  grid-template-columns: 220px 1fr auto;
  align-items: center;
  gap: 16px;
  padding: 12px 18px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  border-radius: 14px;
  cursor: pointer;
  text-align: left;
  transition: all 180ms ease;
}

.task-card-item:hover {
  background: #ffffff;
  border-color: var(--primary-300, #a5b4fc);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.1);
  transform: translateY(-1px);
}

.task-card-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.task-folio-badge {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%);
  color: #ffffff;
  font-size: 14px;
  font-weight: 800;
  display: grid;
  place-items: center;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.22);
}

.task-meta {
  display: flex;
  flex-direction: column;
}

.task-meta strong {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #0f172a);
}

.agent-name-tag {
  font-size: 11px;
  color: var(--text-muted, #64748b);
}

.task-card-mid {
  min-width: 0;
}

.task-dep-text {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

.task-card-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
}

.status-pill.approved { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.status-pill.review { background: #eef2ff; color: #4338ca; border: 1px solid #c7d2fe; }
.status-pill.stale { background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }
.status-pill.failed { background: #fff1f2; color: #b91c1c; border: 1px solid #fecdd3; }

.arrow-icon {
  color: #94a3b8;
  font-size: 16px;
  transition: transform 150ms ease;
}

.task-card-item:hover .arrow-icon {
  color: var(--primary-600, #4f46e5);
  transform: translateX(2px);
}

@media (max-width: 900px) {
  .overview-hero-card, .overview-grid { grid-template-columns: 1fr; }
  .hero-progress-block { border-left: 0; border-top: 1px solid #f1f5f9; padding-left: 0; padding-top: 16px; align-items: flex-start; }
  .task-card-item { grid-template-columns: 1fr auto; }
  .task-card-mid { display: none; }
}

@media (max-width: 600px) {
  .intent-items-grid { grid-template-columns: 1fr; }
  .intent-box.full-width { grid-column: span 1; }
}
</style>
