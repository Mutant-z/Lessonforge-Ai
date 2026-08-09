<script setup lang="ts">
import { ref } from 'vue';
import type { ExerciseQuestion } from '../../types';
import { Refresh, View, Lock } from '@element-plus/icons-vue';

const props = defineProps<{
  exercise: ExerciseQuestion;
  index: number;
}>();

const emit = defineEmits<{
  (e: 'regenerate', id: string): void;
  (e: 'delete', id: string): void;
}>();

const showAnswer = ref(false);

function getDifficultyType(diff: string) {
  if (diff === 'basic') return 'success';
  if (diff === 'advanced') return 'danger';
  return 'warning';
}

function getDifficultyLabel(diff: string) {
  if (diff === 'basic') return '基础巩固';
  if (diff === 'advanced') return '迁移挑战';
  return '理解应用';
}
</script>

<template>
  <div class="exercise-card lf-card card-hover">
    <div class="ex-header">
      <div class="ex-meta">
        <span class="ex-num-badge">第 {{ index + 1 }} 题</span>
        <el-tag size="small" :type="getDifficultyType(exercise.difficulty)" effect="light">
          {{ getDifficultyLabel(exercise.difficulty) }}
        </el-tag>
        <span class="ex-type-chip">{{ exercise.question_type === 'single_choice' ? '单选题' : exercise.question_type === 'multiple_choice' ? '多选题' : exercise.question_type === 'fill_blank' ? '填空题' : '简答与分析题' }}</span>
        <span v-if="exercise.score" class="ex-score-tag">{{ exercise.score }} 分</span>
      </div>

      <div class="ex-actions">
        <el-button size="small" link :icon="View" @click="showAnswer = !showAnswer">
          {{ showAnswer ? '收起解析' : '展开解析' }}
        </el-button>
        <el-button size="small" link :icon="Refresh" @click="emit('regenerate', exercise.id)">
          重新生成
        </el-button>
      </div>
    </div>

    <!-- Question Body -->
    <div class="ex-question">
      <p>{{ exercise.stem }}</p>
    </div>

    <!-- Options if Choice Question -->
    <div v-if="exercise.options && exercise.options.length" class="ex-options">
      <div v-for="(opt, oIdx) in exercise.options" :key="oIdx" class="option-item">
        <span class="opt-letter">{{ opt.id }}</span>
        <span class="opt-text">{{ opt.text }}</span>
      </div>
    </div>

    <!-- Answer and Explanation Area -->
    <div v-if="showAnswer" class="ex-answer-section animate-fade-in">
      <div class="answer-row">
        <span class="callout-label green">✓ 正确答案：</span>
        <span class="answer-text">{{ exercise.answer_key.correct_option_ids.join('、') || exercise.answer_key.accepted_answers.join('、') || exercise.answer_key.reference_answer }}</span>
      </div>
      <div v-if="exercise.analysis" class="explanation-row">
        <span class="callout-label violet">💡 详尽解析：</span>
        <p class="explanation-text">{{ exercise.analysis }}</p>
      </div>
      <div v-if="exercise.objective_ids && exercise.objective_ids.length" class="objective-ref">
        🎯 关联教学目标：{{ exercise.objective_ids.join('、') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.exercise-card {
  margin-bottom: 20px;
  background: var(--bg-card, #ffffff);
  border: 1px solid var(--border-light, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
  padding: 18px 20px;
}

.ex-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--border-light, #e2e8f0);
}

.ex-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ex-num-badge {
  background: #4f46e5;
  color: #ffffff;
  font-size: 12px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 6px;
}

.ex-type-chip {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
}

.ex-score-tag {
  font-size: 12px;
  color: #64748b;
  font-weight: 600;
}

.ex-question p {
  margin: 0 0 14px;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.6;
  color: var(--text-primary, #0f172a);
}

.ex-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 16px;
}

@media (max-width: 640px) {
  .ex-options {
    grid-template-columns: 1fr;
  }
}

.option-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid var(--border-default, #cbd5e1);
  border-radius: var(--radius-md, 8px);
  font-size: 13.5px;
}

.opt-letter {
  font-weight: 800;
  color: #4f46e5;
}

.ex-answer-section {
  padding: 14px 18px;
  background: #f8fafc;
  border-left: 4px solid #4f46e5;
  border-radius: 0 var(--radius-md, 8px) var(--radius-md, 8px) 0;
  font-size: 13px;
}

.answer-row {
  margin-bottom: 8px;
}

.callout-label {
  font-weight: 800;
}

.callout-label.green {
  color: #15803d;
}

.callout-label.violet {
  color: #7e22ce;
}

.answer-text {
  font-weight: 700;
  color: #15803d;
}

.explanation-row {
  color: var(--text-secondary, #334155);
  line-height: 1.6;
  margin-top: 8px;
}

.explanation-text {
  margin: 4px 0 0;
}

.objective-ref {
  margin-top: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #4338ca;
  background: #e0e7ff;
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
}
</style>
