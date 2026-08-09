<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { useCourseStore } from '../stores/courses';
import { useCourseIntakeStore } from '../stores/courseIntake';
import StatusBadge from '../components/feedback/StatusBadge.vue';
import EmptyState from '../components/feedback/EmptyState.vue';

// Visual Landing Page Components for Guests
import AmbientBackground from '../components/visual/AmbientBackground.vue';
import HomeNavbar from '../components/home/HomeNavbar.vue';
import HomeHero from '../components/home/HomeHero.vue';
import ResourceBentoGrid from '../components/home/ResourceBentoGrid.vue';
import CourseExamplePanel from '../components/home/CourseExamplePanel.vue';
import HomeCTA from '../components/home/HomeCTA.vue';
import HomeFooter from '../components/home/HomeFooter.vue';

import { 
  Plus, 
  FolderOpened, 
  Cpu, 
  CircleCheck, 
  Search,
  Files,
  Document,
  ArrowRight,
  Select,
  MagicStick,
  Bell,
  Operation,
  VideoPlay
} from '@element-plus/icons-vue';

const auth = useAuthStore();
const store = useCourseStore();
const intake = useCourseIntakeStore();
const router = useRouter();
const route = useRoute();

const searchQuery = ref((route.query.search as string) || '');
const activeStatusFilter = ref('all');
const quickPromptInput = ref('');
const startingIntake = ref(false);

onMounted(async () => {
  if (auth.user) {
    await store.load();
  }
});

const counts = computed(() => {
  const total = store.items.length;
  const running = store.items.filter(x => ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(x.status)).length;
  const review = store.items.filter(x => ['blueprint_review', 'teacher_review', 'requirement_review', 'draft'].includes(x.status)).length;
  const done = store.items.filter(x => x.status === 'completed').length;
  const completionRate = total > 0 ? Math.round((done / total) * 100) : 0;
  const savedHours = Math.round(total * 4.5);
  return { all: total, running, review, done, completionRate, savedHours };
});

const filteredCourses = computed(() => {
  let list = store.items;

  if (activeStatusFilter.value !== 'all') {
    if (activeStatusFilter.value === 'running') {
      list = list.filter(x => ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(x.status));
    } else if (activeStatusFilter.value === 'review') {
      list = list.filter(x => ['blueprint_review', 'teacher_review', 'requirement_review', 'draft'].includes(x.status));
    } else if (activeStatusFilter.value === 'completed') {
      list = list.filter(x => x.status === 'completed');
    }
  }

  if (!searchQuery.value.trim()) return list;
  const q = searchQuery.value.toLowerCase();
  return list.filter(x => 
    x.title.toLowerCase().includes(q) || 
    x.subject.toLowerCase().includes(q) || 
    x.grade_level.toLowerCase().includes(q)
  );
});

// Pending actions items computed inline
const pendingActionItems = computed(() => {
  const list: any[] = [];
  store.items.forEach(course => {
    if (['blueprint_review', 'teacher_review'].includes(course.status)) {
      list.push({
        id: course.id,
        title: course.title,
        type: 'blueprint',
        tag: '待确认蓝图',
        target: `/courses/${course.id}/blueprint`
      });
    } else if (course.status === 'draft' || course.status === 'requirement_review') {
      list.push({
        id: course.id,
        title: course.title,
        type: 'draft',
        tag: '草稿待完善',
        target: `/courses/${course.id}/workspace`
      });
    }
  });
  return list;
});

// Running agent items computed inline
const runningAgentItems = computed(() => {
  return store.items.filter(x => ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(x.status));
});

const recentEditedCourse = computed(() => {
  if (!store.items.length) return null;
  return store.items[0];
});

async function handleQuickIntakeSubmit() {
  if (!quickPromptInput.value.trim() || startingIntake.value) return;
  startingIntake.value = true;
  try {
    const session = await intake.create(null);
    await intake.send(quickPromptInput.value.trim());
    await router.push({ path: '/courses/new', query: { session: session.id } });
  } catch (e) {
    router.push('/courses/new');
  } finally {
    startingIntake.value = false;
  }
}

function applyQuickPromptChip(text: string) {
  quickPromptInput.value = text;
}

