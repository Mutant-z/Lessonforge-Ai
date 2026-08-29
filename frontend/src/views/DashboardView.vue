<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { useCourseStore } from '../stores/courses';
import { useCourseIntakeStore } from '../stores/courseIntake';
import type { Course } from '../types';
import { errorMessage } from '../api/client';
import { ElMessage, ElMessageBox } from 'element-plus';

import StatusBadge from '../components/feedback/StatusBadge.vue';
import EmptyState from '../components/feedback/EmptyState.vue';

// Public Landing Page Components for Guests
import AmbientBackground from '../components/visual/AmbientBackground.vue';
import HomeNavbar from '../components/home/HomeNavbar.vue';
import HomeHero from '../components/home/HomeHero.vue';
import ResourceBentoGrid from '../components/home/ResourceBentoGrid.vue';
import CourseExamplePanel from '../components/home/CourseExamplePanel.vue';
import HomeCTA from '../components/home/HomeCTA.vue';
import HomeFooter from '../components/home/HomeFooter.vue';

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
  Delete,
  Loading,
  Paperclip,
  VideoPlay,
  ChatDotSquare,
  Bell
} from '@element-plus/icons-vue';

const auth = useAuthStore();
const store = useCourseStore();
const intake = useCourseIntakeStore();
const router = useRouter();
const route = useRoute();

const searchQuery = ref((route.query.search as string) || '');
const activeStatusFilter = ref('all');
const startingIntake = ref(false);
const deletingCourseId = ref<string | null>(null);

const promptInput = ref('');
const attachedFiles = ref<File[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);

onMounted(async () => {
  if (auth.user) {
    await store.load();
  }
});

const counts = computed(() => {
  const items = store.items || [];
  const total = items.length;
  const running = items.filter(x => ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(x.status)).length;
  const review = items.filter(x => ['blueprint_review', 'teacher_review', 'requirement_review', 'draft'].includes(x.status)).length;
  const done = items.filter(x => x.status === 'completed').length;
  const completionRate = total > 0 ? Math.round((done / total) * 100) : 0;
  const savedHours = Math.round(total * 4.5);
  return { all: total, running, review, done, completionRate, savedHours };
});

const pendingActionItems = computed(() => {
  const list: any[] = [];
  const items = store.items || [];
  items.forEach(course => {
    if (['blueprint_review', 'teacher_review'].includes(course.status)) {
      list.push({
        id: course.id,
        title: course.title,
        type: 'blueprint',
        tag: '待确认蓝图',
        desc: `${course.subject} · 蓝图设计等待教师确认`,
        target: `/courses/${course.id}/blueprint`
      });
    } else if (course.status === 'draft' || course.status === 'requirement_review') {
      list.push({
        id: course.id,
        title: course.title,
        type: 'draft',
        tag: '草稿待完善',
        desc: `${course.subject} · 尚未启动 Agent 并发生成`,
        target: `/courses/${course.id}/workspace`
      });
    } else if (course.status === 'failed' || course.status === 'needs_attention') {
      list.push({
        id: course.id,
        title: course.title,
        type: 'failed',
        tag: '需人工处理',
        desc: `${course.subject} · 部分生成环节需介入`,
        target: `/courses/${course.id}/workspace`
      });
    }
  });
  return list;
});

const recentEditedCourse = computed(() => {
  const items = store.items || [];
  if (!items.length) return null;
  return items[0];
});

