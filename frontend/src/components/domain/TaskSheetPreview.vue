<script setup lang="ts">
import { ref, computed } from 'vue';
import {
  Clock,
  Collection,
  User,
  Printer,
  Aim,
  Notebook,
  Opportunity,
  Checked,
  QuestionFilled,
  Star,
  Reading,
  Check,
  Fold,
  Expand,
  Refresh,
  InfoFilled,
  DocumentChecked,
  Sunny,
  Lightning,
  Sunrise
} from '@element-plus/icons-vue';
import type { TaskSheetContent, TaskSheetPhase } from '../../types';

const props = defineProps<{
  content: TaskSheetContent;
  sourceVersions?: Record<string, number>;
}>();

interface PhaseConfig {
  key: TaskSheetPhase;
  label: string;
  subLabel: string;
  tagClass: string;
  icon: any;
}

const phases: PhaseConfig[] = [
  { key: 'pre_class', label: '课前', subLabel: '自主预习与感知', tagClass: 'phase-pre', icon: Sunrise },
  { key: 'in_class', label: '课中', subLabel: '深度探究与合作', tagClass: 'phase-in', icon: Lightning },
  { key: 'after_class', label: '课后', subLabel: '迁移巩固与复盘', tagClass: 'phase-after', icon: Sunny },
];

const collaborationLabels: Record<string, string> = {
  individual: '👤 独立完成',
  pair: '👥 双人结对',
  group: '👨‍👩‍👧‍👦 小组合作',
  whole_class: '🏫 全班互动'
};

const sourceLabels: Record<string, string> = {
  lesson_plan: '教学设计', ppt: 'PPT 课件', task_sheet: '学习任务单',
  exercise: '课后练习', video_script: '视频脚本', verbatim: '教师逐字稿',
};

const referencedSources = computed(() => Object.entries(props.sourceVersions || {})
  .filter(([type]) => type !== 'task_sheet')
  .map(([type, version]) => `${sourceLabels[type] || type} V${version}`));

// Target Coverage
const coveredObjectiveIds = computed(() => {
  return new Set((props.content.tasks || []).flatMap(task => task.objective_ids || []));
});

const coveredObjectiveCount = computed(() => {
  return (props.content.learning_objectives || []).filter(objective => coveredObjectiveIds.value.has(objective.id)).length;
});

const coveragePercentage = computed(() => {
  const total = props.content.learning_objectives?.length || 0;
  if (total === 0) return 100;
  return Math.round((coveredObjectiveCount.value / total) * 100);
});

// Interactive step completion tracking
const checkedSteps = ref<Record<string, boolean>>({});
function toggleStep(taskId: string, sIdx: number) {
  const key = `${taskId}-${sIdx}`;
  checkedSteps.value[key] = !checkedSteps.value[key];
}

// Calculate Task Step Completion
function getTaskStepProgress(taskId: string, totalSteps: number) {
  if (!totalSteps) return 0;
  let done = 0;
  for (let i = 0; i < totalSteps; i++) {
    if (checkedSteps.value[`${taskId}-${i}`]) done++;
  }
  return Math.round((done / totalSteps) * 100);
}

const totalStepsCount = computed(() => {
  return (props.content.tasks || []).reduce((acc, t) => acc + (t.steps?.length || 0), 0);
});

const completedStepsCount = computed(() => {
  return Object.values(checkedSteps.value).filter(Boolean).length;
});

function resetInteractions() {
  checkedSteps.value = {};
  assessmentRatings.value = {};
}

// Hovered Objective for visual linking
const highlightedObjectiveId = ref<string | null>(null);

function highlightObjective(id: string | null) {
  highlightedObjectiveId.value = id;
}

// Interactive self-assessment state
const assessmentRatings = ref<Record<string, string>>({});
function setAssessmentRating(itemId: string, scale: string) {
  assessmentRatings.value[itemId] = scale;
}

// Collapse / Expand control
const collapsedPhases = ref<Record<string, boolean>>({});
function togglePhaseCollapse(key: string) {
  collapsedPhases.value[key] = !collapsedPhases.value[key];
}

// Print Handler
function handlePrint() {
  window.print();
}
</script>

