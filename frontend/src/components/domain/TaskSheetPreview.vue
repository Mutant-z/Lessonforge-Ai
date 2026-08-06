<script setup lang="ts">
import { computed } from 'vue';
import { Clock, Collection, User } from '@element-plus/icons-vue';
import type { TaskSheetContent, TaskSheetPhase } from '../../types';

const props = defineProps<{
  content: TaskSheetContent;
  sourceVersions?: Record<string, number>;
}>();

const phases: Array<{ key: TaskSheetPhase; label: string }> = [
  { key: 'pre_class', label: '课前' },
  { key: 'in_class', label: '课中' },
  { key: 'after_class', label: '课后' },
];
const collaborationLabels = { individual: '独立', pair: '结对', group: '小组', whole_class: '全班' };
const sourceLabels: Record<string, string> = {
  lesson_plan: '教学设计', ppt: 'PPT 课件', task_sheet: '学习任务单',
  exercise: '课后练习', video_script: '视频脚本', verbatim: '教师逐字稿',
};
const referencedSources = computed(() => Object.entries(props.sourceVersions || {})
  .filter(([type]) => type !== 'task_sheet')
  .map(([type, version]) => `${sourceLabels[type] || type} V${version}`));
const coveredObjectiveCount = computed(() => {
  const covered = new Set(props.content.tasks.flatMap(task => task.objective_ids));
  return props.content.learning_objectives.filter(objective => covered.has(objective.id)).length;
});
</script>