const filteredCourses = computed(() => {
  let list = store.items || [];

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

function triggerFileInput() {
  fileInputRef.value?.click();
}

function handleFileSelected(event: Event) {
  const target = event.target as HTMLInputElement;
  if (target.files && target.files.length) {
    attachedFiles.value = [...attachedFiles.value, ...Array.from(target.files)];
  }
}

function removeFile(index: number) {
  attachedFiles.value.splice(index, 1);
}

function applyExampleChip(text: string) {
  promptInput.value = text;
}

function onKeydown(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    handleIntakeSubmit();
  }
}

async function handleIntakeSubmit() {
  if (!promptInput.value.trim() || startingIntake.value) return;
  startingIntake.value = true;
  try {
    const session = await intake.create(null);
    if (attachedFiles.value.length) {
      await Promise.allSettled(attachedFiles.value.map(file => intake.upload(file)));
    }
    await intake.send(promptInput.value.trim());
    await router.push({ path: '/courses/new', query: { session: session.id } });
  } catch (e) {
    router.push('/courses/new');
  } finally {
    startingIntake.value = false;
  }
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

async function handleDeleteCourse(course: Course) {
  if (deletingCourseId.value) return;

  try {
    await ElMessageBox.confirm(
      `确定要删除项目“${course.title}”吗？删除后项目将从项目库中移除，生成内容也将无法继续访问。`,
      '删除微课项目',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
        type: 'warning',
      },
    );
  } catch {
    return;
  }

  deletingCourseId.value = course.id;
  try {
    await store.delete(course.id);
    ElMessage.success('项目已删除');
  } catch (cause) {
    ElMessage.error(errorMessage(cause));
  } finally {
    deletingCourseId.value = null;
  }
}

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

function getProjectCta(course: Course) {
  const { status, id } = course;
  if (['blueprint_review', 'teacher_review'].includes(status)) {
    return { text: '处理待确认', target: `/courses/${id}/blueprint`, btnType: 'warning' };
  }
  if (['blueprint_generating', 'resource_generating', 'quality_checking'].includes(status)) {
    return { text: '查看生成进度', target: `/courses/${id}/workspace`, btnType: 'running' };
  }
  if (status === 'completed') {
    return { text: '进入工作台', target: `/courses/${id}/workspace`, btnType: 'primary' };
  }
  if (status === 'failed' || status === 'needs_attention') {
    return { text: '查看问题', target: `/courses/${id}/workspace`, btnType: 'danger' };
  }
  return { text: '进入工作台', target: `/courses/${id}/workspace`, btnType: 'primary' };
}

function getDeliverableStates(status: string) {
  const isDone = status === 'completed';
  const isReview = ['blueprint_review', 'teacher_review'].includes(status);
  const isRunning = ['blueprint_generating', 'resource_generating', 'quality_checking'].includes(status);
  const isResourceGen = status === 'resource_generating';

  return [
    { label: '教学设计', ready: isDone || isReview || isResourceGen, statusText: isReview ? '待确认' : (isDone ? '完成' : (isResourceGen ? '已就绪' : (isRunning ? '生成中' : '未开始'))), ic: Document, icClass: 'doc' },
    { label: '16:9 PPT', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: Files, icClass: 'ppt' },
    { label: '任务单', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: CircleCheck, icClass: 'sheet' },
    { label: '课后练习', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: Operation, icClass: 'quiz' },
    { label: '视频脚本', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: Cpu, icClass: 'script' },
    { label: '教师逐字稿', ready: isDone, statusText: isDone ? '完成' : (isRunning ? '生成中' : '需同步'), ic: ChatDotSquare, icClass: 'voice' }
  ];
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

    <!-- 2. Integrated One-Screen Workbench Canvas -->
    <div v-else class="teacher-dashboard-workbench animate-fade-in">
      
      <!-- Top Title & Action Header -->
      <div class="workbench-top-bar">
        <div class="top-title-group">
          <span class="brand-eyebrow">DASHBOARD</span>
          <h1 class="page-title">教学资源工作台</h1>
          <span class="title-sep">/</span>
          <span class="page-sub">管理微课项目、Agent 并发生成与教学资源交付状态</span>
        </div>

        <button class="btn-create-primary" @click="router.push('/courses/new')">
          <el-icon><Plus /></el-icon>
          <span>新建微课项目</span>
        </button>
      </div>

      <!-- Main Seamless Console Canvas -->
      <div class="workbench-canvas">
        
        <!-- SECTION 1: Dual Control Console (AI Composer + Pending Tasks) -->
        <div class="console-row">
          
          <!-- AI Creation Composer Box (70%) -->
          <div class="composer-box">
            <div class="box-top-line">
              <div class="box-heading-group">
                <span class="sparkle-badge"><el-icon><MagicStick /></el-icon></span>
                <h3 class="box-title">想制作什么微课？</h3>
                <span class="box-sub">描述教学主题与重点，AI 将自动构建全套教学资源</span>
              </div>

              <button 
                v-if="recentEditedCourse" 
                type="button" 
                class="resume-pill"
                @click="router.push(`/courses/${recentEditedCourse.id}/workspace`)"
              >
                <el-icon><VideoPlay /></el-icon>
                <span>继续编辑：{{ recentEditedCourse.title.length > 12 ? recentEditedCourse.title.slice(0, 12) + '...' : recentEditedCourse.title }}</span>
              </button>
            </div>

            <!-- Sleek Input Field Container -->
            <div class="input-container">
              <textarea 
                v-model="promptInput"
                class="prompt-textarea"
                rows="2"
                placeholder="例如：为高一学生制作一节 15 分钟的《牛顿第二定律：加速度与合外力关系》微课，包含实验引导与考点精讲..."
                @keydown="onKeydown"
              ></textarea>

              <!-- Attached Files Bar -->
              <div v-if="attachedFiles.length" class="attached-files-bar">
                <span 
                  v-for="(file, idx) in attachedFiles" 
                  :key="idx" 
                  class="file-chip"
                >
                  <el-icon><Paperclip /></el-icon>
                  <span class="file-name">{{ file.name }}</span>
                  <button type="button" class="del-file-btn" @click="removeFile(idx)">×</button>
                </span>
              </div>

              <!-- Bottom Bar with Tools + Quick Chips + Generate CTA -->
              <div class="input-bottom-bar">
                <div class="bar-tools">
                  <input ref="fileInputRef" type="file" multiple style="display:none" @change="handleFileSelected" />
                  <button type="button" class="upload-btn" @click="triggerFileInput">
                    <el-icon><Paperclip /></el-icon>
                    <span>+ 添加材料</span>
                  </button>

                  <div class="quick-samples">
                    <span class="sample-lbl">快捷示例：</span>
                    <button type="button" class="sample-btn" @click="applyExampleChip('高一物理《牛顿第二定律》15分钟互动课')">牛顿第二定律</button>
                    <button type="button" class="sample-btn" @click="applyExampleChip('初中数学《勾股定理及实际应用》探究课')">勾股定理</button>
                    <button type="button" class="sample-btn" @click="applyExampleChip('高中化学《氧化还原反应配平技巧》')">氧化还原反应</button>
                  </div>
                </div>

                <button 
                  type="button" 
                  class="generate-btn"
                  :disabled="!promptInput.trim() || startingIntake"
                  @click="handleIntakeSubmit"
                >
                  <span>AI 极速生成</span>
                  <el-icon><ArrowRight /></el-icon>
                </button>
              </div>
            </div>
          </div>

          <div class="panel-v-divider"></div>

          <!-- Today's Pending Tasks Panel (30%) -->
          <div class="pending-box">
            <div class="pending-top">
              <div class="p-title-group">
                <span class="p-icon warning"><el-icon><Bell /></el-icon></span>
                <h4 class="p-title">今日待处理</h4>
              </div>
              <span v-if="pendingActionItems.length" class="p-badge warning">{{ pendingActionItems.length }} 项待确认</span>
              <span v-else class="p-badge success">已清空</span>
            </div>

            <div v-if="!pendingActionItems.length" class="p-empty-state">
              <el-icon class="done-ic"><CircleCheck /></el-icon>
              <span>所有微课蓝图与任务已确认完毕</span>
            </div>

            <div v-else class="p-items-list">
              <div 
                v-for="item in pendingActionItems.slice(0, 2)" 
                :key="item.id" 
                class="p-card-row"
                @click="router.push(item.target)"
              >
                <div class="p-row-main">
                  <div class="p-tag-line">
                    <span class="type-pill" :class="item.type">{{ item.tag }}</span>
                    <h5 class="p-row-title" :title="item.title">{{ item.title }}</h5>
                  </div>
                  <p class="p-row-desc">{{ item.desc }}</p>
                </div>

                <button type="button" class="p-action-btn">
                  <span>处理</span>
                  <el-icon><ArrowRight /></el-icon>
                </button>
              </div>
            </div>
          </div>

        </div>

        <!-- SECTION 2: Integrated Live Metrics Bar -->
        <div class="live-metrics-bar">
          <div class="metrics-left">
            <span class="m-eyebrow">WORKFLOW</span>
            <span class="m-title">教学资源交付状态</span>
            <div class="m-progress-pill">
              <span>可交付微课：<strong>{{ counts.done }} / {{ counts.all }}</strong></span>
              <div class="m-track"><div class="m-fill" :style="{ width: counts.completionRate + '%' }"></div></div>
              <span class="pct-num">{{ counts.completionRate }}%</span>
            </div>
          </div>

          <div class="metrics-right">
            <div class="m-cell" :class="{ active: activeStatusFilter === 'all' }" @click="activeStatusFilter = 'all'">
              <span class="n-val primary">{{ counts.all }}</span>
              <span class="n-lbl">全部微课项目</span>
            </div>

            <div class="m-sep"></div>

            <div class="m-cell" :class="{ active: activeStatusFilter === 'completed' }" @click="activeStatusFilter = 'completed'">
              <span class="n-val success">{{ counts.done }}</span>
              <span class="n-lbl">已打包交付</span>
            </div>

            <div class="m-sep"></div>

            <div class="m-cell" :class="{ active: activeStatusFilter === 'review', urgent: counts.review > 0 }" @click="activeStatusFilter = 'review'">
              <div class="n-group">
                <span class="n-val warning">{{ counts.review }}</span>
                <span v-if="counts.review > 0" class="n-dot-urgent"></span>
              </div>
              <span class="n-lbl">待教师审核</span>
            </div>

            <div class="m-sep"></div>

            <div class="m-cell" :class="{ active: activeStatusFilter === 'running' }" @click="activeStatusFilter = 'running'">
              <div class="n-group">
                <span class="n-val agent">{{ counts.running }}</span>
                <span v-if="counts.running > 0" class="n-dot-live animate-pulse"></span>
              </div>
              <span class="n-lbl">Agent 生成中</span>
            </div>

            <div class="m-sep"></div>

            <div class="m-cell static">
              <span class="n-val mint">{{ counts.savedHours }}<small>h</small></span>
              <span class="n-lbl">累计节省工时</span>
            </div>
          </div>
        </div>

        <!-- SECTION 3: Main Project Library Workspace Area -->
        <div class="project-workspace-area">
          <div class="workspace-toolbar">
            <div class="tb-left">
              <h3 class="tb-title">我的微课项目库</h3>
              <span class="tb-count">共 {{ filteredCourses.length }} 门项目</span>
            </div>

            <div class="tb-right">
              <div class="filter-tabs-pill">
                <button type="button" :class="{ active: activeStatusFilter === 'all' }" @click="activeStatusFilter = 'all'">全部</button>
                <button type="button" :class="{ active: activeStatusFilter === 'running' }" @click="activeStatusFilter = 'running'">生成中</button>
                <button type="button" :class="{ active: activeStatusFilter === 'review' }" @click="activeStatusFilter = 'review'">待核对</button>
                <button type="button" :class="{ active: activeStatusFilter === 'completed' }" @click="activeStatusFilter = 'completed'">已完成</button>
              </div>

              <div class="search-wrap">
                <el-input v-model="searchQuery" placeholder="搜索课程名称、学科或年级..." :prefix-icon="Search" clearable size="default" />
              </div>
            </div>
          </div>

          <!-- Project List Internal Overflow Scroll Area -->
          <div class="workspace-scroll-area">
            <!-- 0 Projects: Guided Onboarding -->
            <div v-if="!store.items.length" class="empty-onboarding-surface">
              <div class="onboarding-banner">
                <div class="onboarding-icon-wrap"><el-icon><MagicStick /></el-icon></div>
                <div class="onboarding-text">
                  <h3>开启您的第一门 AI 微课项目</h3>
                  <p>输入教学主题和要求，多 Agent 团队将在 3 分钟内为您智能构建完整教学设计、PPT 与配套资源。</p>
                </div>
              </div>

              <div class="onboarding-steps-row">
                <div class="step-box"><span class="step-number">01</span><h4 class="step-title">描述教学需求</h4><p class="step-desc">输入主题、学段与重点</p></div>
                <div class="step-box"><span class="step-number">02</span><h4 class="step-title">确认教学意图</h4><p class="step-desc">教师核对蓝图与大纲</p></div>
                <div class="step-box"><span class="step-number">03</span><h4 class="step-title">Agent 并发生成</h4><p class="step-desc">PPT与试题自动产出</p></div>
                <div class="step-box"><span class="step-number">04</span><h4 class="step-title">质检一键导出</h4><p class="step-desc">导出 .pptx/.docx 资源</p></div>
              </div>

              <div class="onboarding-cta-row">
                <el-button type="primary" size="large" :icon="Plus" @click="router.push('/courses/new')">新建微课项目</el-button>
                <el-button size="large" :icon="Select" @click="createSampleCourse">一键导入《牛顿第二定律》示范微课</el-button>
              </div>
            </div>

            <!-- Empty Search Results -->
            <EmptyState v-else-if="!filteredCourses.length" title="未找到符合条件的微课项目" description="建议您调整搜索关键词或重置状态筛选条件。" action-text="重置筛选条件" @action="searchQuery = ''; activeStatusFilter = 'all';" />

            <!-- Single Wide Project Workspace Card -->
            <div v-else-if="filteredCourses.length === 1" class="wide-project-card" @click="router.push(getProjectCta(filteredCourses[0]).target)">
              <div class="w-header">
                <div class="w-left">
                  <h2 class="w-title">{{ filteredCourses[0].title }}</h2>
                  <div class="w-tags">
                    <span class="tag-pill subject">{{ filteredCourses[0].subject }}</span>
                    <span class="tag-pill grade">{{ filteredCourses[0].grade_level }}</span>
                    <span class="tag-pill duration">{{ filteredCourses[0].duration_minutes }} 分钟</span>
                  </div>
                </div>
                <div class="w-header-actions">
                  <StatusBadge :status="filteredCourses[0].status" size="default" />
                  <button
                    type="button"
                    class="delete-project-btn"
                    :disabled="deletingCourseId === filteredCourses[0].id"
                    @click.stop="handleDeleteCourse(filteredCourses[0])"
                  >
                    <el-icon><Delete /></el-icon>
                    <span>删除项目</span>
                  </button>
                </div>
              </div>

              <div class="w-stage-strip" :class="getProjectStageInfo(filteredCourses[0].status).type">
                <div class="stage-strip-left">
                  <span class="stage-dot-indicator"></span>
                  <span class="stage-label">当前阶段：</span>
                  <span class="stage-val">{{ getProjectStageInfo(filteredCourses[0].status).text }}</span>
                </div>
                <div v-if="['blueprint_generating', 'resource_generating'].includes(filteredCourses[0].status)" class="stage-live">
                  <span class="live-pulse-dot animate-pulse"></span>
                  <span>AI 并发执行中</span>
                </div>
              </div>

              <!-- 7 Deliverables Readiness Grid -->
              <div class="w-deliv-grid">
                <div 
                  v-for="(deliv, idx) in getDeliverableStates(filteredCourses[0].status)" 
                  :key="idx" 
                  class="deliv-cell" 
                  :class="{ 
                    ready: deliv.ready && deliv.statusText !== '生成中', 
                    'needs-action': deliv.statusText === '待确认',
                    generating: deliv.statusText === '生成中'
                  }"
                >
                  <div class="deliv-ic" :class="deliv.icClass"><component :is="deliv.ic" /></div>
                  <div class="deliv-info">
                    <span class="deliv-name">{{ deliv.label }}</span>
                    <span 
                      class="deliv-status" 
                      :class="{ 
                        ready: deliv.ready && deliv.statusText !== '生成中', 
                        warning: deliv.statusText === '待确认',
                        generating: deliv.statusText === '生成中'
                      }"
                    >
                      <span v-if="deliv.statusText === '待确认'" class="deliv-status-dot pulse"></span>
                      <span v-else-if="deliv.statusText === '生成中'" class="deliv-status-dot generating"></span>
                      <span v-else-if="deliv.ready" class="deliv-status-dot ready"></span>
                      {{ deliv.statusText }}
                    </span>
                  </div>
                </div>
              </div>

              <div class="w-footer">
                <span class="footer-time">更新时间：{{ new Date(filteredCourses[0].updated_at).toLocaleString('zh-CN') }}</span>
                <button type="button" class="cta-action-btn" :class="getProjectCta(filteredCourses[0]).btnType" @click.stop="router.push(getProjectCta(filteredCourses[0]).target)">
                  <span>{{ getProjectCta(filteredCourses[0]).text }}</span>
                  <el-icon><ArrowRight /></el-icon>
                </button>
              </div>
            </div>

            <!-- Multi Project Grid (>= 2 Projects) -->
            <div v-else class="multi-projects-grid">
              <div v-for="course in filteredCourses" :key="course.id" class="grid-card" @click="router.push(getProjectCta(course).target)">
                <div class="g-header">
                  <div class="g-meta">
                    <div class="w-tags compact">
                      <span class="tag-pill subject">{{ course.subject }}</span>
                      <span class="tag-pill grade">{{ course.grade_level }}</span>
                      <span class="tag-pill duration">{{ course.duration_minutes }}m</span>
                    </div>
                    <h4 class="g-title" :title="course.title">{{ course.title }}</h4>
                  </div>
                  <div class="g-header-actions">
                    <StatusBadge :status="course.status" size="small" />
                    <el-tooltip content="删除项目" placement="top">
                      <button
                        type="button"
                        class="delete-project-icon"
                        :disabled="deletingCourseId === course.id"
                        aria-label="删除项目"
                        @click.stop="handleDeleteCourse(course)"
                      >
                        <el-icon><Delete /></el-icon>
                      </button>
                    </el-tooltip>
                  </div>
                </div>

                <div class="g-stage" :class="getProjectStageInfo(course.status).type">
                  <span class="g-dot"></span>
                  <span>{{ getProjectStageInfo(course.status).text }}</span>
                </div>

                <div class="g-deliv-bar">
                  <div v-for="(deliv, idx) in getDeliverableStates(course.status)" :key="idx" class="g-deliv-item" :class="{ ready: deliv.ready }">
                    <component :is="deliv.ic" class="g-deliv-ic" :class="deliv.icClass" />
                    <span>{{ deliv.label }}</span>
                  </div>
                </div>

                <div class="g-footer">
                  <span class="footer-time">{{ new Date(course.updated_at).toLocaleDateString('zh-CN') }}</span>
                  <button type="button" class="cta-action-btn compact" :class="getProjectCta(course).btnType" @click.stop="router.push(getProjectCta(course).target)">
                    <span>{{ getProjectCta(course).text }}</span>
                    <el-icon><ArrowRight /></el-icon>
                  </button>
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
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.landing-page-shell {
  min-height: 100vh;
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

/* Outer Single-Screen Workbench Canvas */
.teacher-dashboard-workbench {
  width: 100%;
  height: 100%;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 16px 28px 16px;
  box-sizing: border-box;
  background: var(--bg-page);
  display: flex;
  flex-direction: column;
}

.workbench-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.top-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.brand-eyebrow {
  font-size: 11.5px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 3px 9px;
  border-radius: var(--radius-xs);
  letter-spacing: 0.06em;
  border: 1px solid var(--color-primary-border);
}

.page-title {
  margin: 0;
  font-size: 25px;
  font-weight: 900;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.title-sep {
  color: var(--border-default);
  font-size: 14px;
}

.page-sub {
  font-size: 14px;
  color: var(--text-muted);
  font-weight: 500;
}

.btn-create-primary {
  border: none;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  padding: 8px 18px;
  border-radius: var(--radius-pill);
  font-size: 14px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  box-shadow: var(--shadow-glow-primary);
  transition: all var(--motion-fast);
}

.btn-create-primary:hover {
  opacity: 0.94;
  transform: translateY(-1px);
}

/* Main Canvas Content */
.workbench-canvas {
  width: 100%;
  height: 100%;
  max-width: var(--content-max-width);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
  gap: 12px;
  padding-top: 10px;
}

/* Console Row (AI Composer + Today's Pending Tasks) */
.console-row {
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 14px 18px;
  box-shadow: var(--shadow-xs);
  display: flex;
  gap: 16px;
  align-items: stretch;
  flex-shrink: 0;
}

.composer-box {
  flex: 7;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.box-top-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.box-heading-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sparkle-badge {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, var(--color-primary-soft) 0%, var(--accent-violet-soft) 100%);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  font-size: 15px;
  flex-shrink: 0;
}

.box-title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.box-sub {
  font-size: 13px;
  color: var(--text-muted);
  margin-left: 6px;
}

.resume-pill {
  border: 1px solid var(--color-primary-border);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: var(--radius-pill);
  padding: 4px 10px;
  font-size: 12.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.input-container {
  background: var(--surface-secondary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-control);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.input-container:focus-within {
  background: var(--surface-primary);
  border-color: var(--color-primary);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08);
}

.prompt-textarea {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14.5px;
  font-weight: 500;
  color: var(--text-primary);
  resize: none;
  min-height: 48px;
  max-height: 72px;
  line-height: 1.45;
}

.attached-files-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
}

.file-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.del-file-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
}

.input-bottom-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 5px;
  border-top: 1px solid var(--border-light);
}