<template>
  <div class="task-sheet-container">
    <!-- Quick Actions Bar (hidden on print) -->
    <div class="sheet-action-bar">
      <div class="action-bar-info">
        <div class="sheet-badge-group">
          <span class="sheet-badge">
            <el-icon><DocumentChecked /></el-icon>
            A4 智能导学单
          </span>
          <span class="version-tag" v-if="content.schema_version">v{{ content.schema_version }}</span>
        </div>
        <div class="meta-stats-row">
          <span class="meta-stat">
            <el-icon><Opportunity /></el-icon>
            <b>{{ content.tasks?.length || 0 }}</b> 个任务
          </span>
          <span class="stat-divider">•</span>
          <span class="meta-stat">
            <el-icon><Clock /></el-icon>
            预估 <b>{{ content.course_info?.duration_minutes || 45 }}</b> 分钟
          </span>
          <span class="stat-divider">•</span>
          <span class="meta-stat" :class="{ 'is-full': coveragePercentage === 100 }">
            <el-icon><Aim /></el-icon>
            目标对齐 <b>{{ coveragePercentage }}%</b>
          </span>
        </div>
      </div>

      <div class="action-buttons">
        <el-tooltip content="重置勾选与自评进度" placement="top">
          <el-button size="small" circle class="icon-action-btn" @click="resetInteractions">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </el-tooltip>

        <el-button type="primary" class="print-btn" @click="handlePrint">
          <el-icon><Printer /></el-icon>
          打印 / 导出 PDF
        </el-button>
      </div>
    </div>

    <!-- Student Learning Progress Banner (when interactive) -->
    <div v-if="totalStepsCount > 0" class="interactive-progress-bar">
      <div class="progress-info">
        <span class="progress-title">📝 探究步骤完成进度</span>
        <span class="progress-value">{{ completedStepsCount }} / {{ totalStepsCount }} 项步骤 ({{ Math.round((completedStepsCount/totalStepsCount)*100) }}%)</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: `${(completedStepsCount/totalStepsCount)*100}%` }"></div>
      </div>
    </div>

    <!-- Main Sheet Canvas -->
    <article class="task-sheet-preview">
      <!-- Masthead Header -->
      <header class="sheet-masthead">
        <div class="title-wrap">
          <div class="kicker-pill">
            <span class="kicker-dot"></span>
            <span>学习任务单 · 学生导学与探究版</span>
          </div>
          <h1 class="course-title">{{ content.course_info?.course_title || '课程学习任务单' }}</h1>
          <p v-if="(content.course_info as any)?.unit_title" class="unit-subtitle">
            📌 单元主题：{{ (content.course_info as any).unit_title }}
          </p>
        </div>

        <dl class="course-meta">
          <div class="meta-item">
            <dt>学科领域</dt>
            <dd>{{ content.course_info?.subject || '—' }}</dd>
          </div>
          <div class="meta-item">
            <dt>适用对象</dt>
            <dd>{{ content.course_info?.grade_level || content.course_info?.audience || '全体学生' }}</dd>
          </div>
          <div class="meta-item">
            <dt>预计时长</dt>
            <dd>{{ content.course_info?.duration_minutes || 45 }} 分钟</dd>
          </div>
          <div class="meta-item accent">
            <dt>目标达成</dt>
            <dd>{{ coveredObjectiveCount }} / {{ content.learning_objectives?.length || 0 }} 项</dd>
          </div>
        </dl>
      </header>

      <!-- Knowledge Linkage Strip -->
      <div v-if="referencedSources.length" class="knowledge-strip">
        <div class="strip-icon-wrap">
          <el-icon><Collection /></el-icon>
        </div>
        <span><strong>多维教学矩阵对齐：</strong>本任务单基于 {{ referencedSources.join(' · ') }} 自动关联生成</span>
      </div>

      <!-- Section 1: Learning Objectives -->
      <section class="sheet-section objectives-section">
        <header class="section-head">
          <div class="num-badge">1</div>
          <div class="head-text">
            <h2>学习目标与达成标准</h2>
            <span class="head-desc">清晰的目标是高品质学习的起点</span>
          </div>
        </header>

        <div class="objective-cards-grid">
          <article
            v-for="objective in content.learning_objectives"
            :key="objective.id"
            class="obj-card"
            :class="{
              'is-covered': coveredObjectiveIds.has(objective.id),
              'is-highlighted': highlightedObjectiveId === objective.id
            }"
            @mouseenter="highlightObjective(objective.id)"
            @mouseleave="highlightObjective(null)"
          >
            <div class="obj-card-head">
              <span class="obj-badge">{{ objective.id }}</span>
              <span class="obj-chip">
                <el-icon><Aim /></el-icon> 核心素养
              </span>
            </div>
            <p class="obj-statement">{{ objective.statement }}</p>

            <div class="criterion-box">
              <div class="criterion-tag">
                <el-icon><Check /></el-icon> 达成标准
              </div>
              <p class="criterion-text">{{ objective.success_criterion }}</p>
            </div>
          </article>
        </div>
      </section>

      <!-- Section 2: Preparation -->
      <section v-if="content.preparation && content.preparation.length" class="sheet-section preparation-section">
        <header class="section-head">
          <div class="num-badge alt-badge">2</div>
          <div class="head-text">
            <h2>课前准备与学习资源</h2>
            <span class="head-desc">工欲善其事，必先利其器</span>
          </div>
        </header>

        <div class="prep-card">
          <ul class="prep-grid">
            <li v-for="(item, idx) in content.preparation" :key="idx" class="prep-item">
              <span class="prep-num">{{ idx + 1 }}</span>
              <span class="prep-text">{{ item }}</span>
            </li>
          </ul>
        </div>
      </section>

      <!-- Section 3: Learning Tasks -->
      <section class="sheet-section tasks-section">
        <header class="section-head">
          <div class="num-badge">3</div>
          <div class="head-text">
            <h2>探究学习任务链</h2>
            <span class="head-desc">按教学流程分阶段推进自主与协同探究</span>
          </div>
        </header>

        <template v-for="phase in phases" :key="phase.key">
          <div
            v-if="content.tasks && content.tasks.some(task => task.phase === phase.key)"
            class="phase-group"
            :class="[phase.tagClass, { 'is-collapsed': collapsedPhases[phase.key] }]"
          >
            <!-- Phase Header Banner -->
            <div class="phase-banner" @click="togglePhaseCollapse(phase.key)">
              <div class="phase-title-left">
                <component :is="phase.icon" class="phase-icon" />
                <h3>{{ phase.label }}阶段</h3>
                <span class="phase-sub">{{ phase.subLabel }}</span>
              </div>

              <div class="phase-title-right">
                <span class="phase-count-chip">
                  {{ content.tasks.filter(t => t.phase === phase.key).length }} 个探究任务
                </span>
                <el-icon class="collapse-icon">
                  <Fold v-if="!collapsedPhases[phase.key]" />
                  <Expand v-else />
                </el-icon>
              </div>
            </div>

            <!-- Phase Task Cards -->
            <div v-show="!collapsedPhases[phase.key]" class="phase-tasks-wrapper">
              <article
                v-for="task in content.tasks.filter(item => item.phase === phase.key)"
                :key="task.id"
                class="task-card"
              >
                <!-- Task Head Bar -->
                <div class="task-card-head">
                  <div class="task-folio-wrap">
                    <span class="task-folio">{{ task.id }}</span>
                  </div>

                  <div class="task-title-group">
                    <div class="task-title-row">
                      <h4>{{ task.title }}</h4>
                      <span class="stage-tag" v-if="task.stage_id">环节：{{ task.stage_id }}</span>
                    </div>
                  </div>

                  <div class="task-facts">
                    <span class="fact-pill time">
                      <el-icon><Clock /></el-icon>
                      {{ task.estimated_minutes }} 分钟
                    </span>
                    <span class="fact-pill mode" v-if="task.collaboration_mode">
                      {{ collaborationLabels[task.collaboration_mode] || task.collaboration_mode }}
                    </span>
                  </div>
                </div>

                <!-- Objective Mapping Row -->
                <div class="mapping-row">
                  <div class="obj-tags">
                    <span class="meta-label">关联目标：</span>
                    <span
                      v-for="objectiveId in task.objective_ids"
                      :key="objectiveId"
                      class="obj-mini-tag"
                      :class="{ 'is-active': highlightedObjectiveId === objectiveId }"
                    >
                      {{ objectiveId }}
                    </span>
                  </div>

                  <div class="action-desc" v-if="task.action || task.object">
                    <span class="action-badge">核心动作</span>
                    <span class="action-text"><strong>{{ task.action }}</strong> · {{ task.object }}</span>
                  </div>
                </div>

                <!-- Steps Block with Interactivity -->
                <div class="steps-block" v-if="task.steps && task.steps.length">
                  <div class="steps-header">
                    <span class="steps-heading">
                      <el-icon><Opportunity /></el-icon> 探究步骤与引导
                    </span>
                    <span class="steps-progress-mini" v-if="getTaskStepProgress(task.id, task.steps.length) > 0">
                      完成度 {{ getTaskStepProgress(task.id, task.steps.length) }}%
                    </span>
                  </div>

                  <ol class="steps-list">
                    <li
                      v-for="(step, sIdx) in task.steps"
                      :key="sIdx"
                      :class="{ 'is-completed': checkedSteps[`${task.id}-${sIdx}`] }"
                      @click="toggleStep(task.id, sIdx)"
                    >
                      <span class="custom-checkbox">
                        <el-icon v-if="checkedSteps[`${task.id}-${sIdx}`]"><Check /></el-icon>
                      </span>
                      <span class="step-num">{{ sIdx + 1 }}.</span>
                      <span class="step-text">{{ step }}</span>
                    </li>
                  </ol>
                </div>

                <!-- Evidence Grid: Output & Completion Criterion -->
                <div class="evidence-grid" v-if="task.student_output || task.completion_criterion">
                  <div class="evidence-box output-box" v-if="task.student_output">
                    <div class="evidence-title">
                      <el-icon><Checked /></el-icon>
                      <b>预期成果要求</b>
                    </div>
                    <p>{{ task.student_output }}</p>
                  </div>

                  <div class="evidence-box criterion-box-task" v-if="task.completion_criterion">
                    <div class="evidence-title">
                      <el-icon><Star /></el-icon>
                      <b>评价与完成标准</b>
                    </div>
                    <p>{{ task.completion_criterion }}</p>
                  </div>
                </div>

                <!-- Scaffolds (Tips/Thinking Helpers) -->
                <div v-if="task.scaffolds && task.scaffolds.length" class="scaffold-box">
                  <div class="scaffold-label">
                    <el-icon><InfoFilled /></el-icon>
                    <span>思考脚手架：</span>
                  </div>
                  <div class="scaffold-list">
                    <span v-for="(item, sIdx) in task.scaffolds" :key="sIdx" class="scaffold-item">
                      💡 {{ item }}
                    </span>
                  </div>
                </div>

                <!-- Embedded Task Record Table -->
                <div v-if="task.record_table" class="record-block">
                  <div class="record-head">
                    <h5>📋 {{ task.record_table.title }}</h5>
                    <p v-if="task.record_table.instructions" class="record-instruction">
                      说明：{{ task.record_table.instructions }}
                    </p>
                  </div>

                  <div class="record-scroll">
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th style="width: 48px; text-align: center;">#</th>
                          <th v-for="column in task.record_table.columns" :key="column">{{ column }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="row in task.record_table.blank_rows" :key="row">
                          <td style="text-align: center; color: #94a3b8; font-size: 11px;">{{ row }}</td>
                          <td v-for="column in task.record_table.columns" :key="column">
                            <div class="table-fill-placeholder"></div>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </article>
            </div>
          </div>
        </template>
      </section>

      <!-- Section 4: Global Record Table (if standalone) -->
      <section v-if="content.record_table" class="sheet-section record-section">
        <header class="section-head">
          <div class="num-badge alt-badge">4</div>
          <div class="head-text">
            <h2>{{ content.record_table.title }}</h2>
            <span class="head-desc">{{ content.record_table.instructions || '请将探究实验/观察过程记录在下方表格中' }}</span>
          </div>
        </header>

        <div class="record-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 48px; text-align: center;">#</th>
                <th v-for="column in content.record_table.columns" :key="column">{{ column }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in content.record_table.blank_rows" :key="row">
                <td style="text-align: center; color: #94a3b8; font-size: 11px;">{{ row }}</td>
                <td v-for="column in content.record_table.columns" :key="column">
                  <div class="table-fill-placeholder"></div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Section 5: Reflection Questions -->
      <section v-if="content.learning_questions && content.learning_questions.length" class="sheet-section questions-section">
        <header class="section-head">
          <div class="num-badge">5</div>
          <div class="head-text">
            <h2>深度思考与延伸反思</h2>
            <span class="head-desc">连点成线，提升高阶思维能力</span>
          </div>
        </header>

        <div class="questions-grid">
          <article v-for="question in content.learning_questions" :key="question.id" class="question-card">
            <div class="question-head">
              <span class="q-id-tag">{{ question.id }}</span>
              <span class="q-meta" v-if="question.objective_ids && question.objective_ids.length">
                🎯 关联目标：{{ question.objective_ids.join('、') }}
              </span>
            </div>
            <p class="q-prompt">{{ question.prompt }}</p>

            <div class="answer-space">
              <div class="answer-lines">
                <div class="line"></div>
                <div class="line"></div>
                <div class="line"></div>
              </div>
            </div>
          </article>
        </div>
      </section>

      <!-- Section 6: Self Assessment -->
      <section v-if="content.self_assessment && content.self_assessment.length" class="sheet-section assessment-section">
        <header class="section-head">
          <div class="num-badge alt-badge">6</div>
          <div class="head-text">
            <h2>学习成效自我评价</h2>
            <span class="head-desc">客观复盘学习收获，明确后续改进方向</span>
          </div>
        </header>

        <div class="assessment-table-wrap">
          <table class="assessment-table">
            <thead>
              <tr>
                <th class="statement-header">评价维度 / 评价指标</th>
                <th
                  v-for="scale in content.self_assessment_scale"
                  :key="scale"
                  class="scale-header"
                >
                  {{ scale }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in content.self_assessment" :key="item.id">
                <td class="statement-col">
                  <span class="sa-id" v-if="item.id">{{ item.id }}</span>
                  <span class="sa-text">{{ item.statement }}</span>
                </td>
                <td
                  v-for="scale in content.self_assessment_scale"
                  :key="scale"
                  class="check-col"
                  :class="{ 'is-selected': assessmentRatings[item.id] === scale }"
                  @click="setAssessmentRating(item.id, scale)"
                >
                  <div class="rating-cell-content">
                    <el-icon v-if="assessmentRatings[item.id] === scale"><Check /></el-icon>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Section 7: Extension -->
      <section v-if="content.extension && content.extension.length" class="sheet-section extension-section">
        <header class="section-head">
          <div class="num-badge">7</div>
          <div class="head-text">
            <h2>课后拓展与迁移实践</h2>
            <span class="head-desc">学以致用，探索更广阔的领域</span>
          </div>
        </header>

        <div class="extension-card">
          <ul class="prep-grid">
            <li v-for="(item, idx) in content.extension" :key="idx" class="prep-item">
              <span class="ext-bullet">🚀</span>
              <span class="prep-text">{{ item }}</span>
            </li>
          </ul>

          <div class="answer-space" style="margin-top: 16px;">
            <div class="answer-lines">
              <div class="line"></div>
              <div class="line"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- Sheet Footer -->
      <footer class="sheet-footer">
        <div class="footer-left">
          <span>LessonForge AI 课启智造 · 标准教学资源</span>
        </div>
        <div class="footer-right">
          <span>学生姓名：_________________</span>
          <span style="margin-left: 20px;">班级：_____________</span>
          <span style="margin-left: 20px;">日期：____月____日</span>
        </div>
      </footer>
    </article>
  </div>
</template>

<style scoped>
.task-sheet-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: #0f172a;
}

/* Quick Actions Top Bar */
.sheet-action-bar {
  width: min(100%, 920px);
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  padding: 12px 20px;
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-default, #e2e8f0);
  border-radius: 14px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.04);
}

.action-bar-info {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.sheet-badge-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sheet-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #4338ca;
  background: #e0e7ff;
  border: 1px solid #c7d2fe;
  padding: 4px 12px;
  border-radius: 999px;
}

.version-tag {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}

.meta-stats-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.meta-stat {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12.5px;
  color: #64748b;
  font-weight: 500;
}

.meta-stat b {
  color: #0f172a;
  font-weight: 700;
}

.meta-stat.is-full b {
  color: #16a34a;
}

.stat-divider {
  color: #cbd5e1;
  font-size: 10px;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 10px;
}

.icon-action-btn {
  border-color: #cbd5e1;
}

.print-btn {
  font-weight: 600;
  border-radius: 8px;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
  border: none;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25);
  transition: all 0.2s ease;
}

