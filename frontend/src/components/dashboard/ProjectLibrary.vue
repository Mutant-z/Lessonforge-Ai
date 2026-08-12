<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import type { Course } from '../../types';
import StatusBadge from '../feedback/StatusBadge.vue';
import EmptyState from '../feedback/EmptyState.vue';
import { 
  Plus, 
  Search, 
  ArrowRight, 
  Document, 
  Files, 
  CircleCheck, 
  Operation, 
  Cpu, 
  Select, 
  MagicStick,
  Warning,
  Loading
} from '@element-plus/icons-vue';

const props = defineProps<{
  courses: Course[];
  activeFilter: string;
  searchQuery: string;
}>();

const emit = defineEmits<{
  (e: 'update:activeFilter', filter: string): void;
  (e: 'update:searchQuery', query: string): void;
  (e: 'createSample'): void;
}>();

const router = useRouter();

const filter = computed({
  get: () => props.activeFilter,
  set: (val) => emit('update:activeFilter', val)
});

const search = computed({
  get: () => props.searchQuery,
  set: (val) => emit('update:searchQuery', val)
});

const filteredCourses = computed(() => {
  let list = props.courses;

  if (filter.value !== 'all') {
    if (filter.value === 'running') {
      list = list.filter(x => ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(x.status));
    } else if (filter.value === 'review') {
      list = list.filter(x => ['blueprint_review', 'teacher_review', 'requirement_review', 'draft'].includes(x.status));
    } else if (filter.value === 'completed') {
      list = list.filter(x => x.status === 'completed');
    }
  }

  if (!search.value.trim()) return list;
  const q = search.value.toLowerCase();
  return list.filter(x => 
    x.title.toLowerCase().includes(q) || 
    x.subject.toLowerCase().includes(q) || 
    x.grade_level.toLowerCase().includes(q)
  );
});

// Determine project's current stage text and style
function getProjectStageInfo(status: string) {
  switch (status) {
    case 'blueprint_review':
    case 'teacher_review':
      return { text: '教学设计等待教师确认', type: 'warning' };
    case 'requirement_review':
    case 'draft':
      return { text: '课程需求待核对完善', type: 'info' };
    case 'blueprint_generating':
      return { text: 'Agent 正在生成课程蓝图...', type: 'running' };
    case 'resource_generating':
      return { text: 'Agent 团队并发生成 PPT 与脚本...', type: 'running' };
    case 'quality_checking':
      return { text: 'AI 质量引擎评估校验中...', type: 'running' };
    case 'completed':
      return { text: '全套教学资源已准备完成', type: 'success' };
    case 'failed':
      return { text: '生成失败，等待人工干预', type: 'danger' };
    case 'needs_attention':
      return { text: '部分生成环节需要人工确认', type: 'danger' };
    default:
      return { text: '进行中', type: 'info' };
  }
}

// Determine dynamic CTA button text and route
function getProjectCta(course: Course) {
  const { status, id } = course;
  if (['blueprint_review', 'teacher_review'].includes(status)) {
    return {
      text: '处理待确认',
      target: `/courses/${id}/blueprint`,
      btnType: 'warning'
    };
  }
  if (['blueprint_generating', 'resource_generating', 'quality_checking'].includes(status)) {
    return {
      text: '查看生成进度',
      target: `/courses/${id}/workspace`,
      btnType: 'running'
    };
  }
  if (status === 'completed') {
    return {
      text: '进入工作台',
      target: `/courses/${id}/workspace`,
      btnType: 'primary'
    };
  }
  if (status === 'failed' || status === 'needs_attention') {
    return {
      text: '查看问题',
      target: `/courses/${id}/workspace`,
      btnType: 'danger'
    };
  }
  return {
    text: '进入工作台',
    target: `/courses/${id}/workspace`,
    btnType: 'primary'
  };
}

