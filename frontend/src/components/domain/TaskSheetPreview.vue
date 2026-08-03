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
      <div>
        <span class="sheet-kicker">学习任务单 · 学生版</span>
        <h1>{{ content.course_info.course_title }}</h1>
      </div>
      <dl class="course-meta">
        <div><dt>学科</dt><dd>{{ content.course_info.subject || '—' }}</dd></div>
        <div><dt>年级</dt><dd>{{ content.course_info.grade_level || content.course_info.audience || '—' }}</dd></div>
        <div><dt>时长</dt><dd>{{ content.course_info.duration_minutes }} 分钟</dd></div>
        <div><dt>目标覆盖</dt><dd>{{ coveredObjectiveCount }} / {{ content.learning_objectives.length }}</dd></div>
      </dl>
    </header>

    <div v-if="referencedSources.length" class="knowledge-strip">
      <el-icon><Collection /></el-icon>
      <span>本版本参考了：{{ referencedSources.join('、') }}</span>
    </div>

    <section class="sheet-section objectives-section">
      <header><span>01</span><h2>学习目标</h2></header>
      <div class="objective-grid">
        <article v-for="objective in content.learning_objectives" :key="objective.id">
          <b>{{ objective.id }}</b>
          <p>{{ objective.statement }}</p>
          <small>达成标准 · {{ objective.success_criterion }}</small>
        </article>
      </div>
    </section>

    <section class="sheet-section preparation-section">
      <header><span>02</span><h2>课前准备</h2></header>
      <ul><li v-for="item in content.preparation" :key="item">{{ item }}</li></ul>
    </section>

    <section class="sheet-section tasks-section">
      <header><span>03</span><h2>学习任务</h2></header>
      <template v-for="phase in phases" :key="phase.key">
        <div v-if="content.tasks.some(task => task.phase === phase.key)" class="phase-group">
          <h3>{{ phase.label }}</h3>
          <article v-for="task in content.tasks.filter(item => item.phase === phase.key)" :key="task.id" class="task-card">
            <div class="task-card-head">
              <div class="task-folio">{{ task.id }}</div>
              <div class="task-title"><h4>{{ task.title }}</h4><span>{{ task.stage_id || '未指定环节' }}</span></div>
              <div class="task-facts">
                <span><el-icon><Clock /></el-icon>{{ task.estimated_minutes }} 分钟</span>
                <span><el-icon><User /></el-icon>{{ collaborationLabels[task.collaboration_mode] }}</span>
              </div>
            </div>
            <div class="mapping-row">
              <span v-for="objectiveId in task.objective_ids" :key="objectiveId">{{ objectiveId }}</span>
              <small>{{ task.action }} · {{ task.object }}</small>
            </div>
            <ol class="steps-list"><li v-for="step in task.steps" :key="step">{{ step }}</li></ol>
            <div class="evidence-grid">
              <div><b>成果要求</b><p>{{ task.student_output }}</p></div>
              <div><b>完成标准</b><p>{{ task.completion_criterion }}</p></div>
            </div>
            <div v-if="task.scaffolds.length" class="scaffold-box">
              <b>思考支架</b><span v-for="item in task.scaffolds" :key="item">{{ item }}</span>
            </div>
            <div v-if="task.record_table" class="record-block">
              <h5>{{ task.record_table.title }}</h5>
              <p>{{ task.record_table.instructions }}</p>
              <div class="record-scroll">
                <table>
                  <thead><tr><th v-for="column in task.record_table.columns" :key="column">{{ column }}</th></tr></thead>
                  <tbody><tr v-for="row in task.record_table.blank_rows" :key="row"><td v-for="column in task.record_table.columns" :key="column" /></tr></tbody>
                </table>
              </div>
            </div>
          </article>
        </div>
      </template>
    </section>

    <section v-if="content.record_table" class="sheet-section record-section">
      <header><span>04</span><h2>{{ content.record_table.title }}</h2></header>
      <p>{{ content.record_table.instructions }}</p>
      <div class="record-scroll">
        <table>
          <thead><tr><th v-for="column in content.record_table.columns" :key="column">{{ column }}</th></tr></thead>
          <tbody><tr v-for="row in content.record_table.blank_rows" :key="row"><td v-for="column in content.record_table.columns" :key="column" /></tr></tbody>
        </table>
      </div>
    </section>

    <section class="sheet-section questions-section">
      <header><span>05</span><h2>课堂问题</h2></header>
      <article v-for="question in content.learning_questions" :key="question.id" class="question-row">
        <b>{{ question.id }}</b><small>{{ question.objective_ids.join('、') }} · {{ question.stage_id }}</small><p>{{ question.prompt }}</p><div class="answer-lines"><i /><i /></div>
      </article>
    </section>

    <section class="sheet-section assessment-section">
      <header><span>06</span><h2>自我评价</h2></header>
      <div class="assessment-table-wrap">
        <table class="assessment-table">
          <thead><tr><th>自评项目</th><th v-for="scale in content.self_assessment_scale" :key="scale">{{ scale }}</th></tr></thead>
          <tbody><tr v-for="item in content.self_assessment" :key="item.id"><td>{{ item.statement }}</td><td v-for="scale in content.self_assessment_scale" :key="scale"><i /></td></tr></tbody>
        </table>
      </div>
    </section>

    <section class="sheet-section extension-section">
      <header><span>07</span><h2>课后拓展</h2></header>
      <ul><li v-for="item in content.extension" :key="item">{{ item }}</li></ul>
      <div class="extension-lines"><i /><i /><i /></div>
    </section>
  </article>