.print-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.35);
}

/* Interactive Progress Banner */
.interactive-progress-bar {
  width: min(100%, 920px);
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  padding: 10px 18px;
  margin-bottom: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 6px;
}

.progress-title {
  font-weight: 700;
  color: #334155;
}

.progress-value {
  font-weight: 700;
  color: #4f46e5;
}

.progress-track {
  width: 100%;
  height: 6px;
  background: #f1f5f9;
  border-radius: 999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4f46e5 0%, #10b981 100%);
  border-radius: 999px;
  transition: width 0.3s ease;
}

/* Main A4 Preview Sheet Container */
.task-sheet-preview {
  width: min(100%, 920px);
  margin: 0 auto;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 16px;
  color: #0f172a;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.07), 0 2px 6px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

/* Masthead Header */
.sheet-masthead {
  padding: 36px 40px 28px;
  background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
  border-top: 6px solid #4f46e5;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  gap: 28px;
  align-items: flex-end;
}

.kicker-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  font-weight: 800;
  color: #4338ca;
  background: #e0e7ff;
  border: 1px solid #c7d2fe;
  padding: 3px 12px;
  border-radius: 999px;
  letter-spacing: 0.03em;
}

.kicker-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4f46e5;
}

.course-title {
  margin: 12px 0 0;
  font-size: clamp(22px, 3.2vw, 28px);
  font-weight: 900;
  color: #0f172a;
  line-height: 1.25;
  letter-spacing: -0.02em;
}