<template>
  <article class="task-sheet-preview">
    <header class="sheet-masthead">
      <div class="title-wrap">
        <div class="kicker-pill">
          <span class="kicker-dot"></span>
          <span>学习任务单 · 学生版</span>
        </div>
        <h1>{{ content.course_info.course_title }}</h1>
      </div>
      <dl class="course-meta">
        <div class="meta-item">
          <dt>学科</dt>
          <dd>{{ content.course_info.subject || '—' }}</dd>
        </div>
        <div class="meta-item">
          <dt>年级</dt>
          <dd>{{ content.course_info.grade_level || content.course_info.audience || '—' }}</dd>
        </div>
        <div class="meta-item">
          <dt>预计时长</dt>
          <dd>{{ content.course_info.duration_minutes }} 分钟</dd>
        </div>
        <div class="meta-item accent">
          <dt>目标覆盖</dt>
          <dd>{{ coveredObjectiveCount }} / {{ content.learning_objectives.length }}</dd>
        </div>
      </dl>
    </header>

    <div v-if="referencedSources.length" class="knowledge-strip">
      <el-icon><Collection /></el-icon>
      <span>本版本参考了：{{ referencedSources.join(' · ') }}</span>
    </div>

    <section class="sheet-section objectives-section">
      <header class="section-head">
        <span class="section-num">01</span>
        <h2>学习目标</h2>
      </header>
      <div class="objective-cards-grid">
        <article v-for="objective in content.learning_objectives" :key="objective.id" class="obj-card">
          <div class="obj-card-head">
            <span class="obj-badge">{{ objective.id }}</span>
            <span class="obj-chip">核心认知</span>
          </div>
          <p class="obj-statement">{{ objective.statement }}</p>
          <div class="criterion-box">
            <span class="criterion-tag">达成标准</span>
            <span class="criterion-text">{{ objective.success_criterion }}</span>
          </div>
        </article>
      </div>
    </section>

    <section v-if="content.preparation && content.preparation.length" class="sheet-section preparation-section">
      <header class="section-head">
        <span class="section-num">02</span>
        <h2>课前准备</h2>
      </header>
      <ul class="prep-list">
        <li v-for="item in content.preparation" :key="item">{{ item }}</li>
      </ul>
    </section>

    <section class="sheet-section tasks-section">
      <header class="section-head">
        <span class="section-num">03</span>
        <h2>探究学习任务</h2>
      </header>
      <template v-for="phase in phases" :key="phase.key">
        <div v-if="content.tasks.some(task => task.phase === phase.key)" class="phase-group">
          <div class="phase-banner">
            <span class="phase-accent"></span>
            <h3>{{ phase.label }}阶段任务</h3>
          </div>
          <article v-for="task in content.tasks.filter(item => item.phase === phase.key)" :key="task.id" class="task-card">
            <div class="task-card-head">
              <div class="task-folio">{{ task.id }}</div>
              <div class="task-title-group">
                <h4>{{ task.title }}</h4>
                <span class="stage-tag">{{ task.stage_id || '未指定环节' }}</span>
              </div>
              <div class="task-facts">
                <span class="fact-pill"><el-icon><Clock /></el-icon>{{ task.estimated_minutes }} 分钟</span>
                <span class="fact-pill"><el-icon><User /></el-icon>{{ collaborationLabels[task.collaboration_mode] }}</span>
              </div>
            </div>
            <div class="mapping-row">
              <div class="obj-tags">
                <span v-for="objectiveId in task.objective_ids" :key="objectiveId" class="obj-mini-tag">{{ objectiveId }}</span>
              </div>
              <small class="action-desc">{{ task.action }} · {{ task.object }}</small>
            </div>
            <ol class="steps-list">
              <li v-for="step in task.steps" :key="step">{{ step }}</li>
            </ol>
            <div class="evidence-grid">
              <div class="evidence-box">
                <b>成果要求</b>
                <p>{{ task.student_output }}</p>
              </div>
              <div class="evidence-box completion">
                <b>完成标准</b>
                <p>{{ task.completion_criterion }}</p>
              </div>
            </div>
            <div v-if="task.scaffolds.length" class="scaffold-box">
              <b>💡 思考支架：</b>
              <span v-for="item in task.scaffolds" :key="item" class="scaffold-item">{{ item }}</span>
            </div>
            <div v-if="task.record_table" class="record-block">
              <h5>{{ task.record_table.title }}</h5>
              <p>{{ task.record_table.instructions }}</p>
              <div class="record-scroll">
                <table>
                  <thead>
                    <tr>
                      <th v-for="column in task.record_table.columns" :key="column">{{ column }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in task.record_table.blank_rows" :key="row">
                      <td v-for="column in task.record_table.columns" :key="column" />
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </article>
        </div>
      </template>
    </section>

    <section v-if="content.record_table" class="sheet-section record-section">
      <header class="section-head">
        <span class="section-num">04</span>
        <h2>{{ content.record_table.title }}</h2>
      </header>
      <p class="record-instruction">{{ content.record_table.instructions }}</p>
      <div class="record-scroll">
        <table>
          <thead>
            <tr>
              <th v-for="column in content.record_table.columns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in content.record_table.blank_rows" :key="row">
              <td v-for="column in content.record_table.columns" :key="column" />
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="content.learning_questions && content.learning_questions.length" class="sheet-section questions-section">
      <header class="section-head">
        <span class="section-num">05</span>
        <h2>思考与反思问题</h2>
      </header>
      <article v-for="question in content.learning_questions" :key="question.id" class="question-card">
        <div class="question-head">
          <span class="q-id-tag">{{ question.id }}</span>
          <span class="q-meta">{{ question.objective_ids.join('、') }} · {{ question.stage_id }}</span>
        </div>
        <p class="q-prompt">{{ question.prompt }}</p>
        <div class="answer-lines">
          <i /><i />
        </div>
      </article>
    </section>

    <section v-if="content.self_assessment && content.self_assessment.length" class="sheet-section assessment-section">
      <header class="section-head">
        <span class="section-num">06</span>
        <h2>自我达成评价</h2>
      </header>
      <div class="assessment-table-wrap">
        <table class="assessment-table">
          <thead>
            <tr>
              <th>自评项目</th>
              <th v-for="scale in content.self_assessment_scale" :key="scale">{{ scale }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in content.self_assessment" :key="item.id">
              <td class="statement-col">{{ item.statement }}</td>
              <td v-for="scale in content.self_assessment_scale" :key="scale" class="check-col"><i /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="content.extension && content.extension.length" class="sheet-section extension-section">
      <header class="section-head">
        <span class="section-num">07</span>
        <h2>课后拓展与延伸</h2>
      </header>
      <ul class="prep-list">
        <li v-for="item in content.extension" :key="item">{{ item }}</li>
      </ul>
      <div class="extension-lines"><i /><i /><i /></div>
    </section>
  </article>
</template>

<style scoped>
.task-sheet-preview {
  width: min(100%, 940px);
  margin: 0 auto;
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  color: #0f172a;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

/* Masthead Header */
.sheet-masthead {
  padding: 32px 36px 26px;
  background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
  border-top: 6px solid #4f46e5;
  border-bottom: 1.5px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  gap: 28px;
  align-items: flex-end;
}

.kicker-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 3px 12px;
  border-radius: 999px;
  letter-spacing: 0.05em;
}

.kicker-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4f46e5;
}

.sheet-masthead h1 {
  margin: 10px 0 0;
  font-size: clamp(22px, 3.5vw, 32px);
  font-weight: 900;
  color: #0f172a;
  line-height: 1.25;
}

.course-meta {
  display: grid;
  grid-template-columns: repeat(4, auto);
  margin: 0;
  background: #f8fafc;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  overflow: hidden;
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
  font-size: 13px;
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
  gap: 8px;
  padding: 10px 36px;
  border-bottom: 1.5px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.knowledge-strip .el-icon {
  color: #4f46e5;
  font-size: 15px;
}

/* Sections */
.sheet-section {
  padding: 30px 36px;
  border-bottom: 1.5px solid #e2e8f0;
}

.sheet-section:last-child {
  border-bottom: 0;
}

.section-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.section-num {
  font-size: 14px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  padding: 3px 10px;
  border-radius: 999px;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.25);
}

.section-head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

/* Objectives Grid */
.objective-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
  gap: 16px;
}