.bar-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  overflow: hidden;
}

.upload-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 3px 6px;
  border-radius: var(--radius-sm);
  white-space: nowrap;
}

.upload-btn:hover {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.quick-samples {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow: hidden;
}

.sample-lbl {
  font-size: 12.5px;
  color: var(--text-muted);
  font-weight: 600;
  white-space: nowrap;
}

.sample-btn {
  border: 1px solid var(--border-default);
  background: var(--surface-primary);
  color: var(--text-secondary);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--motion-fast);
}

.sample-btn:hover {
  border-color: var(--color-primary-border);
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.generate-btn {
  border: none;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  padding: 6px 16px;
  border-radius: var(--radius-control);
  font-size: 13.5px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  box-shadow: var(--shadow-glow-primary);
  white-space: nowrap;
  flex-shrink: 0;
}

.generate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.panel-v-divider {
  width: 1px;
  background: var(--border-light);
  flex-shrink: 0;
}

.pending-box {
  flex: 3;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.pending-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.p-title-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.p-icon {
  font-size: 16px;
  color: var(--accent-amber);
}

.p-title {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
}

.p-badge.warning {
  font-size: 11.5px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
  white-space: nowrap;
  flex-shrink: 0;
}

.p-badge.success {
  font-size: 11.5px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--accent-mint-soft);
  color: var(--accent-mint);
  white-space: nowrap;
  flex-shrink: 0;
}

.p-empty-state {
  padding: 14px;
  background: var(--surface-secondary);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-control);
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.done-ic {
  font-size: 18px;
  color: var(--accent-mint);
}

.p-items-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.p-card-row {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: var(--radius-control);
  padding: 10px 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  transition: all var(--motion-fast);
}

.p-card-row:hover {
  background: #ffffff;
  border-color: var(--color-primary-border);
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.08);
}