.unit-subtitle {
  margin: 6px 0 0;
  font-size: 13.5px;
  font-weight: 600;
  color: #475569;
}

.course-meta {
  display: grid;
  grid-template-columns: repeat(4, auto);
  margin: 0;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
}

.course-meta .meta-item {
  min-width: 90px;
  padding: 10px 14px;
  border-right: 1px solid #e2e8f0;
}

.course-meta .meta-item:last-child {
  border-right: 0;
}

.course-meta .meta-item.accent {
  background: #eef2ff;
}

.course-meta dt {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.course-meta dd {
  margin: 4px 0 0;
  font-size: 13.5px;
  font-weight: 800;
  color: #0f172a;
}

.course-meta .meta-item.accent dd {
  color: #4f46e5;
}

/* Knowledge Strip */
.knowledge-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 40px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  font-size: 12.5px;
}

.strip-icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #e0e7ff;
  color: #4f46e5;
}

/* Section Headings */
.sheet-section {
  padding: 32px 40px;
  border-bottom: 1px solid #e2e8f0;
}

.sheet-section:last-of-type {
  border-bottom: 0;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 22px;
}

.num-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
  color: #ffffff;
  font-size: 16px;
  font-weight: 900;
  box-shadow: 0 4px 10px rgba(79, 70, 229, 0.22);
  flex-shrink: 0;
}

