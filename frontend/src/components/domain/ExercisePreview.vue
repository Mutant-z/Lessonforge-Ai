<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, ref, watchEffect, type PropType } from 'vue';
import { api } from '../../api/client';
import type { ExerciseContent, ExerciseQuestion, ExerciseQuestionGroup, ExerciseStimulus } from '../../types';
import { Check, Clock, Document, Reading, Star, Warning } from '@element-plus/icons-vue';

const props = defineProps<{
  content: ExerciseContent;
  sourceVersions?: Record<string, number>;
}>();

const mode = ref<'student' | 'teacher'>('teacher');
const assetUrls = ref<Record<string, string>>({});

const questionTypeLabels: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  calculation: '计算题',
  case_analysis: '案例分析',
  practical_task: '实践任务',
};

const ExerciseQuestionView = defineComponent({
  name: 'ExerciseQuestionView',
  props: {
    item: { type: Object as PropType<ExerciseQuestion>, required: true },
    number: { type: Number, required: true },
    teacher: { type: Boolean, required: true },
  },
  setup(componentProps) {
    const answer = () => componentProps.item.answer_key.correct_option_ids.join('、')
      || componentProps.item.answer_key.accepted_answers.join('、')
      || componentProps.item.answer_key.reference_answer;

    return () => h('article', { class: 'fancy-question-card' }, [
      // Card Header
      h('header', { class: 'fancy-q-header' }, [
        h('div', { class: 'q-header-left' }, [
          h('span', { class: 'q-number-badge' }, String(componentProps.number).padStart(2, '0')),
          h('span', { class: 'q-type-chip' }, questionTypeLabels[componentProps.item.question_type] || '练习题'),
          h('span', { class: 'q-score-chip' }, `${componentProps.item.score} 分`),
          h('span', { class: 'q-time-chip' }, `⏱ ${componentProps.item.estimated_minutes} 分钟`),
        ]),
        componentProps.item.objective_ids.length
          ? h('div', { class: 'q-target-tags' }, componentProps.item.objective_ids.map(id => h('span', { key: id, class: 'target-chip' }, `🎯 ${id}`)))
          : null,
      ]),

      // Stem / Question Text
      h('div', { class: 'fancy-q-stem' }, [
        h('h3', componentProps.item.stem),
      ]),

      // Options (if choice question)
      componentProps.item.options.length
        ? h('div', { class: 'fancy-options-grid' }, componentProps.item.options.map(option => h('div', { key: option.id, class: 'fancy-option-item' }, [
            h('span', { class: 'opt-letter' }, option.id),
            h('span', { class: 'opt-text' }, option.text),
          ])))
        : null,

      // Student Answer Space
      !componentProps.teacher && componentProps.item.answer_space.mode !== 'none'
        ? h('div', { class: 'fancy-answer-space' }, [
            h('span', { class: 'space-label' }, '【请在此处书写解答】'),
            ...Array.from({ length: Math.max(1, componentProps.item.answer_space.lines || componentProps.item.answer_space.blank_rows) }, (_, index) => h('i', { key: index, class: 'space-line' })),
          ])
        : null,

      // Teacher Answer & Analysis Callouts
      componentProps.teacher ? h('div', { class: 'fancy-teacher-panel' }, [
        // Answer Callout Box
        h('div', { class: 'teacher-callout answer-callout' }, [
          h('div', { class: 'callout-title' }, [
            h('span', { class: 'callout-badge green' }, '✓ 参考答案'),
          ]),
          h('div', { class: 'callout-body answer-body' }, answer()),
        ]),

        // Analysis Callout Box
        componentProps.item.analysis
          ? h('div', { class: 'teacher-callout analysis-callout' }, [
              h('div', { class: 'callout-title' }, [
                h('span', { class: 'callout-badge violet' }, '💡 详细解析'),
              ]),
              h('p', { class: 'callout-body' }, componentProps.item.analysis),
            ])
          : null,

        // Scoring Rubric
        componentProps.item.scoring_points.length
          ? h('div', { class: 'teacher-callout rubric-callout' }, [
              h('div', { class: 'callout-title' }, [
                h('span', { class: 'callout-badge blue' }, '📝 评分得分点'),
              ]),
              h('ul', { class: 'rubric-list' }, componentProps.item.scoring_points.map(point => h('li', { key: point.id }, [
                h('span', { class: 'rubric-pts' }, `+${point.points}分`),
                h('strong', `${point.criterion}：`),
                h('span', point.acceptable_evidence),
              ]))),
            ])
          : null,

        // Common Error Analysis
        componentProps.item.common_errors.length
          ? h('div', { class: 'teacher-callout warning-callout' }, [
              h('div', { class: 'callout-title' }, [
                h('span', { class: 'callout-badge amber' }, '⚠️ 常见易错点与防坑提示'),
              ]),
              h('p', { class: 'callout-body' }, componentProps.item.common_errors.join('；')),
            ])
          : null,
      ]) : null,
    ]);
  },
});