async function createSampleCourse() {
  try {
    const newCourse = await store.create({
      title: '《牛顿第二定律：加速度与力的关系》',
      subject: '物理',
      grade_level: '高一',
      duration_minutes: 15,
      target_audience: '高一学生',
      teaching_objectives: ['掌握牛顿第二定律表达式 F=ma', '理解加速度与合外力正比关系'],
      key_knowledge_points: ['牛顿第二定律', 'F=ma 矢量性', '国际单位制推导'],
      pedagogical_approach: '实验探究引导式',
      raw_materials: '教案课本参考材料'
    });
    router.push(`/courses/${newCourse.id}/blueprint`);
  } catch (e) {
    router.push('/courses/new');
  }
}
</script>

<template>
  <div class="dashboard-root-view">
    <!-- 1. Guest Public Landing Page -->
    <div v-if="!auth.user" class="landing-page-shell">
      <AmbientBackground theme="light" />
      <HomeNavbar />
      
      <main class="landing-body">
        <HomeHero />
        <ResourceBentoGrid id="resources" />
        <CourseExamplePanel id="examples" />
        <HomeCTA />
      </main>

      <HomeFooter />
    </div>

    <!-- 2. Single-Page (100vh Viewport) Simple & Clean Dashboard -->
    <div v-else class="workspace-page-container animate-fade-in">
      <div class="master-workbench-card">
        
        <!-- Top Navigation / Title Strip -->
        <div class="master-header-strip">
          <div class="header-titles">
            <span class="eyebrow-tag">DASHBOARD</span>
            <h1 class="main-title">教学资源项目完成度看板</h1>
            <span class="subtitle-text">全套微课资源研发进度与 Agent 生成监控</span>
          </div>

          <div class="header-action">
            <el-button type="primary" size="default" :icon="Plus" class="create-main-btn" @click="router.push('/courses/new')">
              新建微课项目
            </el-button>
          </div>
        </div>

        <!-- Metric Band: Simple Progress & Clean Stat Badges -->
        <div class="master-overview-band">
          <div class="overview-banner-card">
            <div class="banner-welcome">
              <div class="welcome-user-info">
                <h2>欢迎回来，{{ auth.user?.username || '老师' }}！</h2>
                <p>微课资源项目总体完成进度与交付物装配状态</p>
              </div>

              <div class="banner-progress-summary">
                <div class="overall-progress-header">
                  <span class="progress-title">微课全套产物打包就绪率</span>
                  <span class="progress-percentage-num">{{ counts.completionRate }}%</span>
                </div>
                <div class="overall-progress-track">
                  <div class="overall-progress-fill" :style="{ width: `${counts.completionRate}%` }"></div>
                </div>
              </div>
            </div>

            <div class="banner-stats-row">
              <div class="stat-pill-card" :class="{ active: activeStatusFilter === 'all' }" @click="activeStatusFilter = 'all'">
                <span class="stat-num blue">{{ counts.all }}</span>
                <span class="stat-label">全部微课项目</span>
              </div>

              <div class="stat-pill-card" :class="{ active: activeStatusFilter === 'completed' }" @click="activeStatusFilter = 'completed'">
                <span class="stat-num success">{{ counts.done }}</span>
                <span class="stat-label">已完成打包</span>
              </div>

              <div class="stat-pill-card" :class="{ active: activeStatusFilter === 'review' }" @click="activeStatusFilter = 'review'">
                <span class="stat-num warning">{{ counts.review }}</span>
                <span class="stat-label">待审核确认</span>
              </div>

              <div class="stat-pill-card" :class="{ active: activeStatusFilter === 'running' }" @click="activeStatusFilter = 'running'">
                <span class="stat-num agent">{{ counts.running }}</span>
                <span class="stat-label">Agent 生成中</span>
              </div>

              <div class="stat-pill-card static">
                <span class="stat-num mint">{{ counts.savedHours }}<small>h</small></span>
                <span class="stat-label">预计节省研发工时</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Clean AI Quick Creation Bar -->
        <div class="inline-ai-quick-strip">
          <div class="quick-prompt-input-row">
            <div class="prompt-input-wrapper">
              <el-icon class="magic-input-icon"><MagicStick /></el-icon>
              <input 
                v-model="quickPromptInput"
                type="text" 
                class="inline-prompt-input"
                placeholder="输入教学主题一键生成微课，例如：高一物理《牛顿第二定律》，时长 15 分钟…" 
                @keyup.enter="handleQuickIntakeSubmit"
              />
              <button 
                type="button" 
                class="inline-send-btn"
                :disabled="!quickPromptInput.trim() || startingIntake"
                @click="handleQuickIntakeSubmit"
              >
                <span>AI 极速生成</span>
                <el-icon><ArrowRight /></el-icon>
              </button>
            </div>

            <div v-if="recentEditedCourse" class="recent-resume-box">
              <button 
                type="button" 
                class="resume-pill-btn"
                @click="router.push(`/courses/${recentEditedCourse.id}/workspace`)"
              >
                <el-icon><VideoPlay /></el-icon>
                <span>继续编辑：{{ recentEditedCourse.title.length > 10 ? recentEditedCourse.title.slice(0, 10) + '...' : recentEditedCourse.title }}</span>
              </button>
            </div>
          </div>

          <div class="prompt-chips-row">
            <span class="chips-label">快捷示例：</span>
            <span class="chip-tag" @click="applyQuickPromptChip('高一物理《牛顿第二定律》，时长 15 分钟')">高一物理《牛顿第二定律》</span>
            <span class="chip-tag" @click="applyQuickPromptChip('初中数学《勾股定理及其应用》，互动教学')">初中数学《勾股定理》</span>
            <span class="chip-tag" @click="applyQuickPromptChip('高中化学《氧化还原反应核心规律解析》')">高中化学《氧化还原反应》</span>
          </div>
        </div>

        <!-- Status Alert Notification Strip (If any) -->
        <div v-if="pendingActionItems.length || runningAgentItems.length" class="inline-status-alert-strip">
          <div v-if="pendingActionItems.length" class="status-alert-item warning">
            <el-icon class="alert-ic"><Bell /></el-icon>
            <span class="alert-txt">今日待处理：有 {{ pendingActionItems.length }} 门微课等待教师确认蓝图或审核</span>
            <button type="button" class="alert-action-link" @click="router.push(pendingActionItems[0].target)">
              <span>立即处理</span>
              <el-icon><ArrowRight /></el-icon>
            </button>
          </div>

          <div v-if="runningAgentItems.length" class="status-alert-item agent">
            <span class="pulse-live-dot animate-pulse"></span>
            <span class="alert-txt">Agent 队列：{{ runningAgentItems.length }} 门微课正由 Agent 团队并发生成中</span>
            <button type="button" class="alert-action-link" @click="activeStatusFilter = 'running'">
              <span>查看生成状态</span>
            </button>
          </div>
        </div>

        <!-- Main Workspace Course Projects List -->
        <div class="master-body-split">
          <div class="master-courses-col">
            <div class="dashboard-content-panel">
              
              <div class="dashboard-toolbar">
                <div class="toolbar-left">
                  <h3 class="lf-card-title">我的微课项目库</h3>
                  <span class="courses-count-pill">共 {{ filteredCourses.length }} 门</span>
                </div>

                <div class="toolbar-right">
                  <div class="status-filter-pills">
                    <button 
                      type="button" 
                      class="filter-pill"
                      :class="{ active: activeStatusFilter === 'all' }"
                      @click="activeStatusFilter = 'all'"
                    >
                      全部
                    </button>
                    <button 
                      type="button" 
                      class="filter-pill"
                      :class="{ active: activeStatusFilter === 'running' }"
                      @click="activeStatusFilter = 'running'"
                    >
                      生成中
                    </button>
                    <button 
                      type="button" 
                      class="filter-pill"
                      :class="{ active: activeStatusFilter === 'review' }"
                      @click="activeStatusFilter = 'review'"
                    >
                      待核对
                    </button>
                    <button 
                      type="button" 
                      class="filter-pill"
                      :class="{ active: activeStatusFilter === 'completed' }"
                      @click="activeStatusFilter = 'completed'"
                    >
                      已完成
                    </button>
                  </div>

                  <div class="search-box">
                    <el-input 
                      v-model="searchQuery" 
                      placeholder="搜索课程、学科或年级..." 
                      :prefix-icon="Search"
                      size="small"
                      clearable 
                    />
                  </div>
                </div>
              </div>

              <div class="courses-body-content">
                <!-- Zero Courses Guided Onboarding State -->
                <div v-if="!store.items.length" class="empty-onboarding-panel">
                  <div class="onboarding-header">
                    <div class="onboarding-icon">
                      <el-icon><MagicStick /></el-icon>
                    </div>
                    <div class="onboarding-title-wrap">
                      <h3>开启您的第一门 AI 微课项目</h3>
                      <p>只需输入教学主题，多 Agent 团队将在 3 分钟内为您构建全套交付资源。</p>
                    </div>
                  </div>

                  <div class="onboarding-steps-grid">
                    <div class="step-card">
                      <span class="step-num">01</span>
                      <h4>描述教学要求</h4>
                      <p>主题、学段与重点</p>
                    </div>
                    <div class="step-card">
                      <span class="step-num">02</span>
                      <h4>确认教学意图</h4>
                      <p>核对 Agent 的理解</p>
                    </div>
                    <div class="step-card">
                      <span class="step-num">03</span>
                      <h4>Agent 并发生成</h4>
                      <p>PPT与脚本自动产出</p>
                    </div>
                    <div class="step-card">
                      <span class="step-num">04</span>
                      <h4>质检一键导出</h4>
                      <p>导出 .pptx/.docx</p>
                    </div>
                  </div>

                  <div class="onboarding-actions">
                    <el-button type="primary" size="default" :icon="Plus" @click="router.push('/courses/new')">
                      新建微课项目
                    </el-button>

                    <el-button size="default" :icon="Select" @click="createSampleCourse">
                      一键导入《牛顿第二定律》示例
                    </el-button>
                  </div>
                </div>

                <!-- Empty Search Results -->
                <EmptyState
                  v-else-if="!filteredCourses.length"
                  title="暂无匹配的微课项目"
                  description="未找到符合筛选条件的微课项目，请调整搜索关键词。"
                  action-text="清空筛选"
                  @action="searchQuery = ''; activeStatusFilter = 'all';"
                />

                <!-- Clean & Balanced Course Cards Grid -->
                <div v-else class="courses-grid-list">
                  <div 
                    v-for="course in filteredCourses" 
                    :key="course.id" 
                    class="course-card card-hover"
                    @click="router.push(`/courses/${course.id}/workspace`)"
                  >
                    <div class="course-card-header">
                      <div class="title-and-tags">
                        <div class="course-tags-row">
                          <span class="meta-tag subject">{{ course.subject }}</span>
                          <span class="meta-tag grade">{{ course.grade_level }}</span>
                          <span class="meta-tag duration">{{ course.duration_minutes }} 分钟</span>
                        </div>
                        <h3 class="course-card-title" :title="course.title">{{ course.title }}</h3>
                      </div>
                      <StatusBadge :status="course.status" size="small" />
                    </div>

                    <!-- 5 Key Deliverable Items Progress Status Bar -->
                    <div class="course-deliverables-bar">
                      <div class="deliv-item" :class="{ ready: course.status === 'completed' }">
                        <el-icon class="deliv-ic doc"><Document /></el-icon>
                        <span>教学设计</span>
                      </div>

                      <div class="deliv-item" :class="{ ready: course.status === 'completed' }">
                        <el-icon class="deliv-ic ppt"><Files /></el-icon>
                        <span>16:9 PPT</span>
                      </div>

                      <div class="deliv-item" :class="{ ready: course.status === 'completed' }">
                        <el-icon class="deliv-ic sheet"><CircleCheck /></el-icon>
                        <span>任务单</span>
                      </div>

                      <div class="deliv-item" :class="{ ready: course.status === 'completed' }">
                        <el-icon class="deliv-ic script"><Cpu /></el-icon>
                        <span>逐字脚本</span>
                      </div>

                      <div class="deliv-item" :class="{ ready: course.status === 'completed' }">
                        <el-icon class="deliv-ic quiz"><Operation /></el-icon>
                        <span>互动试题</span>
                      </div>
                    </div>

                    <div class="course-card-footer">
                      <span class="update-time">更新于 {{ new Date(course.updated_at).toLocaleDateString('zh-CN') }}</span>
                      <el-button type="primary" link size="small" class="enter-btn">
                        <span>进入工作台</span>
                        <el-icon><ArrowRight /></el-icon>
                      </el-button>
                    </div>
                  </div>
                </div>

              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-root-view {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.landing-page-shell {
  min-height: 100vh;
  height: 100%;
  position: relative;
  overflow-x: hidden;
  overflow-y: auto;
  scroll-behavior: smooth;
  background: var(--page-bg);
}

.landing-body {
  position: relative;
  z-index: 1;
}

/* 100vh One-Screen Viewport Outer Container */
.workspace-page-container {
  box-sizing: border-box;
  padding: 16px 20px;
  width: 100%;
  height: 100%;
  max-height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ONE Master Single Card Page Shell */
.master-workbench-card {
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm);
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Section 1: Integrated Top Header Bar */
.master-header-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--border-light);
  background: var(--surface-secondary);
  flex-shrink: 0;
}