.obj-card {
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.03);
  transition: all 180ms ease;
  display: flex;
  flex-direction: column;
}

.obj-card:hover {
  border-color: #818cf8;
  box-shadow: 0 6px 18px rgba(79, 70, 229, 0.08);
  transform: translateY(-2px);
}

.obj-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.obj-badge {
  font-size: 12px;
  font-weight: 900;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 2px 10px;
  border-radius: 999px;
}

.obj-chip {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}

.obj-statement {
  margin: 0 0 14px;
  font-size: 14.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.6;
  flex-grow: 1;
}

.criterion-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #6366f1;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.5;
}

.criterion-tag {
  display: inline-block;
  font-weight: 800;
  color: #4f46e5;
  margin-right: 6px;
}

.criterion-text {
  color: #475569;
  font-weight: 600;
}

/* Preparation & Extension Lists */
.prep-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.8;
  font-size: 14px;
  color: #334155;
}

.prep-list li {
  margin-bottom: 6px;
  font-weight: 600;
}

/* Task Cards & Phase Banner */
.phase-group + .phase-group {
  margin-top: 28px;
}

.phase-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.phase-accent {
  width: 4px;
  height: 16px;
  background: #4f46e5;
  border-radius: 2px;
}

.phase-banner h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 800;
  color: #334155;
}

.task-card {
  margin-bottom: 18px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
}

.task-card-head {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) auto;
  align-items: center;
  background: #f8fafc;
  border-bottom: 1.5px solid #e2e8f0;
}

.task-folio {
  display: grid;
  place-items: center;
  height: 100%;
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
  color: #ffffff;
  font-size: 13px;
  font-weight: 900;
}

.task-title-group {
  padding: 12px 16px;
}

.task-title-group h4 {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
}

.stage-tag {
  display: inline-block;
  margin-top: 3px;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

.task-facts {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
}

.fact-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  color: #475569;
  font-size: 11.5px;
  font-weight: 700;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  padding: 3px 9px;
  border-radius: 999px;
}

.mapping-row {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 10px 16px;
  background: #f1f5f9;
  border-bottom: 1px solid #e2e8f0;
}

.obj-tags {
  display: flex;
  gap: 6px;
}

.obj-mini-tag {
  padding: 2px 8px;
  border-radius: 6px;
  background: #4f46e5;
  color: #ffffff;
  font-size: 10.5px;
  font-weight: 800;
}

.action-desc {
  margin-left: auto;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 700;
}

.steps-list {
  margin: 0;
  padding: 16px 36px;
  line-height: 1.75;
  font-size: 13.5px;
  color: #1e293b;
}

.steps-list li {
  margin-bottom: 4px;
  font-weight: 600;
}