.num-badge.alt-badge {
  background: linear-gradient(135deg, #0f766e 0%, #14b8a6 100%);
  box-shadow: 0 4px 10px rgba(20, 184, 166, 0.22);
}

.head-text h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.head-desc {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

/* Objectives Cards Grid */
.objective-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}

.obj-card {
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  padding: 18px 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
}

.obj-card:hover,
.obj-card.is-highlighted {
  border-color: #6366f1;
  box-shadow: 0 6px 18px rgba(79, 70, 229, 0.12);
  transform: translateY(-2px);
}

.obj-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.obj-badge {
  font-size: 11.5px;
  font-weight: 900;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 2px 10px;
  border-radius: 999px;
}

.obj-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}

.obj-statement {
  margin: 0 0 14px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.6;
  flex-grow: 1;
}

.criterion-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-left: 3.5px solid #6366f1;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
}

.criterion-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 800;
  color: #4f46e5;
  margin-bottom: 4px;
  font-size: 11px;
}

.criterion-text {
  margin: 0;
  color: #475569;
  font-weight: 600;
  line-height: 1.5;
}

/* Preparation & Extension Component */
.prep-card, .extension-card {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  padding: 18px 22px;
}

.prep-grid {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.prep-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  font-size: 14px;
  color: #1e293b;
  font-weight: 600;
  line-height: 1.6;
}