const questions = computed(() => props.content.sections.flatMap(section => section.blocks.flatMap(
  block => block.kind === 'question_group' ? block.sub_questions : [block],
)));

const coveredObjectives = computed(() => new Set(questions.value.flatMap(item => item.objective_ids)).size);

watchEffect(async () => {
  const ids = props.content.sections.flatMap(section => section.blocks.flatMap(block => {
    if (block.kind !== 'question_group') return [];
    return block.stimuli.map(stimulus => stimulus.visual?.asset_id).filter(Boolean) as string[];
  }));
  for (const id of ids) {
    if (assetUrls.value[id]) continue;
    try {
      const response = await api.get(`/artifact-assets/${id}`, { responseType: 'blob' });
      assetUrls.value[id] = URL.createObjectURL(response.data);
    } catch {
      assetUrls.value[id] = '';
    }
  }
});

onBeforeUnmount(() => Object.values(assetUrls.value).forEach(url => url && URL.revokeObjectURL(url)));

function numberFor(item: ExerciseQuestion) {
  return questions.value.findIndex(question => question.id === item.id) + 1;
}

function group(block: ExerciseQuestion | ExerciseQuestionGroup): block is ExerciseQuestionGroup {
  return block.kind === 'question_group';
}

function visualStatus(stimulus: ExerciseStimulus) {
  const status = stimulus.visual?.status;
  if (status === 'approved') return '配图已复核';
  if (status === 'degraded') return '已使用替代材料';
  if (status === 'reviewing') return '配图复核中';
  return '配图准备中';
}
</script>