// Deliverable states for card display based on course status
function getDeliverableStates(status: string) {
  const isDone = status === 'completed';
  const isReview = ['blueprint_review', 'teacher_review'].includes(status);
  const isRunning = ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(status);

  return [
    { label: '教学设计', ready: isDone || isReview, statusText: isReview ? '待确认' : (isDone ? '完成' : (isRunning ? '生成中' : '未开始')), ic: Document, icClass: 'doc' },
    { label: '16:9 PPT', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: Files, icClass: 'ppt' },
    { label: '任务单', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: CircleCheck, icClass: 'sheet' },
    { label: '课后练习', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: Operation, icClass: 'quiz' },
    { label: '视频脚本', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: Cpu, icClass: 'script' },
    { label: '教师逐字稿', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: Document, icClass: 'voice' }
  ];
}

function handleNavigate(path: string) {
  router.push(path);
}
</script>

<template>
  <div class="project-library-container">
    <!-- Section Toolbar -->
    <div class="library-toolbar">
      <div class="toolbar-left">
        <h3 class="toolbar-title">我的微课项目库</h3>
        <span class="count-pill">共 {{ filteredCourses.length }} 门项目</span>
      </div>

      <div class="toolbar-right">
        <!-- Filter Tabs -->
        <div class="status-filter-group">
          <button 
            type="button" 
            class="filter-tab"
            :class="{ active: filter === 'all' }"
            @click="filter = 'all'"
          >
            全部
          </button>
          <button 
            type="button" 
            class="filter-tab"
            :class="{ active: filter === 'running' }"
            @click="filter = 'running'"
          >
            生成中
          </button>
          <button 
            type="button" 
            class="filter-tab"
            :class="{ active: filter === 'review' }"
            @click="filter = 'review'"
          >
            待核对
          </button>
          <button 
            type="button" 
            class="filter-tab"
            :class="{ active: filter === 'completed' }"
            @click="filter = 'completed'"
          >
            已完成
          </button>
        </div>

        <!-- Search Box -->
        <div class="search-input-wrap">
          <el-input
            v-model="search"
            placeholder="搜索课程名称、学科或年级..."
            :prefix-icon="Search"
            clearable
          />
        </div>
      </div>
    </div>

    <!-- 0 Projects: Guided Onboarding -->
    <div v-if="!courses.length" class="empty-onboarding-surface">
      <div class="onboarding-banner">
        <div class="onboarding-icon-wrap">
          <el-icon><MagicStick /></el-icon>
        </div>
        <div class="onboarding-text">
          <h3>开启您的第一门 AI 微课项目</h3>
          <p>输入教学主题和要求，多 Agent 团队将在 3 分钟内为您智能构建完整教学设计、PPT 与配套资源。</p>
        </div>
      </div>

      <div class="onboarding-steps-row">
        <div class="step-box">
          <span class="step-number">01</span>
          <h4 class="step-title">描述教学需求</h4>
          <p class="step-desc">输入主题、学段与教学重点</p>
        </div>
        <div class="step-box">
          <span class="step-number">02</span>
          <h4 class="step-title">确认教学意图</h4>
          <p class="step-desc">教师核对蓝图与大纲设计</p>
        </div>
        <div class="step-box">
          <span class="step-number">03</span>
          <h4 class="step-title">Agent 并发生成</h4>
          <p class="step-desc">PPT、讲稿与试题自动产出</p>
        </div>
        <div class="step-box">
          <span class="step-number">04</span>
          <h4 class="step-title">质检一键导出</h4>
          <p class="step-desc">导出 .pptx/.docx 格式资源</p>
        </div>
      </div>

      <div class="onboarding-cta-row">
        <el-button type="primary" size="large" :icon="Plus" @click="handleNavigate('/courses/new')">
          新建微课项目
        </el-button>

        <el-button size="large" :icon="Select" @click="emit('createSample')">
          一键导入《牛顿第二定律》示范微课
        </el-button>
      </div>
    </div>

    <!-- Empty Search Results -->
    <EmptyState
      v-else-if="!filteredCourses.length"
      title="未找到符合条件的微课项目"
      description="建议您调整搜索关键词或重置状态筛选条件。"
      action-text="重置筛选条件"
      @action="search = ''; filter = 'all';"
    />

    <!-- 1 Project: Wide Card Surface Layout (Full Horizontal Width, No Whitespace) -->
    <div v-else-if="filteredCourses.length === 1" class="single-project-wide-surface">
      <div 
        v-for="course in filteredCourses" 
        :key="course.id" 
        class="wide-course-card"
        @click="handleNavigate(getProjectCta(course).target)"
      >
        <div class="wide-card-header">
          <div class="wide-header-left">
            <div class="meta-tags-strip">
              <span class="tag-pill subject">{{ course.subject }}</span>
              <span class="tag-pill grade">{{ course.grade_level }}</span>
              <span class="tag-pill duration">{{ course.duration_minutes }} 分钟</span>
            </div>
            <h2 class="wide-course-title" :title="course.title">{{ course.title }}</h2>
          </div>

          <div class="wide-header-right">
            <StatusBadge :status="course.status" size="default" />
          </div>
        </div>

        <!-- Current Stage Indicator Strip -->
        <div class="wide-stage-banner" :class="getProjectStageInfo(course.status).type">
          <div class="stage-banner-left">
            <span class="stage-label">当前阶段：</span>
            <span class="stage-text">{{ getProjectStageInfo(course.status).text }}</span>
          </div>

          <div v-if="['blueprint_generating', 'resource_generating'].includes(course.status)" class="stage-live-anim">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>Agent 团队生成中</span>
          </div>
        </div>

        <!-- 6 Deliverables Readiness Surface -->
        <div class="wide-deliverables-grid">
          <div 
            v-for="(deliv, idx) in getDeliverableStates(course.status)" 
            :key="idx" 
            class="wide-deliv-cell"
            :class="{ ready: deliv.ready }"
          >
            <div class="deliv-icon-wrap" :class="deliv.icClass">
              <component :is="deliv.ic" />
            </div>
            <div class="deliv-cell-info">
              <span class="deliv-cell-name">{{ deliv.label }}</span>
              <span class="deliv-cell-status" :class="{ ready: deliv.ready }">{{ deliv.statusText }}</span>
            </div>
          </div>
        </div>

        <!-- Wide Card Footer -->
        <div class="wide-card-footer">
          <span class="footer-time">更新时间：{{ new Date(course.updated_at).toLocaleString('zh-CN') }}</span>

          <button 
            type="button" 
            class="dynamic-cta-btn"
            :class="getProjectCta(course).btnType"
            @click.stop="handleNavigate(getProjectCta(course).target)"
          >
            <span>{{ getProjectCta(course).text }}</span>
            <el-icon><ArrowRight /></el-icon>
          </button>
        </div>
      </div>
    </div>

    <!-- Multi Projects Layout (2~6+ Projects): Responsive Grid -->
    <div v-else class="multi-projects-grid">
      <div 
        v-for="course in filteredCourses" 
        :key="course.id" 
        class="grid-course-card card-hover"
        @click="handleNavigate(getProjectCta(course).target)"
      >
        <div class="grid-card-header">
          <div class="grid-header-meta">
            <div class="meta-tags-strip compact">
              <span class="tag-pill subject">{{ course.subject }}</span>
              <span class="tag-pill grade">{{ course.grade_level }}</span>
              <span class="tag-pill duration">{{ course.duration_minutes }}m</span>
            </div>
            <h4 class="grid-course-title" :title="course.title">{{ course.title }}</h4>
          </div>
          <StatusBadge :status="course.status" size="small" />
        </div>

        <!-- Stage Strip -->
        <div class="grid-stage-badge" :class="getProjectStageInfo(course.status).type">
          <span class="stage-dot"></span>
          <span class="stage-txt">{{ getProjectStageInfo(course.status).text }}</span>
        </div>

        <!-- 6 Deliverables Row -->
        <div class="grid-deliverables-bar">
          <div 
            v-for="(deliv, idx) in getDeliverableStates(course.status)" 
            :key="idx" 
            class="grid-deliv-item"
            :class="{ ready: deliv.ready }"
            :title="`${deliv.label}: ${deliv.statusText}`"
          >
            <component :is="deliv.ic" class="deliv-mini-ic" :class="deliv.icClass" />
            <span class="deliv-mini-txt">{{ deliv.label }}</span>
          </div>
        </div>

        <!-- Grid Footer -->
        <div class="grid-card-footer">
          <span class="footer-time">{{ new Date(course.updated_at).toLocaleDateString('zh-CN') }}</span>

          <button 
            type="button" 
            class="dynamic-cta-btn compact"
            :class="getProjectCta(course).btnType"
            @click.stop="handleNavigate(getProjectCta(course).target)"
          >
            <span>{{ getProjectCta(course).text }}</span>
            <el-icon><ArrowRight /></el-icon>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.project-library-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  flex: 1;
  min-height: 0;
}