.prep-num {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e0e7ff;
  color: #4338ca;
  font-size: 11px;
  font-weight: 900;
  flex-shrink: 0;
  margin-top: 1px;
}

.ext-bullet {
  font-size: 16px;
  flex-shrink: 0;
}

/* Tasks & Phases */
.phase-group {
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  overflow: hidden;
  margin-bottom: 24px;
  background: #ffffff;
}

.phase-group:last-child {
  margin-bottom: 0;
}

.phase-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}

.phase-pre .phase-banner { background: #f0fdf4; border-bottom: 1px solid #bbf7d0; }
.phase-in .phase-banner { background: #eef2ff; border-bottom: 1px solid #c7d2fe; }
.phase-after .phase-banner { background: #fffbeb; border-bottom: 1px solid #fde68a; }

.phase-title-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.phase-icon {
  font-size: 18px;
}

.phase-pre .phase-icon { color: #16a34a; }
.phase-in .phase-icon { color: #4f46e5; }
.phase-after .phase-icon { color: #d97706; }

.phase-banner h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.phase-sub {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.phase-title-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.phase-count-chip {
  font-size: 11.5px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
}

.phase-pre .phase-count-chip { background: #dcfce7; color: #15803d; }
.phase-in .phase-count-chip { background: #e0e7ff; color: #4338ca; }
.phase-after .phase-count-chip { background: #fef3c7; color: #b45309; }

.collapse-icon {
  font-size: 16px;
  color: #64748b;
}

.phase-tasks-wrapper {
  padding: 16px;
}

/* Individual Task Card */
.task-card {
  margin-bottom: 18px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
}

.task-card:last-child {
  margin-bottom: 0;
}

.task-card-head {
  display: flex;
  align-items: center;
  background: #f8fafc;
  border-bottom: 1.5px solid #e2e8f0;
  padding: 12px 18px;
  gap: 16px;
}

.task-folio-wrap {
  flex-shrink: 0;
}

.task-folio {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 12px;
  border-radius: 8px;
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 900;
  letter-spacing: 0.02em;
}

.phase-pre .task-folio { background: linear-gradient(135deg, #16a34a 0%, #22c55e 100%); }
.phase-in .task-folio { background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%); }
.phase-after .task-folio { background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%); }

.task-title-group {
  flex-grow: 1;
}

.task-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.task-title-row h4 {
  margin: 0;
  font-size: 15.5px;
  font-weight: 800;
  color: #0f172a;
}

.stage-tag {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 4px;
}

.task-facts {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.fact-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  color: #475569;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 3px 10px;
  border-radius: 999px;
}

/* Mapping Row */
.mapping-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 18px;
  background: #fafafa;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
}

.obj-tags {
  display: flex;
  align-items: center;
  gap: 6px;
}

.meta-label {
  color: #64748b;
  font-weight: 600;
}

.obj-mini-tag {
  padding: 2px 8px;
  border-radius: 4px;
  background: #4f46e5;
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
  transition: all 0.2s ease;
}

.obj-mini-tag.is-active {
  background: #16a34a;
  transform: scale(1.05);
}

.action-desc {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.action-badge {
  font-size: 10.5px;
  font-weight: 800;
  color: #4338ca;
  background: #e0e7ff;
  padding: 1px 6px;
  border-radius: 4px;
}

.action-text {
  color: #334155;
}

/* Steps Block */
.steps-block {
  padding: 16px 20px;
}

.steps-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.steps-heading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 800;
  color: #1e293b;
}

.steps-progress-mini {
  font-size: 11.5px;
  font-weight: 700;
  color: #16a34a;
}

.steps-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.steps-list li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}

.steps-list li:hover {
  background: #eef2ff;
  border-color: #c7d2fe;
}

.steps-list li.is-completed {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.steps-list li.is-completed .step-text {
  text-decoration: line-through;
  color: #64748b;
}

.custom-checkbox {
  width: 18px;
  height: 18px;
  border: 1.5px solid #94a3b8;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
  background: #ffffff;
  transition: all 0.15s ease;
}

.steps-list li.is-completed .custom-checkbox {
  background: #16a34a;
  border-color: #16a34a;
  color: #ffffff;
}

.step-num {
  font-weight: 800;
  color: #475569;
  font-size: 13px;
}

.step-text {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  line-height: 1.55;
}

/* Evidence Grid */
.evidence-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 1px solid #e2e8f0;
  background: #fafafa;
}

.evidence-box {
  padding: 12px 18px;
}

.evidence-box + .evidence-box {
  border-left: 1px solid #e2e8f0;
}

.evidence-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #4f46e5;
  font-size: 12px;
  margin-bottom: 4px;
}

.evidence-title b {
  font-weight: 800;
}

.evidence-box p {
  margin: 0;
  line-height: 1.55;
  font-size: 13px;
  color: #334155;
  font-weight: 600;
}

/* Scaffold Box */
.scaffold-box {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 10px 18px;
  border-top: 1px solid #e2e8f0;
  background: #f5f3ff;
}

.scaffold-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #6d28d9;
  font-size: 12px;
  font-weight: 800;
  flex-shrink: 0;
  margin-top: 2px;
}

.scaffold-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.scaffold-item {
  color: #5b21b6;
  font-size: 12px;
  font-weight: 600;
  background: #ede9fe;
  padding: 3px 10px;
  border-radius: 6px;
}

/* Record Block Tables */
.record-block {
  padding: 18px 20px;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
}

.record-head h5 {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 800;
  color: #0f172a;
}

.record-instruction {
  margin: 0 0 12px;
  color: #64748b;
  font-size: 12px;
}

.record-scroll {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  min-width: 480px;
  border-collapse: collapse;
  table-layout: fixed;
  border-radius: 8px;
  overflow: hidden;
  border: 1.5px solid #cbd5e1;
}

.data-table th,
.data-table td {
  height: 40px;
  border: 1px solid #cbd5e1;
  padding: 8px 12px;
}

.data-table th {
  background: #f1f5f9;
  color: #1e293b;
  font-size: 12.5px;
  font-weight: 800;
  text-align: left;
}

.data-table tbody tr:nth-child(even) {
  background: #fafafa;
}

.table-fill-placeholder {
  width: 100%;
  height: 100%;
  min-height: 20px;
}

/* Questions Grid */
.questions-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.question-card {
  padding: 18px 20px;
  background: #f8fafc;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
}

.question-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.q-id-tag {
  font-size: 11.5px;
  font-weight: 900;
  color: #ffffff;
  background: #4f46e5;
  padding: 2px 8px;
  border-radius: 6px;
}

.q-meta {
  color: #64748b;
  font-size: 11.5px;
  font-weight: 600;
}

.q-prompt {
  margin: 0 0 16px;
  font-size: 14.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.6;
}

.answer-space {
  padding: 8px 0;
}

.answer-lines {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.answer-lines .line {
  height: 1px;
  border-bottom: 1.5px dashed #cbd5e1;
}

/* Assessment Table */
.assessment-table-wrap {
  overflow-x: auto;
}

.assessment-table {
  width: 100%;
  min-width: 600px;
  border: 1.5px solid #cbd5e1;
  border-collapse: collapse;
  table-layout: fixed;
  border-radius: 10px;
  overflow: hidden;
}

.assessment-table th,
.assessment-table td {
  padding: 12px 14px;
  border: 1px solid #cbd5e1;
  text-align: center;
  font-size: 13px;
}

.assessment-table .statement-header {
  width: 50%;
  text-align: left;
  background: #f1f5f9;
  color: #1e293b;
  font-weight: 800;
}

.assessment-table .scale-header {
  background: #f1f5f9;
  color: #1e293b;
  font-weight: 800;
}

.statement-col {
  text-align: left;
  font-weight: 700;
  color: #0f172a;
}

.sa-id {
  display: inline-block;
  font-size: 11px;
  font-weight: 900;
  color: #4f46e5;
  background: #eef2ff;
  padding: 2px 6px;
  border-radius: 4px;
  margin-right: 8px;
}

.sa-text {
  line-height: 1.5;
}

.check-col {
  cursor: pointer;
  transition: background 0.15s ease;
}

.check-col:hover {
  background: #f1f5f9;
}

.check-col.is-selected {
  background: #e0e7ff;
}

.rating-cell-content {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1.5px solid #94a3b8;
  border-radius: 6px;
  background: #ffffff;
  transition: all 0.15s ease;
}

.check-col.is-selected .rating-cell-content {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #ffffff;
}

/* Sheet Footer */
.sheet-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 40px;
  background: #f8fafc;
  border-top: 1px solid #e2e8f0;
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

/* Responsive Media Queries */
@media (max-width: 768px) {
  .sheet-action-bar {
    flex-direction: column;
    gap: 12px;
    align-items: stretch;
  }
  .sheet-masthead {
    padding: 24px 20px;
    flex-direction: column;
    align-items: flex-start;
  }
  .course-meta {
    width: 100%;
    grid-template-columns: repeat(2, 1fr);
  }
  .sheet-section {
    padding: 24px 20px;
  }
  .evidence-grid {
    grid-template-columns: 1fr;
  }
  .evidence-box + .evidence-box {
    border-left: 0;
    border-top: 1px solid #e2e8f0;
  }
  .task-card-head {
    flex-direction: column;
    align-items: flex-start;
  }
  .task-facts {
    width: 100%;
    justify-content: flex-start;
  }
}

/* High Quality Print Styles */
@media print {
  .sheet-action-bar,
  .interactive-progress-bar {
    display: none !important;
  }
  .task-sheet-preview {
    width: 100% !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 0 !important;
  }
  .sheet-masthead {
    border-top: 4px solid #4f46e5 !important;
  }
  .task-card, .sheet-section {
    break-inside: avoid;
  }
}
</style>



