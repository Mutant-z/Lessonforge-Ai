<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ArrowRight, CircleCheck, Document, Warning } from '@element-plus/icons-vue';
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
  <div v-if="store.loading && !store.project" class="project-loading"><el-skeleton :rows="8" animated /></div>
  <ProjectShell v-else-if="store.project">
    <div class="overview-scroll">
      <section class="overview-lead">
        <div>
          <span class="folio">PROJECT / {{ store.project.course.id.slice(0, 8).toUpperCase() }}</span>
          <h2>{{ store.project.intent.headline }}</h2>
          <p>六个专属 Agent 正在按任务依赖生成并维护课程交付文件。进入任一任务即可继续对话修改。</p>
        </div>
        <div class="progress-figure">
          <strong>{{ store.completion }}%</strong>
          <span>整体生成进度</span>
        </div>
      </section>

      <section v-if="store.project.planning.status !== 'ready'" class="planning-line">
        <span class="planning-index">00</span>
        <div>
          <strong>{{ store.project.planning.status === 'failed' ? '内部规划失败' : '正在将教学意图转化为任务上下文' }}</strong>
          <p>{{ store.project.planning.error?.message || '完成后将自动启动教学设计、PPT、任务单和练习 Agent。' }}</p>
          <button v-if="store.project.planning.status === 'failed'" type="button" class="planning-retry" @click="store.retryPlanning(courseId)">重试内部规划</button>
        </div>
        <span>{{ store.project.planning.progress }}%</span>
      </section>

      <div class="overview-grid">
        <section class="intent-panel">
          <header><span>已确认的教学意图</span><strong>V{{ store.project.course.current_blueprint_version || 1 }}</strong></header>
          <div class="intent-main">
            <dl>
              <div><dt>课程核心任务</dt><dd>{{ store.project.intent.course_task || '围绕课程主题完成理解与基础应用' }}</dd></div>
              <div><dt>授课对象与场景</dt><dd>{{ store.project.intent.audience }} · {{ store.project.intent.scenario }}</dd></div>
              <div><dt>教学目标</dt><dd>{{ store.project.intent.teaching_objectives || '由内部规划结合课程任务形成可观察学习目标' }}</dd></div>
              <div><dt>重点与难点</dt><dd>{{ store.project.intent.key_points || '核心概念与关键关系' }}；{{ store.project.intent.difficulty_points || '在新情境中应用方法' }}</dd></div>
              <div><dt>教学方式</dt><dd>{{ store.project.intent.teaching_method || '情境驱动、讲练结合' }}</dd></div>
              <div><dt>呈现风格</dt><dd>{{ store.project.intent.style_requirements || '清晰、可讲解、适合课堂投放' }}</dd></div>
            </dl>
          </div>
        </section>

        <aside class="project-summary">
          <header>项目状态</header>
          <div class="summary-number"><strong>{{ approvedCount }}</strong><span>/ 6 项已确认</span></div>
          <div class="summary-row"><span>运行中的 Agent</span><strong>{{ activeCount }}</strong></div>
          <div class="summary-row"><span>需要教师处理</span><strong>{{ attentionCount }}</strong></div>
          <div class="summary-row"><span>质量得分</span><strong>{{ store.project.quality.score ?? '—' }}</strong></div>
          <p>{{ store.project.quality.summary }}</p>
        </aside>
      </div>

      <section class="task-list">
        <header><span>交付任务</span><span>点击进入对应 Agent 工作区</span></header>
        <button v-for="task in store.tasks" :key="task.id" type="button" @click="router.push(`/courses/${courseId}/tasks/${task.task_type}`)">
          <span class="list-number">{{ String(task.display_order).padStart(2, '0') }}</span>
          <span class="list-title"><strong>{{ task.display_name }}</strong><small>{{ task.agent_name }}</small></span>
          <span class="list-dependency">{{ task.dependency_types.length ? `依赖：${task.dependency_types.map(type => store.tasks.find(x => x.task_type === type)?.display_name).join('、')}` : '内部规划完成后自动启动' }}</span>
          <span class="list-status" :class="task.status">
            <el-icon v-if="task.status === 'approved'"><CircleCheck /></el-icon>
            <el-icon v-else-if="['failed','stale'].includes(task.status)"><Warning /></el-icon>
            <el-icon v-else><Document /></el-icon>
            {{ task.status === 'review' ? '待确认' : task.status === 'approved' ? '已确认' : task.status === 'stale' ? '待同步' : task.status === 'failed' ? '需重试' : task.status === 'running' ? `${task.progress}%` : task.status === 'queued' ? '排队中' : '等待依赖' }}
          </span>
          <el-icon><ArrowRight /></el-icon>
        </button>
      </section>
    </div>
  </ProjectShell>
</template>

