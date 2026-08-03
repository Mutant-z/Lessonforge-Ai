<script setup lang="ts">
import type { ExerciseContent, ExerciseQuestion, ExerciseQuestionGroup } from '../../types';

const model = defineModel<ExerciseContent>({ required: true });

const typeOptions = [
  ['single_choice', '单选题'], ['multiple_choice', '多选题'], ['true_false', '判断题'], ['fill_blank', '填空题'],
  ['short_answer', '简答题'], ['calculation', '计算题'], ['case_analysis', '案例分析'], ['practical_task', '实践任务'],
] as const;

function isGroup(block: ExerciseQuestion | ExerciseQuestionGroup): block is ExerciseQuestionGroup {
  return block.kind === 'question_group';
}

function questions(block: ExerciseQuestion | ExerciseQuestionGroup) {
  return isGroup(block) ? block.sub_questions : [block];
}

function split(value: string) {
  return value.split(/[、,，\s]+/).map(item => item.trim()).filter(Boolean);
}

function setAnswer(question: ExerciseQuestion, value: string) {
  if (['single_choice', 'multiple_choice'].includes(question.question_type)) {
    question.answer_key.correct_option_ids = split(value);
  } else if (question.question_type === 'fill_blank' || question.question_type === 'true_false') {
    question.answer_key.accepted_answers = split(value);
  } else {
    question.answer_key.reference_answer = value;
  }
}
</script>