/* Toolbar Styles */
.library-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.count-pill {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  background: var(--surface-tertiary);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-filter-group {
  display: flex;
  align-items: center;
  gap: 3px;
  background: var(--surface-secondary);
  padding: 2px;
  border-radius: var(--radius-control);
  border: 1px solid var(--border-soft);
}

.filter-tab {
  border: none;
  background: transparent;
  padding: 4px 10px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--motion-fast);
}

.filter-tab:hover { color: var(--text-primary); }

.filter-tab.active {
  background: var(--surface-primary);
  color: var(--color-primary);
  box-shadow: var(--shadow-xs);
}

.search-input-wrap {
  width: 240px;
}

/* Tags Strip */
.meta-tags-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.meta-tags-strip.compact {
  gap: 4px;
  margin-bottom: 3px;
}

.tag-pill {
  font-size: 11.5px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.tag-pill.subject { background: var(--primary-50); color: var(--primary-700); border: 1px solid var(--primary-200); }
.tag-pill.grade { background: var(--surface-secondary); color: var(--text-secondary); border: 1px solid var(--border-default); }
.tag-pill.duration { background: var(--accent-cyan-soft); color: var(--accent-cyan); border: 1px solid rgba(2, 132, 199, 0.2); }

/* ============================================================ */
/* SINGLE PROJECT: WIDE CARD SURFACE (100% Full Width)          */
/* ============================================================ */
.single-project-wide-surface {
  width: 100%;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.wide-course-card {
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 14px 18px;
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition: all var(--motion-fast) var(--ease-out-smooth);
}

.wide-course-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.wide-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.wide-header-left {
  flex: 1;
  min-width: 0;
}

.wide-course-title {
  margin: 0;
  font-size: 19px;
  font-weight: 900;
  color: var(--text-primary);
  line-height: 1.3;
}

/* Stage Banner */
.wide-stage-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-radius: var(--radius-control);
  font-size: 13px;
  font-weight: 700;
}

.wide-stage-banner.warning {
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
  border: 1px solid rgba(217, 119, 6, 0.2);
}

.wide-stage-banner.running {
  background: var(--accent-violet-soft);
  color: var(--accent-violet);
  border: 1px solid rgba(124, 58, 237, 0.2);
}

.wide-stage-banner.success {
  background: var(--color-success-soft);
  color: var(--success);
  border: 1px solid rgba(22, 163, 74, 0.2);
}

.wide-stage-banner.danger {
  background: var(--color-danger-soft);
  color: var(--danger);
  border: 1px solid rgba(220, 38, 38, 0.2);
}

.wide-stage-banner.info {
  background: var(--surface-tertiary);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
}

.stage-label {
  color: var(--text-muted);
  font-weight: 600;
}

.stage-live-anim {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
}

/* 6 Deliverables Grid */
.wide-deliverables-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
}