.evidence-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 1.5px solid #e2e8f0;
  background: #fafafa;
}

.evidence-box {
  padding: 12px 16px;
}

.evidence-box + .evidence-box {
  border-left: 1.5px solid #e2e8f0;
}

.evidence-box b {
  color: #4f46e5;
  font-size: 11.5px;
  font-weight: 800;
}

.evidence-box p {
  margin: 4px 0 0;
  line-height: 1.55;
  font-size: 12.5px;
  color: #334155;
  font-weight: 600;
}

.scaffold-box {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 16px;
  border-top: 1px solid #e2e8f0;
  background: #f5f3ff;
}

.scaffold-box b {
  color: #6d28d9;
  font-size: 11.5px;
  font-weight: 800;
}

.scaffold-item {
  color: #5b21b6;
  font-size: 11.5px;
  font-weight: 600;
  background: #ede9fe;
  padding: 2px 8px;
  border-radius: 6px;
}

/* Record Block & Table */
.record-block {
  padding: 16px;
  border-top: 1.5px solid #e2e8f0;
}

.record-block h5 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 800;
  color: #0f172a;
}

.record-block > p,
.record-instruction {
  margin: 4px 0 12px;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.record-scroll {
  overflow-x: auto;
}

.record-block table,
.record-section table {
  width: 100%;
  min-width: 480px;
  border-collapse: collapse;
  table-layout: fixed;
  border-radius: 8px;
  overflow: hidden;
  border: 1.5px solid #cbd5e1;
}

.record-block th,
.record-block td,
.record-section th,
.record-section td {
  height: 36px;
  border: 1px solid #cbd5e1;
  padding: 8px 10px;
}

.record-block th,
.record-section th {
  background: #f1f5f9;
  color: #1e293b;
  font-size: 12px;
  font-weight: 800;
}

/* Questions Section */
.question-card {
  padding: 16px;
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  margin-bottom: 14px;
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
  font-size: 11px;
  font-weight: 600;
}

.q-prompt {
  margin: 0 0 14px;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.6;
}

.answer-lines {
  display: grid;
  gap: 12px;
}

.answer-lines i,
.extension-lines i {
  display: block;
  height: 18px;
  border-bottom: 1.5px dashed #cbd5e1;
}

/* Assessment Table */
.assessment-table-wrap {
  overflow-x: auto;
}

.assessment-table {
  width: 100%;
  min-width: 620px;
  border: 1.5px solid #cbd5e1;
  border-collapse: collapse;
  table-layout: fixed;
  border-radius: 10px;
  overflow: hidden;
}

.assessment-table th,
.assessment-table td {
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  text-align: center;
  font-size: 12px;
}

.assessment-table th:first-child,
.assessment-table td:first-child {
  width: 50%;
  text-align: left;
}

.assessment-table th {
  background: #f1f5f9;
  color: #1e293b;
  font-weight: 800;
}

.assessment-table .statement-col {
  font-weight: 700;
  color: #0f172a;
}

.assessment-table i {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 1.5px solid #94a3b8;
  border-radius: 3px;
}

.extension-lines {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

@media (max-width: 700px) {
  .sheet-masthead {
    padding: 24px 18px;
    align-items: start;
    flex-direction: column;
  }
  .course-meta {
    width: 100%;
    grid-template-columns: repeat(2, 1fr);
  }
  .course-meta .meta-item {
    min-width: 0;
    border-bottom: 1px solid #e2e8f0;
  }
  .course-meta .meta-item:nth-last-child(-n + 2) {
    border-bottom: 0;
  }
  .knowledge-strip,
  .sheet-section {
    padding-left: 18px;
    padding-right: 18px;
  }
  .objective-cards-grid {
    grid-template-columns: 1fr;
  }
  .task-card-head {
    grid-template-columns: 48px minmax(0, 1fr);
  }
  .task-facts {
    grid-column: 1 / -1;
    justify-content: flex-end;
    min-height: 34px;
    border-top: 1px solid #e2e8f0;
  }
  .evidence-grid {
    grid-template-columns: 1fr;
  }
  .evidence-box + .evidence-box {
    border-left: 0;
    border-top: 1px solid #e2e8f0;
  }
}
</style>