.header-titles {
  display: flex;
  align-items: center;
  gap: 12px;
}

.eyebrow-tag {
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 3px 8px;
  border-radius: var(--radius-xs);
  letter-spacing: 0.05em;
}

.main-title {
  margin: 0;
  font-size: 19px;
  font-weight: 900;
  color: var(--text-primary);
}

.subtitle-text {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 500;
}

.create-main-btn {
  font-weight: 800 !important;
}

/* Section 2: Progress Summary & Metrics Band */
.master-overview-band {
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-light);
  background: linear-gradient(135deg, var(--surface-primary) 0%, var(--surface-secondary) 100%);
  flex-shrink: 0;
}

.overview-banner-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.banner-welcome {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.welcome-user-info h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 900;
  color: var(--text-primary);
}

.welcome-user-info p {
  margin: 2px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

.banner-progress-summary {
  min-width: 300px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.overall-progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-title {
  font-size: 12px;
  font-weight: 800;
  color: var(--text-secondary);
}

.progress-percentage-num {
  font-size: 15px;
  font-weight: 900;
  color: var(--color-primary);
}

.overall-progress-track {
  height: 8px;
  background: var(--border-default);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.overall-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  border-radius: var(--radius-pill);
  transition: width var(--motion-slow) var(--ease-out-smooth);
}

.banner-stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
}

@media (max-width: 900px) {
  .banner-stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-pill-card {
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-control);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.stat-pill-card:hover {
  border-color: var(--border-active);
  transform: translateY(-2px);
  box-shadow: var(--shadow-xs);
}

.stat-pill-card.active {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.stat-pill-card.static {
  cursor: default;
}
.stat-pill-card.static:hover {
  transform: none;
  border-color: var(--border-default);
}

.stat-num {
  font-size: 18px;
  font-weight: 900;
  line-height: 1.2;
}

.stat-num.blue { color: var(--color-primary); }
.stat-num.success { color: var(--accent-mint); }
.stat-num.warning { color: var(--accent-amber); }
.stat-num.agent { color: var(--accent-violet); }
.stat-num.mint { color: var(--accent-cyan); }

.stat-num small {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
}

.stat-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
}

/* Section 3: Inline AI Quick Creation Strip */
.inline-ai-quick-strip {
  padding: 10px 20px;
  background: var(--surface-secondary);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.quick-prompt-input-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.prompt-input-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--surface-primary);
  border: 1.5px solid var(--color-primary-border);
  border-radius: var(--radius-control);
  padding: 4px 6px 4px 14px;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.06);
  transition: all var(--motion-fast);
}