<style scoped>
.project-loading { padding: 32px; }
.overview-scroll { height: 100%; overflow-y: auto; padding: 28px 30px 40px; box-sizing: border-box; }
.overview-lead { display: grid; grid-template-columns: minmax(0,1fr) 180px; gap: 28px; padding-bottom: 28px; border-bottom: 1px solid #cfd2d9; }
.folio { font-size: 11px; font-weight: 800; color: #002fa7; letter-spacing: .08em; }
.overview-lead h2 { max-width: 900px; margin: 12px 0 8px; font-size: clamp(26px, 3vw, 42px); line-height: 1.08; letter-spacing: -.035em; }
.overview-lead p { max-width: 760px; margin: 0; color: #656a73; font-size: 14px; }
.progress-figure { border-left: 1px solid #cfd2d9; padding-left: 24px; display: flex; flex-direction: column; justify-content: flex-end; }
.progress-figure strong { color: #002fa7; font-size: 48px; line-height: 1; font-variant-numeric: tabular-nums; }
.progress-figure span { margin-top: 8px; color: #656a73; font-size: 12px; }
.planning-line { display: grid; grid-template-columns: 50px 1fr auto; align-items: center; gap: 18px; margin-top: 18px; padding: 14px 16px; background: #fff; border: 1px solid #cfd2d9; }
.planning-index { font-size: 24px; color: #002fa7; font-weight: 800; }
.planning-line p { margin: 3px 0 0; font-size: 12px; color: #656a73; }
.planning-retry { margin-top: 7px; padding: 0; border: 0; background: transparent; color: #002fa7; font-weight: 700; cursor: pointer; }
.overview-grid { display: grid; grid-template-columns: minmax(0,1fr) 310px; border: 1px solid #cfd2d9; margin-top: 22px; background: #fff; }
.intent-panel { border-right: 1px solid #cfd2d9; }
.intent-panel header, .project-summary header, .task-list header { min-height: 44px; padding: 0 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #d9dce3; font-size: 13px; font-weight: 800; }
.intent-panel header strong { color: #002fa7; }
.intent-main { padding: 8px 18px 18px; }
.intent-main dl { margin: 0; }
.intent-main dl div { display: grid; grid-template-columns: 150px 1fr; gap: 18px; padding: 11px 0; border-bottom: 1px solid #eceef2; }
.intent-main dl div:last-child { border-bottom: 0; }
.intent-main dt { color: #656a73; font-size: 12px; }
.intent-main dd { margin: 0; font-size: 14px; line-height: 1.55; }
.project-summary { padding-bottom: 16px; }
.summary-number { padding: 20px 16px; display: flex; align-items: baseline; gap: 8px; border-bottom: 1px solid #d9dce3; }
.summary-number strong { color: #002fa7; font-size: 44px; line-height: 1; }
.summary-number span { color: #656a73; font-size: 12px; }
.summary-row { padding: 10px 16px; display: flex; justify-content: space-between; font-size: 13px; border-bottom: 1px solid #eceef2; }
.project-summary p { margin: 14px 16px 0; color: #656a73; font-size: 12px; line-height: 1.55; }
.task-list { margin-top: 22px; border: 1px solid #cfd2d9; background: #fff; }
.task-list header span:last-child { color: #656a73; font-weight: 400; }
.task-list button { width: 100%; min-height: 64px; display: grid; grid-template-columns: 52px minmax(160px,1.2fr) minmax(220px,1.5fr) 110px 20px; align-items: center; gap: 14px; padding: 0 16px; border: 0; border-bottom: 1px solid #d9dce3; background: #fff; text-align: left; cursor: pointer; }
.task-list button:last-child { border-bottom: 0; }
.task-list button:hover { background: #f7f7f8; }
.list-number { color: #002fa7; font-size: 20px; font-weight: 800; }
.list-title { display: flex; flex-direction: column; }
.list-title small, .list-dependency { color: #656a73; font-size: 12px; }
.list-status { display: flex; align-items: center; gap: 5px; font-size: 12px; }
.list-status.failed { color: #b42318; }.list-status.stale { color: #9a6700; }.list-status.approved { color: #067647; }
@media (max-width: 980px) { .overview-grid { grid-template-columns: 1fr; }.intent-panel { border-right: 0; border-bottom: 1px solid #cfd2d9; }.task-list button { grid-template-columns: 44px 1fr 100px 18px; }.list-dependency { display:none; } }
@media (max-width: 640px) { .overview-scroll { padding: 18px 14px 28px; }.overview-lead { grid-template-columns: 1fr; }.progress-figure { border-left: 0; border-top: 1px solid #cfd2d9; padding: 16px 0 0; }.intent-main dl div { grid-template-columns: 1fr; gap: 4px; }.task-list button { grid-template-columns: 38px 1fr 80px 16px; } }
</style>