.p-row-main {
  flex: 1;
  min-width: 0;
}

.p-tag-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.type-pill {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1.2;
}
.type-pill.blueprint { background: var(--accent-amber-soft); color: var(--accent-amber); border: 1px solid #fef3c7; }
.type-pill.draft { background: var(--surface-tertiary); color: var(--text-secondary); }
.type-pill.failed { background: var(--color-danger-soft); color: var(--danger); }

.p-row-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 800;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.p-row-desc {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.p-action-btn {
  border: none;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  font-size: 12.5px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

/* Integrated Live Metrics Bar */
.live-metrics-bar {
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 8px 16px;
  box-shadow: var(--shadow-xs);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-shrink: 0;
}

.metrics-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.m-eyebrow {
  font-size: 11px;
  font-weight: 800;
  color: var(--color-primary);
  letter-spacing: 0.08em;
}

.m-title {
  font-size: 15px;
  font-weight: 800;
  color: var(--text-primary);
}

.m-progress-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-secondary);
  border: 1px solid var(--border-soft);
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  color: var(--text-muted);
}

.m-progress-pill strong { color: var(--color-primary); }

.m-track {
  width: 70px;
  height: 5px;
  background: var(--surface-tertiary);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.m-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  border-radius: var(--radius-pill);
}

.pct-num { font-weight: 800; color: var(--text-primary); }

.metrics-right {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface-secondary);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-control);
  padding: 3px 6px;
}