.prompt-input-wrapper:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 3px 12px rgba(79, 70, 229, 0.15);
}

.magic-input-icon {
  font-size: 18px;
  color: var(--color-primary);
}

.inline-prompt-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.inline-send-btn {
  border: none;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  padding: 7px 16px;
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.inline-send-btn:hover:not(:disabled) {
  opacity: 0.92;
  transform: translateX(1px);
}

.inline-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.recent-resume-box {
  flex-shrink: 0;
}

.resume-pill-btn {
  border: 1px solid var(--color-primary-border);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: var(--radius-pill);
  padding: 6px 14px;
  font-size: 12.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.resume-pill-btn:hover {
  background: var(--color-primary);
  color: #ffffff;
}

.prompt-chips-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.chips-label {
  color: var(--text-muted);
  font-weight: 700;
}

.chip-tag {
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: all var(--motion-fast);
}

.chip-tag:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

/* Inline Alert Strip */
.inline-status-alert-strip {
  padding: 8px 20px;
  background: var(--surface-tertiary);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.status-alert-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 700;
  padding: 4px 12px;
  border-radius: var(--radius-pill);
}

.status-alert-item.warning {
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
}

.status-alert-item.agent {
  background: var(--accent-violet-soft);
  color: var(--accent-violet);
}

.alert-ic {
  font-size: 14px;
}

.pulse-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent-violet);
}

