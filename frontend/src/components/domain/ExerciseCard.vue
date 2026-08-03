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
        <span class="ex-num">第 {{ index + 1 }} 题</span>
        <el-tag size="small" :type="getDifficultyType(exercise.difficulty)">
          {{ getDifficultyLabel(exercise.difficulty) }}
        </el-tag>
        <span class="ex-type">{{ exercise.question_type === 'single_choice' ? '单选题' : exercise.question_type === 'multiple_choice' ? '多选题' : exercise.question_type === 'fill_blank' ? '填空题' : '简答与分析题' }}</span>
      </div>

      <div class="ex-actions">
        <el-button size="small" link :icon="View" @click="showAnswer = !showAnswer">
          {{ showAnswer ? '隐藏答案解析' : '显示答案解析' }}
        </el-button>
        <el-button size="small" link :icon="Refresh" @click="emit('regenerate', exercise.id)">
          重生此题
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
        {{ opt.id }}. {{ opt.text }}
      </div>
    </div>

    <!-- Answer and Explanation Area -->
    <div v-if="showAnswer" class="ex-answer-section animate-fade-in">
      <div class="answer-row">
        <strong>【正确答案】:</strong>
        <span class="answer-text">{{ exercise.answer_key.correct_option_ids.join('、') || exercise.answer_key.accepted_answers.join('、') || exercise.answer_key.reference_answer }}</span>
      </div>
      <div class="explanation-row">
        <strong>【解析指南】:</strong>
        <p class="explanation-text">{{ exercise.analysis }}</p>
      </div>
      <div v-if="exercise.objective_ids.length" class="objective-ref">
        关联教学目标: {{ exercise.objective_ids.join('、') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.exercise-card {
  margin-bottom: 20px;
}

.ex-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}

.ex-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ex-num {
  font-size: 14px;
  font-weight: 800;
  color: var(--color-primary);
}

.ex-type {
  font-size: 12px;
  color: var(--text-muted);
}

.ex-question p {
  margin: 0 0 14px;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--text-primary);
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
  padding: 10px 14px;
  background: var(--bg-page);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-size: 13px;
}

.ex-answer-section {
  padding: 14px 18px;
  background: var(--color-primary-soft);
  border-left: 3px solid var(--color-primary);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  font-size: 13px;
}

.answer-row {
  margin-bottom: 8px;
  color: var(--color-primary);
}

.answer-text {
  font-weight: 700;
  margin-left: 6px;
}

.explanation-row {
  color: var(--text-secondary);
  line-height: 1.6;
}

.explanation-text {
  margin: 4px 0 0;
}

.objective-ref {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-muted);
}
</style>