</template>

<style scoped>
.task-sheet-preview { width: min(100%, 940px); margin: 0 auto; background: #fff; border: 1px solid #cfd2d9; color: #18191d; font-family: "Helvetica Neue", Arial, sans-serif; }
.sheet-masthead { padding: 32px 36px 26px; border-top: 8px solid #002fa7; border-bottom: 1px solid #cfd2d9; display: flex; justify-content: space-between; gap: 28px; align-items: end; }
.sheet-kicker { color: #002fa7; font-size: 11px; font-weight: 800; letter-spacing: .1em; }
.sheet-masthead h1 { margin: 8px 0 0; font-size: clamp(24px, 4vw, 38px); line-height: 1.12; }
.course-meta { display: grid; grid-template-columns: repeat(4, auto); margin: 0; border: 1px solid #cfd2d9; }
.course-meta div { min-width: 86px; padding: 8px 12px; border-right: 1px solid #cfd2d9; }.course-meta div:last-child { border-right: 0; }
.course-meta dt { font-size: 10px; color: #656a73; }.course-meta dd { margin: 3px 0 0; font-size: 12px; font-weight: 700; }
.knowledge-strip { display: flex; align-items: center; gap: 8px; padding: 10px 36px; border-bottom: 1px solid #cfd2d9; background: #f7f7f8; color: #51545b; font-size: 12px; }
.knowledge-strip .el-icon { color: #002fa7; }
.sheet-section { padding: 28px 36px; border-bottom: 1px solid #cfd2d9; }.sheet-section:last-child { border-bottom: 0; }
.sheet-section > header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 18px; }.sheet-section > header span { color: #002fa7; font-size: 24px; font-weight: 800; font-variant-numeric: tabular-nums; }.sheet-section h2 { margin: 0; font-size: 18px; }
.objective-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border: 1px solid #cfd2d9; }
.objective-grid article { padding: 16px; border-right: 1px solid #cfd2d9; }.objective-grid article:last-child { border-right: 0; }.objective-grid b { color: #002fa7; font-size: 12px; }.objective-grid p { margin: 8px 0; font-weight: 700; line-height: 1.5; }.objective-grid small { color: #656a73; line-height: 1.5; }
.preparation-section ul, .extension-section ul { margin: 0; padding-left: 22px; line-height: 1.8; }
.phase-group + .phase-group { margin-top: 24px; }.phase-group > h3 { margin: 0 0 10px; padding: 6px 10px; border-left: 3px solid #002fa7; background: #f7f7f8; font-size: 13px; }
.task-card { margin-bottom: 14px; border: 1px solid #cfd2d9; }.task-card-head { display: grid; grid-template-columns: 58px minmax(0, 1fr) auto; border-bottom: 1px solid #cfd2d9; }
.task-folio { display: grid; place-items: center; background: #002fa7; color: #fff; font-size: 12px; font-weight: 800; }.task-title { padding: 12px 14px; }.task-title h4 { margin: 0; font-size: 15px; }.task-title span { display: block; margin-top: 4px; color: #656a73; font-size: 11px; }
.task-facts { display: flex; align-items: center; gap: 12px; padding: 0 14px; border-left: 1px solid #cfd2d9; }.task-facts span { display: flex; align-items: center; gap: 4px; white-space: nowrap; color: #51545b; font-size: 11px; }
.mapping-row { display: flex; gap: 6px; align-items: center; padding: 10px 14px; background: #f7f7f8; }.mapping-row span { padding: 2px 7px; border: 1px solid #002fa7; color: #002fa7; font-size: 10px; font-weight: 800; }.mapping-row small { margin-left: auto; color: #656a73; }
.steps-list { margin: 0; padding: 16px 34px; line-height: 1.75; font-size: 13px; }.evidence-grid { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid #cfd2d9; }.evidence-grid > div { padding: 12px 14px; }.evidence-grid > div + div { border-left: 1px solid #cfd2d9; }.evidence-grid b { color: #002fa7; font-size: 11px; }.evidence-grid p { margin: 5px 0 0; line-height: 1.55; font-size: 12px; }
.scaffold-box { display: flex; gap: 8px; flex-wrap: wrap; padding: 10px 14px; border-top: 1px solid #cfd2d9; }.scaffold-box b { color: #002fa7; font-size: 11px; }.scaffold-box span { color: #51545b; font-size: 11px; }
.record-block { padding: 14px; border-top: 1px solid #cfd2d9; }.record-block h5 { margin: 0; font-size: 13px; }.record-block > p, .record-section > p { margin: 4px 0 10px; color: #656a73; font-size: 11px; }.record-scroll { overflow-x: auto; }.record-block table, .record-section table { width: 100%; min-width: 480px; border-collapse: collapse; table-layout: fixed; }.record-block th, .record-block td, .record-section th, .record-section td { height: 34px; border: 1px solid #cfd2d9; padding: 6px; }.record-block th, .record-section th { background: #f7f7f8; color: #34373d; font-size: 11px; }
.question-row { padding: 14px 0; border-top: 1px solid #cfd2d9; }.question-row b { color: #002fa7; font-size: 11px; }.question-row small { margin-left: 8px; color: #656a73; font-size: 10px; }.question-row p { margin: 6px 0 12px; }.answer-lines { display: grid; gap: 12px; }.answer-lines i, .extension-lines i { display: block; height: 18px; border-bottom: 1px solid #cfd2d9; }
.assessment-table-wrap { overflow-x: auto; }.assessment-table { width: 100%; min-width: 620px; border: 1px solid #cfd2d9; border-collapse: collapse; table-layout: fixed; }.assessment-table th, .assessment-table td { padding: 10px; border: 1px solid #cfd2d9; text-align: center; font-size: 11px; }.assessment-table th:first-child, .assessment-table td:first-child { width: 52%; text-align: left; }.assessment-table th { background: #f7f7f8; }.assessment-table i { display: inline-block; width: 13px; height: 13px; border: 1px solid #9da1aa; }
.extension-lines { display: grid; gap: 10px; margin-top: 12px; }
@media (max-width: 700px) { .sheet-masthead { padding: 24px 18px; align-items: start; flex-direction: column; }.course-meta { width: 100%; grid-template-columns: repeat(2, 1fr); }.course-meta div { min-width: 0; border-bottom: 1px solid #cfd2d9; }.course-meta div:nth-last-child(-n + 2) { border-bottom: 0; }.knowledge-strip, .sheet-section { padding-left: 18px; padding-right: 18px; }.objective-grid { grid-template-columns: 1fr; }.objective-grid article { border-right: 0; border-bottom: 1px solid #cfd2d9; }.objective-grid article:last-child { border-bottom: 0; }.task-card-head { grid-template-columns: 48px minmax(0, 1fr); }.task-facts { grid-column: 1 / -1; justify-content: flex-end; min-height: 34px; border-top: 1px solid #cfd2d9; border-left: 0; }.evidence-grid { grid-template-columns: 1fr; }.evidence-grid > div + div { border-left: 0; border-top: 1px solid #cfd2d9; } }
</style>
