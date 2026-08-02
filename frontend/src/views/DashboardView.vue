<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { useCourseStore } from '../stores/courses';
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
  DataAnalysis, 
  Clock, 
  Cpu, 
  CircleCheck, 
  Search,
  Files,
  Document,
  ArrowRight,
  Select,
  MagicStick,
  Check
} from '@element-plus/icons-vue';

const auth = useAuthStore();
const store = useCourseStore();
const router = useRouter();
const route = useRoute();

const searchQuery = ref((route.query.search as string) || '');
const activeStatusFilter = ref('all');

onMounted(async () => {
  if (auth.user) {
    await store.load();
  }
});

const counts = computed(() => {
  const total = store.items.length;
  const running = store.items.filter(x => ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(x.status)).length;
  const review = store.items.filter(x => ['blueprint_review', 'teacher_review'].includes(x.status)).length;
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
      list = list.filter(x => ['blueprint_review', 'teacher_review'].includes(x.status));
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

    <!-- 2. Project Completion & Status Dashboard for Authenticated Teachers -->
    <div v-else class="workspace-page-container animate-fade-in">
      <div class="master-workbench-card">
        <!-- Master Header: Title + Action -->
        <div class="master-header-strip">
          <div class="header-titles">
            <span class="eyebrow-tag">DASHBOARD</span>
            <h1 class="main-title">教学资源项目完成度看板</h1>
            <span class="subtitle-text">全套微课资源研发进度与 Agent 生成监控</span>
          </div>

          <div class="header-action">
            <el-button type="primary" size="default" :icon="Plus" @click="router.push('/courses/new')">
              新建微课项目
            </el-button>
          </div>
        </div>

        <!-- Master Overview Band: Project Completion & Progress Summary Banner -->
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

        <!-- Master Main Split: Full Width Course Library -->
        <div class="master-body-split">
          <!-- Primary Column: Course Projects Workspace -->
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

                <!-- Empty Filter Search Results -->
                <EmptyState
                  v-else-if="!filteredCourses.length"
                  title="暂无匹配的微课项目"
                  description="未找到符合筛选条件的微课项目，请调整搜索关键词。"
                  action-text="清空筛选"
                  @action="searchQuery = ''; activeStatusFilter = 'all';"
                />

                <!-- Course Cards List -->
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
                        <h3 class="course-card-title">{{ course.title }}</h3>
                      </div>
                      <StatusBadge :status="course.status" size="small" />
                    </div>

                    <div class="course-resources-preview">
                      <span class="res-item"><el-icon><Document /></el-icon> 教学设计</span>
                      <span class="res-item"><el-icon><Files /></el-icon> 16:9 PPT</span>
                      <span class="res-item"><el-icon><CircleCheck /></el-icon> 任务单</span>
                      <span class="res-item"><el-icon><Cpu /></el-icon> 脚本</span>
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
  position: relative;
  overflow-x: hidden;
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

/* Section 1: Integrated Top Header & Metrics Bar */
.master-header-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 20px;
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
  font-weight: 600;
}

.unified-metrics-inline {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--surface-primary);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill);
  padding: 4px 14px;
  box-shadow: var(--shadow-xs);
}

.metric-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  transition: background var(--motion-fast);
}

.metric-item:hover {
  background: var(--bg-hover);
}

.metric-item.active {
  background: var(--color-primary-soft);
}

.metric-ic {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12.5px;
}

.metric-ic.blue { background: var(--color-primary-soft); color: var(--color-primary); }
.metric-ic.agent { background: var(--accent-violet-soft); color: var(--accent-violet); }
.metric-ic.warning { background: var(--accent-amber-soft); color: var(--accent-amber); }
.metric-ic.success { background: var(--accent-mint-soft); color: var(--accent-mint); }

.metric-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.metric-meta .label {
  font-size: 12.5px;
  color: var(--text-muted);
  font-weight: 700;
}

.metric-meta .val {
  font-size: 15.5px;
  font-weight: 900;
  color: var(--text-primary);
  line-height: 1;
}

.metric-meta .agent-text { color: var(--accent-violet); }

.metric-meta .val small {
  font-size: 11px;
  color: var(--text-muted);
}

.metric-sep {
  width: 1px;
  height: 16px;
  background: var(--border-default);
}

.header-action {
  display: flex;
  align-items: center;
}

/* Section 2: Project Completion & Progress Overview Banner */
.master-overview-band {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-light);
  background: linear-gradient(135deg, var(--surface-primary) 0%, var(--surface-secondary) 100%);
  flex-shrink: 0;
}

.overview-banner-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
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
  margin: 3px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}

.banner-progress-summary {
  min-width: 300px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.overall-progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-title {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--text-secondary);
}

.progress-percentage-num {
  font-size: 15.5px;
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
  padding: 10px 14px;
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
  font-size: 20px;
  font-weight: 900;
  line-height: 1.2;
}

.stat-num.blue { color: var(--color-primary); }
.stat-num.success { color: var(--accent-mint); }
.stat-num.warning { color: var(--accent-amber); }
.stat-num.agent { color: var(--accent-violet); }
.stat-num.mint { color: var(--accent-cyan); }

.stat-num small {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
}

.stat-label {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-muted);
}

/* Section 3: Master Main Workspace Split */
.master-body-split {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface-primary);
}

.master-courses-col {
  padding: 18px 24px;
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
  margin-bottom: 14px;
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
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}


.course-card {
  background: var(--surface-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 16px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-shadow: var(--shadow-xs);
  transition: all var(--motion-normal) var(--ease-out-smooth);
}

.course-card:hover {
  border-color: var(--border-active);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  background: var(--surface-primary);
}

.course-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 10px;
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
  font-weight: 800;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.meta-tag.subject { background: var(--color-primary-soft); color: var(--color-primary); }
.meta-tag.grade { background: var(--surface-tertiary); color: var(--text-secondary); }
.meta-tag.duration { background: var(--accent-cyan-soft); color: var(--accent-cyan); }

.course-card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.course-resources-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  background: var(--surface-primary);
  border-radius: var(--radius-xs);
  margin-bottom: 10px;
  border: 1px solid var(--border-light);
}

.res-item {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.course-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid var(--border-light);
}

.update-time {
  font-size: 12px;
  color: var(--text-muted);
}

.enter-btn {
  font-size: 13px !important;
  font-weight: 800 !important;
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