.wide-deliv-cell {
  background: var(--surface-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-control);
  padding: 6px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all var(--motion-fast);
}

.wide-deliv-cell.ready {
  background: var(--surface-primary);
  border-color: var(--border-active);
}

.deliv-icon-wrap {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  display: grid;
  place-items: center;
  font-size: 15px;
  flex-shrink: 0;
  background: var(--surface-primary);
  border: 1px solid var(--border-soft);
}

.deliv-icon-wrap.doc { color: var(--primary-600); }
.deliv-icon-wrap.ppt { color: var(--accent-amber); }
.deliv-icon-wrap.sheet { color: var(--accent-mint); }
.deliv-icon-wrap.quiz { color: var(--accent-cyan); }
.deliv-icon-wrap.script { color: var(--accent-violet); }
.deliv-icon-wrap.voice { color: var(--accent-blue); }

.deliv-cell-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.deliv-cell-name {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--text-primary);
  white-space: nowrap;
}

.deliv-cell-status {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-muted);
}

.deliv-cell-status.ready {
  color: var(--accent-mint);
}

/* Wide Footer */
.wide-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px dashed var(--border-default);
}

.footer-time {
  font-size: 12.5px;
  color: var(--text-muted);
  font-weight: 500;
}

/* Dynamic Primary CTA Button Styles */
.dynamic-cta-btn {
  border: none;
  padding: 6px 16px;
  border-radius: var(--radius-control);
  font-size: 13.5px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.dynamic-cta-btn.compact {
  padding: 5px 12px;
  font-size: 12.5px;
}

.dynamic-cta-btn.primary {
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  box-shadow: var(--shadow-glow-primary);
}

.dynamic-cta-btn.warning {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: #ffffff;
  box-shadow: 0 4px 14px rgba(217, 119, 6, 0.3);
}

.dynamic-cta-btn.running {
  background: linear-gradient(135deg, #7c3aed 0%, #6366f1 100%);
  color: #ffffff;
  box-shadow: var(--shadow-glow-agent);
}

.dynamic-cta-btn.danger {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: #ffffff;
  box-shadow: 0 4px 14px rgba(220, 38, 38, 0.25);
}

.dynamic-cta-btn:hover {
  opacity: 0.94;
  transform: translateX(2px);
}

/* ============================================================ */
/* MULTI PROJECTS: RESPONSIVE GRID (2 ~ 6+ Items)               */
/* ============================================================ */
.multi-projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
  width: 100%;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.grid-course-card {
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 14px 16px;
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 10px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.grid-course-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.grid-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.grid-header-meta {
  flex: 1;
  min-width: 0;
}

.grid-course-title {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.grid-stage-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 700;
}

.grid-stage-badge.warning { background: var(--accent-amber-soft); color: var(--accent-amber); }
.grid-stage-badge.running { background: var(--accent-violet-soft); color: var(--accent-violet); }
.grid-stage-badge.success { background: var(--color-success-soft); color: var(--success); }
.grid-stage-badge.danger { background: var(--color-danger-soft); color: var(--danger); }
.grid-stage-badge.info { background: var(--surface-tertiary); color: var(--text-secondary); }

.stage-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.grid-deliverables-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  padding: 6px 8px;
  background: var(--surface-secondary);
  border-radius: var(--radius-control);
  border: 1px solid var(--border-soft);
}

.grid-deliv-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-muted);
}

.grid-deliv-item.ready {
  color: var(--accent-mint);
}

.deliv-mini-ic {
  font-size: 12px;
}

.deliv-mini-txt {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.grid-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px dashed var(--border-default);
}

/* Onboarding Surface for 0 Courses */
.empty-onboarding-surface {
  padding: 20px 24px;
  background: var(--surface-secondary);
  border-radius: var(--radius-card);
  border: 1.5px dashed var(--border-default);
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.onboarding-banner {
  display: flex;
  align-items: center;
  gap: 14px;
}

.onboarding-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-control);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  font-size: 20px;
}

.onboarding-text h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 900;
  color: var(--text-primary);
}

.onboarding-text p {
  margin: 2px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

.onboarding-steps-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.step-box {
  padding: 10px 12px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-control);
}

.step-number {
  font-size: 12px;
  font-weight: 900;
  color: var(--color-primary);
}

.step-title {
  margin: 2px 0 1px;
  font-size: 14px;
  font-weight: 800;
  color: var(--text-primary);
}

.step-desc {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.onboarding-cta-row {
  display: flex;
  gap: 12px;
}

@media (max-width: 1280px) {
  .wide-deliverables-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .onboarding-steps-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .wide-deliverables-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