<template>
  <div class="exercise-editor">
    <header>
      <div><span>结构化编辑</span><h2>{{ model.paper_settings.title }}</h2></div>
      <div class="paper-fields">
        <label>总分<el-input-number v-model="model.paper_settings.total_score" :min="1" :max="1000" /></label>
        <label>建议用时<el-input-number v-model="model.paper_settings.estimated_minutes" :min="1" :max="180" /></label>
      </div>
    </header>

    <el-form label-position="top">
      <el-form-item label="试卷标题"><el-input v-model="model.paper_settings.title" /></el-form-item>
      <el-form-item label="作答要求"><el-input v-model="model.paper_settings.answer_requirements" type="textarea" :rows="2" /></el-form-item>
    </el-form>

    <section v-for="section in model.sections" :key="section.id" class="editor-section">
      <header><div><small>{{ section.id }}</small><el-input v-model="section.title" /></div><label>分区分值<el-input-number v-model="section.score" :min="1" /></label></header>
      <div v-for="block in section.blocks" :key="block.id" class="editor-block">
        <template v-if="isGroup(block)">
          <div class="group-fields">
            <span>材料题组</span><el-input v-model="block.title" /><el-input v-model="block.instructions" placeholder="题组说明" />
          </div>
          <div v-for="stimulus in block.stimuli" :key="stimulus.id" class="stimulus-fields">
            <el-input v-model="stimulus.title" placeholder="材料标题" />
            <el-input v-if="stimulus.kind === 'text'" v-model="stimulus.text" type="textarea" :rows="3" placeholder="材料正文" />
            <template v-else-if="stimulus.kind === 'visual' && stimulus.visual">
              <el-input v-model="stimulus.visual.purpose" placeholder="配图用途" />
              <el-input v-model="stimulus.visual.alt_text" placeholder="替代文本" />
              <el-input v-model="stimulus.visual.fallback_stimulus" type="textarea" :rows="2" placeholder="生成或复核失败时的等价材料" />
              <el-input v-if="stimulus.visual.mode === 'generated_image'" v-model="stimulus.visual.generation_prompt" type="textarea" :rows="2" placeholder="图片生成提示词" />
            </template>
          </div>
        </template>

        <article v-for="question in questions(block)" :key="question.id" class="question-editor">
          <header><strong>{{ question.id }}</strong><el-select v-model="question.question_type"><el-option v-for="item in typeOptions" :key="item[0]" :label="item[1]" :value="item[0]" /></el-select></header>
          <el-input v-model="question.stem" type="textarea" :rows="2" placeholder="题干" />
          <div class="question-grid">
            <label>分值<el-input-number v-model="question.score" :min="1" /></label>
            <label>预计分钟<el-input-number v-model="question.estimated_minutes" :min="0.5" :step="0.5" /></label>
            <label>目标 ID<el-input :model-value="question.objective_ids.join('、')" @update:model-value="question.objective_ids = split($event)" /></label>
            <label>知识点 ID<el-input :model-value="question.knowledge_point_ids.join('、')" @update:model-value="question.knowledge_point_ids = split($event)" /></label>
          </div>
          <div v-if="question.options.length" class="option-editor">
            <label v-for="option in question.options" :key="option.id"><b>{{ option.id }}</b><el-input v-model="option.text" /></label>
          </div>
          <el-input :model-value="question.answer_key.correct_option_ids.join('、') || question.answer_key.accepted_answers.join('、') || question.answer_key.reference_answer" type="textarea" :rows="2" placeholder="正确答案或参考答案" @update:model-value="setAnswer(question, $event)" />
          <el-input v-model="question.analysis" type="textarea" :rows="2" placeholder="教师版解析" />
          <div v-if="question.scoring_points.length" class="rubric-editor">
            <strong>分步评分点</strong>
            <div v-for="point in question.scoring_points" :key="point.id"><el-input v-model="point.criterion" /><el-input-number v-model="point.points" :min="1" /><el-input v-model="point.acceptable_evidence" /></div>
          </div>
          <div class="question-grid"><label>作答空间<el-select v-model="question.answer_space.mode"><el-option label="无" value="none" /><el-option label="横线" value="lines" /><el-option label="方格" value="grid" /><el-option label="表格" value="table" /></el-select></label><label>行数<el-input-number v-model="question.answer_space.lines" :min="0" :max="30" /></label></div>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.exercise-editor { display: grid; gap: 18px; padding: 24px; font-family: "Helvetica Neue", "PingFang SC", sans-serif; color: #172033; }
.exercise-editor > header { display: flex; justify-content: space-between; gap: 20px; padding-bottom: 16px; border-bottom: 2px solid #172033; }.exercise-editor > header span { color: #4f46e5; font-size: 11px; font-weight: 800; }.exercise-editor h2 { margin: 4px 0 0; }.paper-fields { display: flex; gap: 12px; }.paper-fields label,.editor-section > header label,.question-grid label { display: grid; gap: 5px; color: #64748b; font-size: 11px; }
.editor-section { border: 1px solid #cbd5e1; }.editor-section > header { display: flex; justify-content: space-between; align-items: end; padding: 14px; background: #f7f7f8; border-bottom: 1px solid #cbd5e1; }.editor-section > header small { display: block; margin-bottom: 5px; color: #4f46e5; }.editor-section > header > div { min-width: 280px; }
.editor-block { padding: 14px; border-bottom: 1px solid #dbe2ea; }.editor-block:last-child { border-bottom: 0; }.group-fields,.stimulus-fields { display: grid; gap: 8px; margin-bottom: 12px; padding: 12px; background: #eef2ff; }.group-fields span { color: #4338ca; font-size: 11px; font-weight: 800; }
.question-editor { display: grid; gap: 10px; padding: 14px 0; border-top: 1px solid #dbe2ea; }.question-editor > header { display: flex; justify-content: space-between; }.question-editor > header strong { color: #4f46e5; }.question-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }.option-editor { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }.option-editor label { display: grid; grid-template-columns: 24px 1fr; align-items: center; }.option-editor b { color: #4f46e5; }.rubric-editor { display: grid; gap: 8px; padding: 12px; background: #f7f7f8; }.rubric-editor > div { display: grid; grid-template-columns: 1fr 100px 1.5fr; gap: 8px; }
@media (max-width: 760px) { .exercise-editor > header,.editor-section > header { align-items: stretch; flex-direction: column; }.paper-fields,.question-grid,.option-editor { grid-template-columns: 1fr; display: grid; }.rubric-editor > div { grid-template-columns: 1fr; } }
</style>
