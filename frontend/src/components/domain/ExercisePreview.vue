<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, ref, watchEffect, type PropType } from 'vue';
import { api } from '../../api/client';
import type { ExerciseContent, ExerciseQuestion, ExerciseQuestionGroup, ExerciseStimulus } from '../../types';

const props = defineProps<{
  content: ExerciseContent;
  sourceVersions?: Record<string, number>;
}>();

const mode = ref<'student' | 'teacher'>('student');
const assetUrls = ref<Record<string, string>>({});
const questionTypeLabels: Record<string, string> = {
  single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题',
  short_answer: '简答题', calculation: '计算题', case_analysis: '案例分析', practical_task: '实践任务',
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
    return () => h('article', { class: 'question-card' }, [
      h('header', [
        h('span', { class: 'question-number' }, String(componentProps.number).padStart(2, '0')),
        h('div', [
          h('p', { class: 'question-meta' }, `${questionTypeLabels[componentProps.item.question_type]} · ${componentProps.item.score} 分 · ${componentProps.item.estimated_minutes} 分钟`),
          h('h3', componentProps.item.stem),
          h('div', { class: 'mapping-tags' }, componentProps.item.objective_ids.map(id => h('span', { key: id }, id))),
        ]),
      ]),
      componentProps.item.options.length ? h('div', { class: 'option-grid' }, componentProps.item.options.map(option => h('div', { key: option.id }, [h('b', option.id), h('span', option.text)]))) : null,
      !componentProps.teacher && componentProps.item.answer_space.mode !== 'none'
        ? h('div', { class: 'answer-space' }, Array.from({ length: Math.max(1, componentProps.item.answer_space.lines || componentProps.item.answer_space.blank_rows) }, (_, index) => h('i', { key: index })))
        : null,
      componentProps.teacher ? h('section', { class: 'teacher-answer' }, [
        h('p', [h('strong', '参考答案：'), answer()]),
        h('p', [h('strong', '解析：'), componentProps.item.analysis]),
        componentProps.item.scoring_points.length ? h('ol', componentProps.item.scoring_points.map(point => h('li', { key: point.id }, `${point.criterion}（${point.points} 分）：${point.acceptable_evidence}`))) : null,
        componentProps.item.common_errors.length ? h('p', [h('strong', '常见错误：'), componentProps.item.common_errors.join('；')]) : null,
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
  <article class="exercise-paper">
    <header class="paper-header">
      <div>
        <p class="paper-kicker">课后练习 · {{ mode === 'student' ? '学生版' : '教师版' }}</p>
        <h1>{{ content.paper_settings.title }}</h1>
        <p>{{ content.course_info.subject }} · {{ content.course_info.grade_level || content.course_info.audience }}</p>
      </div>
      <div class="mode-switch" role="tablist" aria-label="预览版本">
        <button :class="{ active: mode === 'student' }" @click="mode = 'student'">学生预览</button>
        <button :class="{ active: mode === 'teacher' }" @click="mode = 'teacher'">教师预览</button>
      </div>
    </header>

    <section class="paper-metrics">
      <div><strong>{{ content.paper_settings.total_score }}</strong><span>总分</span></div>
      <div><strong>{{ content.paper_settings.estimated_minutes }}</strong><span>建议分钟</span></div>
      <div><strong>{{ coveredObjectives }}</strong><span>覆盖目标</span></div>
      <div><strong>{{ questions.length }}</strong><span>计分题</span></div>
    </section>

    <section v-if="sourceVersions && Object.keys(sourceVersions).length" class="source-strip">
      <span>本版本参考了</span>
      <b v-for="(version, type) in sourceVersions" :key="type">{{ type }} V{{ version }}</b>
    </section>

    <section v-if="content.review_summary.needs_teacher_attention" class="review-alert">
      <strong>需要教师关注</strong>
      <span>{{ content.review_summary.notes.join('；') }}</span>
    </section>

    <section class="instructions">
      <h2>作答说明</h2>
      <ul><li v-for="item in content.paper_settings.student_instructions" :key="item">{{ item }}</li></ul>
      <p>{{ content.paper_settings.answer_requirements }}</p>
    </section>

    <section v-for="(section, sectionIndex) in content.sections" :key="section.id" class="paper-section">
      <header class="section-header">
        <span>{{ String(sectionIndex + 1).padStart(2, '0') }}</span>
        <div><h2>{{ section.title }}</h2><p>{{ section.score }} 分</p></div>
      </header>

      <template v-for="block in section.blocks" :key="block.id">
        <div v-if="group(block)" class="question-group">
          <header><span>材料题组</span><h3>{{ block.id }} · {{ block.title }}</h3><p>{{ block.instructions }}</p></header>
          <div v-for="stimulus in block.stimuli" :key="stimulus.id" class="stimulus">
            <strong>{{ stimulus.title || '材料' }}</strong>
            <p v-if="stimulus.kind === 'text'">{{ stimulus.text }}</p>
            <table v-else-if="stimulus.kind === 'table'">
              <thead><tr><th v-for="column in stimulus.columns" :key="column">{{ column }}</th></tr></thead>
              <tbody><tr v-for="(row, rowIndex) in stimulus.rows" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td></tr></tbody>
            </table>
            <div v-else-if="stimulus.visual" class="visual-stimulus">
              <img v-if="stimulus.visual.asset_id && assetUrls[stimulus.visual.asset_id]" :src="assetUrls[stimulus.visual.asset_id]" :alt="stimulus.visual.alt_text" />
              <div v-else class="visual-fallback">{{ stimulus.visual.fallback_stimulus }}</div>
              <small>{{ visualStatus(stimulus) }}<template v-if="stimulus.visual.caption"> · {{ stimulus.visual.caption }}</template></small>
            </div>
          </div>
          <ExerciseQuestionView v-for="item in block.sub_questions" :key="item.id" :item="item" :number="numberFor(item)" :teacher="mode === 'teacher'" />
        </div>
        <ExerciseQuestionView v-else :item="block" :number="numberFor(block)" :teacher="mode === 'teacher'" />
      </template>
    </section>
  </article>
</template>

<style scoped>
.exercise-paper { max-width: 900px; margin: 0 auto; padding: 30px; color: #172033; background: #fff; font-family: "Helvetica Neue", "PingFang SC", sans-serif; }
.paper-header { display: flex; justify-content: space-between; gap: 24px; padding-bottom: 22px; border-bottom: 2px solid #172033; }
.paper-kicker { margin: 0 0 7px; color: #4f46e5 !important; font-size: 12px; font-weight: 800; letter-spacing: .08em; }
.paper-header h1 { margin: 0 0 8px; font-size: clamp(24px, 3vw, 34px); line-height: 1.15; }
.paper-header p { margin: 0; color: #64748b; }
.mode-switch { align-self: flex-start; display: flex; border: 1px solid #cbd5e1; padding: 3px; }
.mode-switch button { border: 0; padding: 7px 12px; background: transparent; color: #64748b; cursor: pointer; }
.mode-switch button.active { background: #4f46e5; color: #fff; }
.paper-metrics { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid #dbe2ea; border-top: 0; }
.paper-metrics div { display: flex; align-items: baseline; gap: 7px; padding: 13px 16px; border-right: 1px solid #dbe2ea; }
.paper-metrics div:last-child { border-right: 0; }
.paper-metrics strong { font-size: 22px; color: #4f46e5; }
.paper-metrics span { font-size: 12px; color: #64748b; }
.source-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; padding: 10px 12px; border-bottom: 1px solid #dbe2ea; font-size: 12px; }
.source-strip span { color: #64748b; }.source-strip b { padding: 2px 7px; color: #4338ca; background: #eef2ff; }
.review-alert { margin-top: 18px; padding: 12px 14px; display: grid; gap: 4px; border: 1px solid #f59e0b; background: #fffbeb; font-size: 13px; }
.instructions { padding: 24px 0 10px; }.instructions h2 { margin: 0 0 8px; font-size: 16px; }.instructions ul { margin: 0; padding-left: 20px; }.instructions p { color: #64748b; }
.paper-section { margin-top: 24px; }.section-header { display: grid; grid-template-columns: 54px 1fr; align-items: center; border-bottom: 1px solid #172033; }
.section-header > span { font-size: 32px; font-weight: 900; color: #4f46e5; }.section-header div { display: flex; justify-content: space-between; align-items: baseline; }.section-header h2 { margin: 0; }.section-header p { margin: 0; font-weight: 700; }
.question-group { margin-top: 18px; padding: 18px; border: 1px solid #9aa8ba; }.question-group > header span { color: #4f46e5; font-size: 11px; font-weight: 800; }.question-group > header h3 { margin: 4px 0; }.question-group > header p { margin: 0 0 14px; color: #64748b; }
.stimulus { padding: 14px; background: #f7f7f8; border-left: 3px solid #4f46e5; }.stimulus p { margin-bottom: 0; line-height: 1.7; }.stimulus table { width: 100%; margin-top: 8px; border-collapse: collapse; }.stimulus th,.stimulus td { border: 1px solid #cbd5e1; padding: 7px; text-align: left; }
.visual-stimulus { display: grid; gap: 7px; margin-top: 8px; }.visual-stimulus img { max-width: 100%; max-height: 420px; margin: auto; object-fit: contain; }.visual-fallback { padding: 18px; border: 1px dashed #94a3b8; color: #475569; }.visual-stimulus small { color: #64748b; text-align: center; }
:deep(.question-card) { margin-top: 16px; padding: 18px 0; border-bottom: 1px solid #dbe2ea; }:deep(.question-card > header) { display: grid; grid-template-columns: 42px 1fr; gap: 12px; }
:deep(.question-number) { font-size: 22px; font-weight: 900; color: #4f46e5; }:deep(.question-meta) { margin: 0 0 5px; color: #64748b; font-size: 11px; }:deep(.question-card h3) { margin: 0; font-size: 15px; line-height: 1.6; }
:deep(.mapping-tags) { display: flex; gap: 5px; margin-top: 7px; }:deep(.mapping-tags span) { padding: 2px 6px; background: #eef2ff; color: #4338ca; font-size: 10px; }
:deep(.option-grid) { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 13px 0 0 54px; }:deep(.option-grid div) { display: grid; grid-template-columns: 24px 1fr; padding: 9px; border: 1px solid #dbe2ea; }:deep(.option-grid b) { color: #4f46e5; }
:deep(.answer-space) { display: grid; gap: 16px; margin: 18px 0 0 54px; }:deep(.answer-space i) { display: block; border-bottom: 1px solid #94a3b8; }
:deep(.teacher-answer) { margin: 14px 0 0 54px; padding: 13px 15px; border-left: 3px solid #4f46e5; background: #eef2ff; }:deep(.teacher-answer p) { margin: 4px 0; line-height: 1.6; }:deep(.teacher-answer ol) { margin: 8px 0 0; padding-left: 20px; }
@media (max-width: 700px) { .exercise-paper { padding: 18px; }.paper-header { display: grid; }.paper-metrics { grid-template-columns: 1fr 1fr; }.paper-metrics div:nth-child(2) { border-right: 0; }.option-grid { grid-template-columns: 1fr !important; margin-left: 0 !important; }.answer-space,.teacher-answer { margin-left: 0 !important; } }
</style>