.m-sep {
  width: 1px;
  height: 22px;
  background: var(--border-default);
  flex-shrink: 0;
}

.m-cell {
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all var(--motion-fast);
}

.m-cell:hover,
.m-cell.active {
  background: var(--surface-primary);
  box-shadow: var(--shadow-xs);
}

.m-cell.static { cursor: default; }
.m-cell.static:hover { background: transparent; box-shadow: none; }

.n-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.n-val {
  font-size: 18px;
  font-weight: 900;
  line-height: 1;
}

.n-val.primary { color: var(--color-primary); }
.n-val.success { color: var(--accent-mint); }
.n-val.warning { color: var(--accent-amber); }
.n-val.agent { color: var(--accent-violet); }
.n-val.mint { color: var(--accent-cyan); }

.n-lbl {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
  white-space: nowrap;
}

.n-dot-urgent {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent-amber);
}

.n-dot-live {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-violet);
}

/* Project Workspace Area */
.project-workspace-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  flex: 1;
  min-height: 0;
}

.workspace-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.tb-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tb-title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.tb-count {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-muted);
  background: var(--surface-tertiary);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.tb-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-tabs-pill {
  display: flex;
  align-items: center;
  gap: 3px;
  background: var(--surface-secondary);
  padding: 2px;
  border-radius: var(--radius-control);
  border: 1px solid var(--border-soft);
}