<template>
  <article class="fancy-exercise-paper">
    <!-- Header Banner -->
    <header class="fancy-paper-header">
      <div class="header-main-info">
        <span class="paper-kicker">
          <el-icon><Document /></el-icon> 课后巩固与达标测试
        </span>
        <h1 class="paper-title">{{ content.paper_settings.title }}</h1>
        <div class="paper-meta-row">
          <span class="meta-tag">{{ content.course_info.subject }}</span>
          <span class="meta-tag">{{ content.course_info.grade_level || content.course_info.audience }}</span>
        </div>
      </div>

      <!-- Mode Switcher Pill -->
      <div class="mode-switch-wrapper">
        <div class="mode-switch-pill" role="tablist">
          <button
            type="button"
            :class="{ active: mode === 'student' }"
            @click="mode = 'student'"
          >
            学生答题模式
          </button>
          <button
            type="button"
            :class="{ active: mode === 'teacher' }"
            @click="mode = 'teacher'"
          >
            教师解析模式
          </button>
        </div>
      </div>
    </header>

    <!-- Metrics Cards Banner -->
    <section class="fancy-paper-metrics">
      <div class="metric-card">
        <span class="metric-value">{{ content.paper_settings.total_score }}</span>
        <span class="metric-label">试卷总分</span>
      </div>
      <div class="metric-card">
        <span class="metric-value">{{ content.paper_settings.estimated_minutes }}</span>
        <span class="metric-label">建议用时(分钟)</span>
      </div>
      <div class="metric-card">
        <span class="metric-value">{{ questions.length }}</span>
        <span class="metric-label">计分题目数</span>
      </div>
      <div class="metric-card">
        <span class="metric-value">{{ coveredObjectives }}</span>
        <span class="metric-label">覆盖目标数</span>
      </div>
    </section>

    <!-- Source Versions Strip -->
    <section v-if="sourceVersions && Object.keys(sourceVersions).length" class="fancy-source-strip">
      <span class="source-icon">🔗 依赖版本关联:</span>
      <span v-for="(version, type) in sourceVersions" :key="type" class="source-badge">
        {{ type }} V{{ version }}
      </span>
    </section>

    <!-- Teacher Attention Alert -->
    <section v-if="content.review_summary.needs_teacher_attention" class="fancy-review-alert">
      <el-icon class="alert-icon"><Warning /></el-icon>
      <div>
        <strong>教师关注提示：</strong>
        <span>{{ content.review_summary.notes.join('；') }}</span>
      </div>
    </section>

    <!-- Student Instructions -->
    <section class="fancy-instructions-card">
      <div class="instructions-head">
        <el-icon><Reading /></el-icon>
        <span>作答说明与答题要求</span>
      </div>
      <ul class="instructions-list">
        <li v-for="item in content.paper_settings.student_instructions" :key="item">{{ item }}</li>
      </ul>
      <p v-if="content.paper_settings.answer_requirements" class="req-text">
        {{ content.paper_settings.answer_requirements }}
      </p>
    </section>

    <!-- Sections & Questions List -->
    <section v-for="(section, sectionIndex) in content.sections" :key="section.id" class="fancy-paper-section">
      <header class="section-banner">
        <span class="section-idx">{{ String(sectionIndex + 1).padStart(2, '0') }}</span>
        <div class="section-heading">
          <h2>{{ section.title }}</h2>
          <span class="section-score-tag">本大题共 {{ section.score }} 分</span>
        </div>
      </header>

      <template v-for="block in section.blocks" :key="block.id">
        <!-- Question Group (Stimulus + Sub questions) -->
        <div v-if="group(block)" class="fancy-question-group">
          <header class="group-header">
            <span class="group-badge">材料阅读题组</span>
            <h3>{{ block.title }}</h3>
            <p v-if="block.instructions" class="group-inst">{{ block.instructions }}</p>
          </header>

          <div v-for="stimulus in block.stimuli" :key="stimulus.id" class="fancy-stimulus-card">
            <strong class="stimulus-title">{{ stimulus.title || '材料背景' }}</strong>
            <p v-if="stimulus.kind === 'text'" class="stimulus-text">{{ stimulus.text }}</p>
            <div v-else-if="stimulus.kind === 'table'" class="stimulus-table-wrapper">
              <table>
                <thead><tr><th v-for="column in stimulus.columns" :key="column">{{ column }}</th></tr></thead>
                <tbody>
                  <tr v-for="(row, rowIndex) in stimulus.rows" :key="rowIndex">
                    <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else-if="stimulus.visual" class="fancy-visual-stimulus">
              <img v-if="stimulus.visual.asset_id && assetUrls[stimulus.visual.asset_id]" :src="assetUrls[stimulus.visual.asset_id]" :alt="stimulus.visual.alt_text" />
              <div v-else class="visual-fallback">{{ stimulus.visual.fallback_stimulus }}</div>
              <small>{{ visualStatus(stimulus) }}<template v-if="stimulus.visual.caption"> · {{ stimulus.visual.caption }}</template></small>
            </div>
          </div>

          <ExerciseQuestionView
            v-for="item in block.sub_questions"
            :key="item.id"
            :item="item"
            :number="numberFor(item)"
            :teacher="mode === 'teacher'"
          />
        </div>

        <!-- Standalone Question -->
        <ExerciseQuestionView
          v-else
          :item="block"
          :number="numberFor(block)"
          :teacher="mode === 'teacher'"
        />
      </template>
    </section>
  </article>
</template>

<style scoped>
.fancy-exercise-paper {
  max-width: 920px;
  margin: 0 auto;
  padding: 32px 36px;
  color: var(--text-primary, #0f172a);
  background: #ffffff;
  font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "PingFang SC", sans-serif;
  box-sizing: border-box;
}

.fancy-paper-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  padding-bottom: 20px;
  border-bottom: 2px solid #e2e8f0;
}