.alert-txt {
  font-size: 12.5px;
}

.alert-action-link {
  border: none;
  background: transparent;
  color: currentColor;
  font-weight: 900;
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
  margin-left: 6px;
}

/* Section 4: Master Main Workspace */
.master-body-split {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface-primary);
}

.master-courses-col {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.dashboard-content-panel {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.dashboard-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-shrink: 0;
  gap: 16px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.lf-card-title {
  margin: 0;
  font-size: 16.5px;
  font-weight: 900;
  color: var(--text-primary);
}

.courses-count-pill {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  background: var(--surface-tertiary);
  padding: 2px 9px;
  border-radius: var(--radius-pill);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-filter-pills {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--surface-secondary);
  padding: 3px;
  border-radius: var(--radius-control);
  border: 1px solid var(--border-soft);
}

.filter-pill {
  border: none;
  background: transparent;
  padding: 4px 12px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--motion-fast);
}

.filter-pill:hover {
  color: var(--text-primary);
}

.filter-pill.active {
  background: var(--surface-primary);
  color: var(--color-primary);
  box-shadow: var(--shadow-xs);
}

.search-box {
  width: 220px;
}

.courses-body-content {
  width: 100%;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.courses-grid-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 16px;
}

.course-card {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  padding: 16px 18px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
  overflow: hidden;
  gap: 12px;
}

.course-card:hover {
  border-color: #c7d2fe;
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(79, 70, 229, 0.1);
}

.course-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.title-and-tags {
  min-width: 0;
  flex: 1;
}

.course-tags-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.meta-tag {
  font-size: 11.5px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.meta-tag.subject { background: #eef2ff; color: #4338ca; border: 1px solid #c7d2fe; }
.meta-tag.grade { background: #f8fafc; color: #475569; border: 1px solid #e2e8f0; }
.meta-tag.duration { background: #f0f9ff; color: #0284c7; border: 1px solid #bae6fd; }

.course-card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Clean 5 Deliverables Status Row */
.course-deliverables-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.deliv-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  color: #94a3b8;
}

.deliv-item.ready {
  color: #059669;
}

.deliv-ic {
  font-size: 13px;
}

.deliv-ic.doc { color: #4f46e5; }
.deliv-ic.ppt { color: #d97706; }
.deliv-ic.sheet { color: #059669; }
.deliv-ic.script { color: #7c3aed; }
.deliv-ic.quiz { color: #0891b2; }

.course-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
}

.update-time {
  font-size: 11.5px;
  color: #64748b;
  font-weight: 500;
}

.enter-btn {
  font-size: 12px !important;
  font-weight: 700 !important;
  color: #ffffff !important;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
  border: 0 !important;
  border-radius: 999px !important;
  padding: 5px 14px !important;
  box-shadow: 0 3px 10px rgba(79, 70, 229, 0.2) !important;
  transition: all 180ms ease !important;
}

.enter-btn:hover {
  transform: translateX(2px) !important;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.3) !important;
}

/* Compact Zero Courses Guided Onboarding Styles */
.empty-onboarding-panel {
  padding: 20px 24px;
  background: var(--surface-secondary);
  border-radius: var(--radius-card);
  border: 1.5px dashed var(--border-default);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.onboarding-header {
  display: flex;
  align-items: center;
  gap: 14px;
}

.onboarding-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-control);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  font-size: 20px;
}

.onboarding-title-wrap h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 900;
  color: var(--text-primary);
}

.onboarding-title-wrap p {
  margin: 4px 0 0;
  font-size: 13.5px;
  color: var(--text-muted);
}

.onboarding-steps-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.step-card {
  padding: 12px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-control);
}

.step-num {
  font-size: 12px;
  font-weight: 900;
  color: var(--color-primary);
}

.step-card h4 {
  margin: 4px 0 2px;
  font-size: 14px;
  font-weight: 800;
}

.step-card p {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.onboarding-actions {
  display: flex;
  gap: 12px;
}
</style>