.filter-tabs-pill button {
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

.filter-tabs-pill button:hover { color: var(--text-primary); }

.filter-tabs-pill button.active {
  background: var(--surface-primary);
  color: var(--color-primary);
  box-shadow: var(--shadow-xs);
}

.search-wrap {
  width: 240px;
}

.workspace-scroll-area {
  width: 100%;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

/* Wide Project Card */
.wide-project-card {
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 16px 20px;
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.wide-project-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.w-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.w-header-actions,
.g-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.delete-project-btn,
.delete-project-icon {
  border: 1px solid #fecdd3;
  background: #fff1f2;
  color: #be123c;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.delete-project-btn {
  min-height: 30px;
  padding: 4px 10px;
  border-radius: var(--radius-control);
  font-size: 12.5px;
  font-weight: 800;
}

.delete-project-icon {
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: var(--radius-sm);
  font-size: 15px;
}

.delete-project-btn:hover,
.delete-project-icon:hover {
  background: #ffe4e6;
  border-color: #fda4af;
  color: #9f1239;
}

.delete-project-btn:disabled,
.delete-project-icon:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.w-left {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.w-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 0;
}

.w-tags.compact { gap: 4px; margin-bottom: 3px; }

.tag-pill {
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.tag-pill.subject { background: var(--primary-50); color: var(--primary-700); border: 1px solid var(--primary-200); }
.tag-pill.grade { background: var(--surface-secondary); color: var(--text-secondary); border: 1px solid var(--border-default); }
.tag-pill.duration { background: var(--accent-cyan-soft); color: var(--accent-cyan); border: 1px solid rgba(2, 132, 199, 0.2); }

.w-title {
  margin: 0;
  font-size: 20px;
  font-weight: 900;
  color: var(--text-primary);
  line-height: 1.3;
}

.w-stage-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border-radius: var(--radius-control);
  font-size: 13px;
  font-weight: 700;
  border-left: 3.5px solid transparent;
  transition: all var(--motion-fast);
}

.stage-strip-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stage-dot-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.stage-label {
  color: var(--text-muted);
  font-weight: 600;
}

.stage-val {
  font-weight: 800;
}

.w-stage-strip.warning {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fef3c7;
  border-left: 3.5px solid #f59e0b;
}

.w-stage-strip.warning .stage-val {
  color: #d97706;
}

.w-stage-strip.running {
  background: #f5f3ff;
  color: #6d28d9;
  border: 1px solid #ede9fe;
  border-left: 3.5px solid #7c3aed;
}

.w-stage-strip.running .stage-val {
  color: #7c3aed;
}

.w-stage-strip.success {
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #dcfce7;
  border-left: 3.5px solid #16a34a;
}

.w-stage-strip.success .stage-val {
  color: #16a34a;
}

.w-stage-strip.danger {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fee2e2;
  border-left: 3.5px solid #dc2626;
}

.w-stage-strip.info {
  background: var(--surface-tertiary);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-left: 3.5px solid var(--text-muted);
}

.stage-live { 
  display: flex; 
  align-items: center; 
  gap: 6px; 
  font-size: 12.5px;
  font-weight: 800;
  color: var(--accent-violet);
}

.w-deliv-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
}

.deliv-cell {
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: var(--radius-control);
  padding: 8px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all var(--motion-fast);
  min-width: 0;
}

.deliv-cell:hover {
  background: #ffffff;
  border-color: #cbd5e1;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
}

.deliv-cell.needs-action {
  background: #fffbeb;
  border-color: #fde68a;
}

.deliv-cell.needs-action:hover {
  border-color: #f59e0b;
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.12);
}

.deliv-cell.ready {
  background: #ffffff;
  border-color: #e2e8f0;
}

.deliv-cell.generating {
  background: #faf5ff;
  border-color: #c7d2fe;
}

.deliv-cell.generating:hover {
  border-color: #818cf8;
  box-shadow: 0 4px 14px rgba(124, 58, 237, 0.12);
}

.deliv-status.generating {
  color: #7c3aed;
  font-weight: 800;
}

.deliv-status-dot.generating {
  background: #7c3aed;
  box-shadow: 0 0 6px rgba(124, 58, 237, 0.6);
  animation: pulse-ring 1.5s cubic-bezier(0.24, 0, 0.38, 1) infinite;
}

.live-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent-violet);
  box-shadow: 0 0 8px rgba(124, 58, 237, 0.6);
}