.paper-kicker {
  color: #4f46e5;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.05em;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.paper-title {
  margin: 0 0 10px 0;
  font-size: 26px;
  font-weight: 900;
  color: #0f172a;
  line-height: 1.25;
}

.paper-meta-row {
  display: flex;
  gap: 8px;
}

.meta-tag {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 10px;
  border-radius: 999px;
}

.mode-switch-wrapper {
  flex-shrink: 0;
}

.mode-switch-pill {
  display: flex;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
}

.mode-switch-pill button {
  border: 0;
  padding: 6px 14px;
  border-radius: 999px;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 180ms ease;
}

.mode-switch-pill button.active {
  background: #ffffff;
  color: #4f46e5;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.fancy-paper-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 20px;
}

.metric-card {
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  transition: transform 150ms ease;
}

.metric-card:hover {
  transform: translateY(-1px);
  border-color: #cbd5e1;
}

.metric-value {
  font-size: 24px;
  font-weight: 900;
  color: #4f46e5;
}

.metric-label {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.fancy-source-strip {
  margin-top: 14px;
  padding: 8px 14px;
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  border-radius: 10px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.source-icon {
  color: #6d28d9;
  font-weight: 700;
}

.source-badge {
  font-weight: 700;
  color: #4f46e5;
  background: #ffffff;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid #c7d2fe;
}

.fancy-review-alert {
  margin-top: 16px;
  padding: 12px 16px;
  background: #fffbeb;
  border: 1.5px solid #fcd34d;
  border-radius: 12px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  color: #92400e;
  font-size: 13px;
}

.alert-icon {
  color: #d97706;
  font-size: 18px;
  margin-top: 1px;
}

.fancy-instructions-card {
  margin-top: 20px;
  background: #fafafa;
  border: 1px solid #e5e5e5;
  border-radius: 12px;
  padding: 16px 20px;
}

.instructions-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 800;
  color: #334155;
  margin-bottom: 8px;
}

.instructions-list {
  margin: 0 0 8px 0;
  padding-left: 20px;
  font-size: 13px;
  color: #475569;
  line-height: 1.6;
}

.req-text {
  margin: 0;
  font-size: 12px;
  color: #64748b;
  font-style: italic;
}

.fancy-paper-section {
  margin-top: 28px;
}

.section-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 10px;
  border-bottom: 2px solid #0f172a;
}

.section-idx {
  font-size: 28px;
  font-weight: 900;
  color: #4f46e5;
  line-height: 1;
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex: 1;
}

.section-heading h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.section-score-tag {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}

.fancy-question-group {
  margin-top: 20px;
  background: #f8fafc;
  border: 1.5px solid #cbd5e1;
  border-radius: 14px;
  padding: 20px;
}

.group-header {
  margin-bottom: 14px;
}

.group-badge {
  font-size: 11px;
  font-weight: 800;
  color: #4f46e5;
  background: #e0e7ff;
  padding: 2px 8px;
  border-radius: 999px;
}

.group-header h3 {
  margin: 6px 0 4px 0;
  font-size: 16px;
  color: #0f172a;
}

.group-inst {
  margin: 0;
  font-size: 13px;
  color: #64748b;
}

.fancy-stimulus-card {
  background: #ffffff;
  border-left: 4px solid #4f46e5;
  border-radius: 0 10px 10px 0;
  padding: 14px 18px;
  margin-bottom: 16px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.stimulus-title {
  display: block;
  font-size: 13px;
  color: #334155;
  margin-bottom: 6px;
}

.stimulus-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.65;
  color: #1e293b;
}

.stimulus-table-wrapper table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 8px;
}

.stimulus-table-wrapper th, .stimulus-table-wrapper td {
  border: 1px solid #cbd5e1;
  padding: 8px 12px;
  font-size: 13px;
}

.stimulus-table-wrapper th {
  background: #f1f5f9;
  font-weight: 700;
}

.fancy-visual-stimulus {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.fancy-visual-stimulus img {
  max-width: 100%;
  max-height: 380px;
  object-fit: contain;
  border-radius: 8px;
}

.visual-fallback {
  padding: 20px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  text-align: center;
}

/* Question Card Styles */
:deep(.fancy-question-card) {
  margin-top: 20px;
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
  transition: all 180ms ease;
}

:deep(.fancy-question-card:hover) {
  border-color: #cbd5e1;
  box-shadow: 0 6px 24px rgba(15, 23, 42, 0.07);
}

:deep(.fancy-q-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

:deep(.q-header-left) {
  display: flex;
  align-items: center;
  gap: 8px;
}

:deep(.q-number-badge) {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  font-size: 12px;
  font-weight: 900;
  display: grid;
  place-items: center;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.25);
}

:deep(.q-type-chip) {
  font-size: 11px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 999px;
}

:deep(.q-score-chip), :deep(.q-time-chip) {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 999px;
}

:deep(.q-target-tags) {
  display: flex;
  gap: 6px;
}

:deep(.target-chip) {
  font-size: 10px;
  font-weight: 700;
  color: #6d28d9;
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  padding: 2px 8px;
  border-radius: 999px;
}

:deep(.fancy-q-stem h3) {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
  line-height: 1.65;
}

:deep(.fancy-options-grid) {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
  margin-top: 16px;
}

:deep(.fancy-option-item) {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  transition: all 150ms ease;
}

:deep(.fancy-option-item:hover) {
  background: #ffffff;
  border-color: #a5b4fc;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.08);
}

:deep(.opt-letter) {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e0e7ff;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 900;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

:deep(.opt-text) {
  font-size: 13.5px;
  color: #1e293b;
  line-height: 1.5;
}

:deep(.fancy-answer-space) {
  margin-top: 18px;
  padding: 14px;
  background: #fafafa;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
}

:deep(.space-label) {
  font-size: 11px;
  font-weight: 700;
  color: #94a3b8;
  display: block;
  margin-bottom: 8px;
}

:deep(.space-line) {
  display: block;
  height: 28px;
  border-bottom: 1px dashed #cbd5e1;
}

:deep(.fancy-teacher-panel) {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

:deep(.teacher-callout) {
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.6;
}

:deep(.answer-callout) {
  background: #ecfdf5;
  border-left: 4px solid #10b981;
}

:deep(.analysis-callout) {
  background: #f5f3ff;
  border-left: 4px solid #8b5cf6;
}

:deep(.rubric-callout) {
  background: #eff6ff;
  border-left: 4px solid #3b82f6;
}

:deep(.warning-callout) {
  background: #fffbeb;
  border-left: 4px solid #f59e0b;
}

:deep(.callout-title) {
  margin-bottom: 4px;
}

:deep(.callout-badge) {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 999px;
}

:deep(.callout-badge.green) { color: #047857; background: #d1fae5; }
:deep(.callout-badge.violet) { color: #6d28d9; background: #ede9fe; }
:deep(.callout-badge.blue) { color: #1d4ed8; background: #dbeafe; }
:deep(.callout-badge.amber) { color: #b45309; background: #fef3c7; }

:deep(.answer-body) {
  font-weight: 800;
  font-size: 14px;
  color: #047857;
}

:deep(.callout-body) {
  margin: 4px 0 0 0;
  color: #334155;
}

:deep(.rubric-list) {
  margin: 6px 0 0 0;
  padding-left: 18px;
}

:deep(.rubric-list li) {
  margin-bottom: 4px;
}

:deep(.rubric-pts) {
  font-size: 11px;
  font-weight: 800;
  color: #2563eb;
  background: #ffffff;
  padding: 1px 6px;
  border-radius: 4px;
  margin-right: 6px;
}

@media (max-width: 700px) {
  .fancy-exercise-paper { padding: 18px; }
  .fancy-paper-header { flex-direction: column; }
  .fancy-paper-metrics { grid-template-columns: 1fr 1fr; }
  :deep(.fancy-options-grid) { grid-template-columns: 1fr; }
}
</style>