.deliv-ic {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 15px;
  flex-shrink: 0;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
}

.deliv-ic.doc { color: #2563eb; background: #eff6ff; border-color: #dbeafe; }
.deliv-ic.ppt { color: #ea580c; background: #fff7ed; border-color: #ffedd5; }
.deliv-ic.sheet { color: #059669; background: #ecfdf5; border-color: #d1fae5; }
.deliv-ic.quiz { color: #0284c7; background: #f0f9ff; border-color: #e0f2fe; }
.deliv-ic.script { color: #7c3aed; background: #f5f3ff; border-color: #ede9fe; }
.deliv-ic.voice { color: #4f46e5; background: #eef2ff; border-color: #e0e7ff; }
.deliv-ic.video { color: #e11d48; background: #fff1f2; border-color: #ffe4e6; }

.deliv-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.deliv-name { 
  font-size: 13px; 
  font-weight: 800; 
  color: #1e293b; 
  white-space: nowrap; 
}

.deliv-status { 
  font-size: 11.5px; 
  font-weight: 700; 
  color: #94a3b8; 
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.deliv-status.warning { 
  color: #d97706; 
  font-weight: 800;
}

.deliv-status.ready { 
  color: #059669; 
  font-weight: 800;
}

.deliv-status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.deliv-status-dot.pulse {
  background: #f59e0b;
  box-shadow: 0 0 6px rgba(245, 158, 11, 0.6);
  animation: pulse-ring 1.8s cubic-bezier(0.24, 0, 0.38, 1) infinite;
}

.deliv-status-dot.ready {
  background: #10b981;
}

@keyframes pulse-ring {
  0% { transform: scale(0.95); opacity: 0.8; }
  50% { transform: scale(1.4); opacity: 1; }
  100% { transform: scale(0.95); opacity: 0.8; }
}

.w-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px dashed var(--border-default);
}

.footer-time { font-size: 13px; color: var(--text-muted); font-weight: 500; }

.cta-action-btn {
  border: none;
  padding: 7px 18px;
  border-radius: var(--radius-control);
  font-size: 14px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.cta-action-btn.compact { padding: 5px 12px; font-size: 12.5px; }

.cta-action-btn.primary { background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%); color: #ffffff; box-shadow: var(--shadow-glow-primary); }
.cta-action-btn.warning { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: #ffffff; box-shadow: 0 4px 14px rgba(217, 119, 6, 0.3); }
.cta-action-btn.running { background: linear-gradient(135deg, #7c3aed 0%, #6366f1 100%); color: #ffffff; box-shadow: var(--shadow-glow-agent); }
.cta-action-btn.danger { background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); color: #ffffff; }

.cta-action-btn:hover { opacity: 0.94; transform: translateX(2px); }

/* Multi Projects Grid */
.multi-projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
  width: 100%;
}

.grid-card {
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

.grid-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-md);
}

.g-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.g-header-actions { gap: 6px; }
.g-meta { flex: 1; min-width: 0; }
.g-title { margin: 0; font-size: 16px; font-weight: 800; color: var(--text-primary); line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.g-stage { display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px; border-radius: var(--radius-pill); font-size: 12px; font-weight: 700; }
.g-stage.warning { background: var(--accent-amber-soft); color: var(--accent-amber); }
.g-stage.running { background: var(--accent-violet-soft); color: var(--accent-violet); }
.g-stage.success { background: var(--color-success-soft); color: var(--success); }
.g-stage.danger { background: var(--color-danger-soft); color: var(--danger); }
.g-stage.info { background: var(--surface-tertiary); color: var(--text-secondary); }

.g-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }

.g-deliv-bar { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px; padding: 6px 8px; background: var(--surface-secondary); border-radius: var(--radius-control); border: 1px solid var(--border-soft); }
.g-deliv-item { display: flex; align-items: center; gap: 4px; font-size: 11.5px; font-weight: 700; color: var(--text-muted); }
.g-deliv-item.ready { color: var(--accent-mint); }
.g-deliv-ic { font-size: 12px; }

.g-footer { display: flex; align-items: center; justify-content: space-between; padding-top: 6px; border-top: 1px dashed var(--border-default); }

.empty-onboarding-surface {
  padding: 20px 24px;
  background: var(--surface-secondary);
  border-radius: var(--radius-card);
  border: 1.5px dashed var(--border-default);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.onboarding-banner { display: flex; align-items: center; gap: 14px; }
.onboarding-icon-wrap { width: 42px; height: 42px; border-radius: var(--radius-control); background: var(--color-primary-soft); color: var(--color-primary); display: grid; place-items: center; font-size: 20px; }
.onboarding-text h3 { margin: 0; font-size: 18px; font-weight: 900; color: var(--text-primary); }
.onboarding-text p { margin: 2px 0 0; font-size: 13.5px; color: var(--text-muted); }
.onboarding-steps-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.step-box { padding: 10px 12px; background: var(--surface-primary); border: 1px solid var(--border-default); border-radius: var(--radius-control); }
.step-number { font-size: 12.5px; font-weight: 900; color: var(--color-primary); }
.step-title { margin: 2px 0 1px; font-size: 14.5px; font-weight: 800; color: var(--text-primary); }
.step-desc { margin: 0; font-size: 12.5px; color: var(--text-muted); }
.onboarding-cta-row { display: flex; gap: 12px; }

@media (max-width: 1280px) {
  .w-deliv-grid { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 1023px) {
  .dashboard-root-view { overflow: auto; }
  .teacher-dashboard-workbench { height: auto; min-height: calc(100vh - var(--header-height)); overflow: visible; padding: 16px 16px 40px; }
  .workbench-top-bar { flex-direction: column; align-items: flex-start; gap: 8px; }
  .console-row { flex-direction: column; gap: 12px; }
  .panel-v-divider { width: 100%; height: 1px; }
  .live-metrics-bar { flex-direction: column; align-items: flex-start; gap: 8px; }
  .page-title { font-size: 20px; }
}

@media (max-width: 640px) {
  .metrics-right { display: grid; grid-template-columns: repeat(2, 1fr); width: 100%; }
  .m-sep { display: none; }
  .onboarding-steps-row { grid-template-columns: repeat(2, 1fr); }
  .w-deliv-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
