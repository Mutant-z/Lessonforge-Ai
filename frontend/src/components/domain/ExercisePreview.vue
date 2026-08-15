<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, ref, watchEffect, type PropType } from 'vue';
import { api } from '../../api/client';
import type { ExerciseContent, ExerciseQuestion, ExerciseQuestionGroup, ExerciseStimulus } from '../../types';
import { Check, Clock, Document, Reading, Star, Warning, Printer, EditPen, Delete } from '@element-plus/icons-vue';

const props = defineProps<{
  content: ExerciseContent;
  sourceVersions?: Record<string, number>;
}>();

const mode = ref<'student' | 'teacher'>('teacher');
const assetUrls = ref<Record<string, string>>({});
const studentAnswers = ref<Record<string, string>>({});
const studentBlanks = ref<Record<string, Record<number, string>>>({});

const questionTypeLabels: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  calculation: '综合计算题',
  case_analysis: '案例分析',
  practical_task: '实践任务',
};

const cognitiveLabels: Record<string, { label: string; class: string }> = {
  remember: { label: '记忆识记', class: 'cog-remember' },
  understand: { label: '理解领会', class: 'cog-understand' },
  apply: { label: '应用实践', class: 'cog-apply' },
  analyze: { label: '分析关联', class: 'cog-analyze' },
  transfer: { label: '迁移创新', class: 'cog-transfer' },
  evaluate: { label: '评价反思', class: 'cog-evaluate' },
  create: { label: '创造设计', class: 'cog-create' },
};

const difficultyLabels: Record<string, { label: string; class: string }> = {
  basic: { label: '基础巩固', class: 'diff-basic' },
  core: { label: '核心应用', class: 'diff-core' },
  advanced: { label: '迁移挑战', class: 'diff-advanced' },
};

function formatMathText(text: string): string {
  if (!text) return '';
  let res = text;
  // 识别与高亮常见物理/数学公式符号：如 G = 4.0 N, F拉 = 2.5 N, F上 = 4 N, F下 = 10 N, F浮, p=ρgh, Δh, ρ_液 g V_排 等
  res = res.replace(
    /\b(G\s*=\s*\d+(?:\.\d+)?\s*[Nn]|F\s*拉\s*=\s*\d+(?:\.\d+)?\s*[Nn]|G\s*桶\s*=\s*\d+(?:\.\d+)?\s*[Nn]|G\s*总\s*=\s*\d+(?:\.\d+)?\s*[Nn]|G\s*排\s*=\s*\d+(?:\.\d+)?\s*[Nn]|F\s*上\s*=\s*\d+(?:\.\d+)?\s*[Nn]|F\s*下\s*=\s*\d+(?:\.\d+)?\s*[Nn]|F\s*浮|F\s*上|F\s*下|G\s*排|G\s*物|G\s*桶|G\s*总|F\s*拉|p\s*=\s*ρgh|Δh|ρ|g|h|V\s*排)\b/g,
    '<code class="math-badge">$1</code>'
  );
  return res;
}

const quickSymbols = ['F浮', 'F上', 'F下', 'G排', 'p=ρgh', 'Δh', 'N', 'Pa', '=', '>', '<', 'ρ'];

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

    const diffInfo = computed(() => difficultyLabels[componentProps.item.difficulty] || { label: '基础巩固', class: 'diff-basic' });
    const cogInfo = computed(() => cognitiveLabels[componentProps.item.cognitive_level] || { label: '理解领会', class: 'cog-understand' });

    // 计算填空题空位数量
    const blanksCount = computed(() => {
      if (componentProps.item.question_type !== 'fill_blank') return 0;
      if (componentProps.item.answer_key.accepted_answers?.length) {
        return componentProps.item.answer_key.accepted_answers.length;
      }
      const matches = componentProps.item.stem.match(/(?:_{2,}|（\s*）|\(\s*\)|【\s*】)/g);
      return matches ? Math.max(1, matches.length) : 2;
    });

    function insertSymbol(symbol: string) {
      const qid = componentProps.item.id;
      const current = studentAnswers.value[qid] || '';
      studentAnswers.value[qid] = current + (current ? ' ' : '') + symbol;
    }

    return () => h('article', { class: 'fancy-question-card' }, [
      // Card Header
      h('header', { class: 'fancy-q-header' }, [
        h('div', { class: 'q-header-left' }, [
          h('span', { class: 'q-number-badge' }, String(componentProps.number).padStart(2, '0')),
          h('span', { class: 'q-type-chip' }, questionTypeLabels[componentProps.item.question_type] || '单选题'),
          h('span', { class: `q-diff-badge ${diffInfo.value.class}` }, diffInfo.value.label),
          h('span', { class: `q-cog-badge ${cogInfo.value.class}` }, cogInfo.value.label),
          h('span', { class: 'q-score-chip' }, `${componentProps.item.score} 分`),
          h('span', { class: 'q-time-chip' }, `⏱ ${componentProps.item.estimated_minutes} 分钟`),
        ]),
        componentProps.item.objective_ids.length
          ? h('div', { class: 'q-target-tags' }, componentProps.item.objective_ids.map(id => h('span', { key: id, class: 'target-chip' }, `🎯 ${id}`)))
          : null,
      ]),

      // Stem / Question Text
      h('div', { class: 'fancy-q-stem' }, [
        h('h3', { innerHTML: formatMathText(componentProps.item.stem) }),
      ]),

      // Options (if choice question)
      componentProps.item.options.length
        ? h('div', { class: 'fancy-options-grid' }, componentProps.item.options.map(option => {
            const isSelected = studentAnswers.value[componentProps.item.id] === option.id;
            const isCorrect = componentProps.teacher && componentProps.item.answer_key.correct_option_ids.includes(option.id);
            return h('div', {
              key: option.id,
              class: ['fancy-option-item', isSelected ? 'is-selected' : '', isCorrect ? 'is-correct' : ''],
              onClick: () => {
                if (!componentProps.teacher) {
                  studentAnswers.value[componentProps.item.id] = option.id;
                }
              }
            }, [
              h('span', { class: ['opt-letter', isCorrect ? 'correct-letter' : ''] }, option.id),
              h('span', { class: 'opt-text', innerHTML: formatMathText(option.text) }),
            ]);
          }))
        : null,

      // -------------------------------------------------------------
      // 高档交互式学生作答区（全宽画布 + 快捷符号栏 + 结构化填空卡片）
      // -------------------------------------------------------------
      !componentProps.teacher && !componentProps.item.options.length
        ? h('div', { class: 'fancy-answer-space' }, [
            // 1. 作答区头部工具条
            h('div', { class: 'space-header' }, [
              h('div', { class: 'space-header-left' }, [
                h('span', { class: 'space-icon' }, '✍️'),
                h('span', { class: 'space-title' }, componentProps.item.question_type === 'fill_blank' ? '学生规范填空与演算推导' : '学生规范作答区'),
                h('span', { class: 'space-type-tag' }, questionTypeLabels[componentProps.item.question_type] || '主观题'),
              ]),
              h('div', { class: 'space-header-right' }, [
                h('span', { class: 'char-counter' }, `已输入 ${(studentAnswers.value[componentProps.item.id] || '').length} 字`),
                (studentAnswers.value[componentProps.item.id] || '').length > 0
                  ? h('button', {
                      type: 'button',
                      class: 'clear-ans-btn',
                      title: '清空作答内容',
                      onClick: () => { studentAnswers.value[componentProps.item.id] = ''; }
                    }, '清空')
                  : h('span', { class: 'ans-status-pill' }, '📝 待作答')
              ])
            ]),

            // 2. 针对填空题展示结构化填空槽位
            componentProps.item.question_type === 'fill_blank' && blanksCount.value > 0
              ? h('div', { class: 'structured-blanks-grid' },
                  Array.from({ length: blanksCount.value }, (_, idx) => {
                    const blankNum = idx + 1;
                    const val = (studentBlanks.value[componentProps.item.id] ??= {})[blankNum] || '';
                    return h('div', { key: blankNum, class: 'blank-slot-card' }, [
                      h('span', { class: 'slot-badge' }, `第 (${blankNum}) 空`),
                      h('input', {
                        type: 'text',
                        class: 'blank-slot-input',
                        placeholder: `输入第 (${blankNum}) 空答案...`,
                        value: val,
                        onInput: (e: Event) => {
                          const targetVal = (e.target as HTMLInputElement).value;
                          studentBlanks.value[componentProps.item.id][blankNum] = targetVal;
                          // 自动同步组合到主答案中
                          const combined = Object.keys(studentBlanks.value[componentProps.item.id])
                            .sort((a, b) => Number(a) - Number(b))
                            .map(k => `(${k}) ${studentBlanks.value[componentProps.item.id][Number(k)]}`)
                            .join('；');
                          studentAnswers.value[componentProps.item.id] = combined;
                        }
                      })
                    ]);
                  })
                )
              : null,

            // 3. 快捷物理量与符号输入栏
            h('div', { class: 'quick-symbol-toolbar' }, [
              h('span', { class: 'symbol-label' }, '快捷符号:'),
              h('div', { class: 'symbol-chips-row' },
                quickSymbols.map(sym => h('button', {
                  key: sym,
                  type: 'button',
                  class: 'symbol-chip-btn',
                  onClick: () => insertSymbol(sym)
                }, `+ ${sym}`))
              )
            ]),

            // 4. 全宽现代化答题多行输入画布
            h('div', { class: 'textarea-wrapper' }, [
              h('textarea', {
                class: 'student-textarea-input',
                rows: Math.max(3, componentProps.item.answer_space.lines || componentProps.item.answer_space.blank_rows || 3),
                placeholder: componentProps.item.question_type === 'fill_blank'
                  ? '在此记录演算草稿、公式推导或详细步骤（选填）...'
                  : '请在此规范输入解答思路、推导步骤、物理公式及最终结论...',
                value: studentAnswers.value[componentProps.item.id] || '',
                onInput: (e: Event) => {
                  studentAnswers.value[componentProps.item.id] = (e.target as HTMLTextAreaElement).value;
                }
              }),
            ]),

            // 5. 打印专属横线纸（仅在打印时呈现）
            h('div', { class: 'paper-print-ruled-lines print-only' },
              Array.from({ length: Math.max(3, componentProps.item.answer_space.lines || componentProps.item.answer_space.blank_rows || 3) }, (_, index) => h('i', { key: index, class: 'ruled-line' }))
            )
          ])
        : null,

      // Teacher Answer & Analysis Callouts
      componentProps.teacher ? h('div', { class: 'fancy-teacher-panel' }, [
        // Answer Callout Box
        h('div', { class: 'teacher-callout answer-callout' }, [
          h('div', { class: 'callout-title' }, [
            h('span', { class: 'callout-badge green' }, '✓ 参考答案'),
          ]),
          h('div', { class: 'callout-body answer-body', innerHTML: formatMathText(answer()) }),
        ]),

        // Analysis Callout Box
        componentProps.item.analysis
          ? h('div', { class: 'teacher-callout analysis-callout' }, [
              h('div', { class: 'callout-title' }, [
                h('span', { class: 'callout-badge violet' }, '💡 详细解析与思路引导'),
              ]),
              h('p', { class: 'callout-body', innerHTML: formatMathText(componentProps.item.analysis) }),
            ])
          : null,

        // Scoring Rubric
        componentProps.item.scoring_points.length
          ? h('div', { class: 'teacher-callout rubric-callout' }, [
              h('div', { class: 'callout-title' }, [
                h('span', { class: 'callout-badge blue' }, '📝 阶梯得分点与采分标准'),
              ]),
              h('ul', { class: 'rubric-list' }, componentProps.item.scoring_points.map(point => h('li', { key: point.id }, [
                h('span', { class: 'rubric-pts' }, `+${point.points}分`),
                h('strong', `${point.criterion}：`),
                h('span', { innerHTML: formatMathText(point.acceptable_evidence) }),
              ]))),
            ])
          : null,

        // Common Error Analysis
        componentProps.item.common_errors.length
          ? h('div', { class: 'teacher-callout warning-callout' }, [
              h('div', { class: 'callout-title' }, [
                h('span', { class: 'callout-badge amber' }, '⚠️ 常见易错点与避坑策略'),
              ]),
              h('p', { class: 'callout-body', innerHTML: formatMathText(componentProps.item.common_errors.join('；')) }),
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

function handlePrint() {
  window.print();
}
</script>

<template>
  <div class="fancy-exercise-paper">
    <!-- 顶部控制栏 -->
    <div class="print-control-bar no-print">
      <div class="control-left">
        <span class="control-badge">🎯 梯度精选试题集 · 智能达标检测</span>
        <span class="control-hint">支持一键切换学生答题卡与教师讲评版</span>
      </div>
      <div class="control-right">
        <div class="mode-switch-pill" role="tablist">
          <button
            type="button"
            :class="{ active: mode === 'student' }"
            @click="mode = 'student'"
          >
            <el-icon><EditPen /></el-icon> ✍️ 学生答题卷
          </button>
          <button
            type="button"
            :class="{ active: mode === 'teacher' }"
            @click="mode = 'teacher'"
          >
            <el-icon><Reading /></el-icon> 📖 教师讲评卷
          </button>
        </div>
        <el-button type="primary" size="small" :icon="Printer" class="print-btn" @click="handlePrint">
          打印 / 导出 PDF 试卷
        </el-button>
      </div>
    </div>

    <!-- 深色高档试卷看板 -->
    <header class="fancy-paper-masthead">
      <div class="masthead-top">
        <div class="masthead-kicker">
          <span class="pulse-dot"></span>
          <span>STAGE 04 · 课后练习与达标测评卷</span>
        </div>
        <div class="masthead-status-chip">
          <span>✓ 100分制梯度对齐</span>
        </div>
      </div>

      <div class="masthead-title-row">
        <h1 class="paper-title">{{ content.paper_settings.title || '阿基米德原理与浮力产生原因 · 课后巩固与达标测试' }}</h1>
        <div class="paper-meta-row">
          <span class="meta-tag subject-tag">{{ content.course_info.subject || '物理' }}</span>
          <span class="meta-tag grade-tag">{{ content.course_info.grade_level || content.course_info.audience || '初中八年级' }}</span>
          <span class="meta-tag duration-tag">⏱️ 10 分钟微课配套</span>
        </div>
      </div>

      <!-- 4 格核心测试指标网格 -->
      <div class="masthead-metrics">
        <div class="metric-card">
          <span class="metric-icon">💯</span>
          <div class="metric-detail">
            <span class="metric-label">全卷总分</span>
            <span class="metric-val highlight">{{ content.paper_settings.total_score || 100 }} 分</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-icon">⏱️</span>
          <div class="metric-detail">
            <span class="metric-label">建议用时</span>
            <span class="metric-val">{{ content.paper_settings.estimated_minutes || 15 }} 分钟</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-icon">📝</span>
          <div class="metric-detail">
            <span class="metric-label">题量总数</span>
            <span class="metric-val">{{ questions.length }} 道大题</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-icon">🎯</span>
          <div class="metric-detail">
            <span class="metric-label">覆盖教学目标</span>
            <span class="metric-val success">{{ coveredObjectives }} 个目标</span>
          </div>
        </div>
      </div>
    </header>

    <!-- 教师复核提醒 (若存在) -->
    <section v-if="content.review_summary.needs_teacher_attention" class="fancy-review-alert">
      <el-icon class="alert-icon"><Warning /></el-icon>
      <div>
        <strong>教师关注提示：</strong>
        <span>{{ content.review_summary.notes.join('；') }}</span>
      </div>
    </section>

    <!-- 学生作答说明与答题要求 -->
    <section class="fancy-instructions-card">
      <div class="instructions-head">
        <span class="instructions-icon">📋</span>
        <span class="instructions-title">作答说明与答题要求</span>
      </div>
      <ul class="instructions-list">
        <li v-for="item in content.paper_settings.student_instructions" :key="item">{{ item }}</li>
      </ul>
      <p v-if="content.paper_settings.answer_requirements" class="req-text">
        {{ content.paper_settings.answer_requirements }}
      </p>
    </section>

    <!-- 各版块与题目卡片列表 -->
    <section v-for="(section, sectionIndex) in content.sections" :key="section.id" class="fancy-paper-section">
      <header class="section-banner">
        <div class="section-idx-badge">{{ String(sectionIndex + 1).padStart(2, '0') }}</div>
        <div class="section-heading">
          <h2>{{ section.title }}</h2>
          <span class="section-score-tag">本模块共 {{ section.score }} 分</span>
        </div>
      </header>

      <template v-for="block in section.blocks" :key="block.id">
        <!-- 材料题组 (Stimulus + Sub questions) -->
        <div v-if="group(block)" class="fancy-question-group">
          <header class="group-header">
            <span class="group-badge">材料阅读题组</span>
            <h3>{{ block.title }}</h3>
            <p v-if="block.instructions" class="group-inst">{{ block.instructions }}</p>
          </header>

          <div v-for="stimulus in block.stimuli" :key="stimulus.id" class="fancy-stimulus-card">
            <strong class="stimulus-title">{{ stimulus.title || '材料背景' }}</strong>
            <p v-if="stimulus.kind === 'text'" class="stimulus-text" v-html="formatMathText(stimulus.text)"></p>
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

        <!-- 独立单题 -->
        <ExerciseQuestionView
          v-else
          :item="block"
          :number="numberFor(block)"
          :teacher="mode === 'teacher'"
        />
      </template>
    </section>
  </div>
</template>

<style scoped>
.fancy-exercise-paper {
  max-width: 1020px;
  margin: 0 auto;
  padding: 20px 24px 40px;
  color: #0f172a;
  background: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  box-sizing: border-box;
}

/* 顶部控制栏 */
.print-control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 18px;
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  margin-bottom: 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
  flex-wrap: wrap;
  gap: 12px;
}

.control-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.control-badge {
  font-size: 12.5px;
  font-weight: 800;
  color: #4338ca;
}

.control-hint {
  font-size: 11.5px;
  color: #64748b;
}

.control-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mode-switch-pill {
  display: flex;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 999px;
  border: 1px solid #e2e8f0;
}

.mode-switch-pill button {
  display: flex;
  align-items: center;
  gap: 6px;
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
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.12);
}

/* 深色高档试卷看板 */
.fancy-paper-masthead {
  padding: 22px 26px;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #1e293b 100%);
  border-radius: 18px;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.12);
  position: relative;
  overflow: hidden;
  margin-bottom: 20px;
}

.fancy-paper-masthead::after {
  content: '';
  position: absolute;
  top: -40%;
  right: -20%;
  width: 260px;
  height: 260px;
  background: radial-gradient(circle, rgba(129, 140, 248, 0.25) 0%, rgba(129, 140, 248, 0) 70%);
  pointer-events: none;
}

.masthead-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.masthead-kicker {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #818cf8;
  background: rgba(99, 102, 241, 0.18);
  border: 1px solid rgba(99, 102, 241, 0.3);
  padding: 4px 12px;
  border-radius: 999px;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 8px #34d399;
  animation: paper-pulse 2s infinite ease-in-out;
}

@keyframes paper-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

.masthead-status-chip {
  font-size: 11px;
  font-weight: 800;
  color: #6ee7b7;
  background: rgba(16, 185, 129, 0.18);
  border: 1px solid rgba(16, 185, 129, 0.35);
  padding: 3px 10px;
  border-radius: 999px;
}

.masthead-title-row {
  margin-bottom: 16px;
}

.paper-title {
  margin: 0 0 8px 0;
  font-size: 22px;
  font-weight: 900;
  color: #ffffff;
  line-height: 1.3;
  letter-spacing: -0.02em;
}

.paper-meta-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
}

.subject-tag {
  color: #c7d2fe;
  background: rgba(99, 102, 241, 0.2);
  border: 1px solid rgba(99, 102, 241, 0.3);
}

.grade-tag {
  color: #bae6fd;
  background: rgba(2, 132, 199, 0.2);
  border: 1px solid rgba(2, 132, 199, 0.3);
}

.duration-tag {
  color: #fde68a;
  background: rgba(217, 119, 6, 0.2);
  border: 1px solid rgba(217, 119, 6, 0.3);
}

.masthead-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  backdrop-filter: blur(8px);
}

.metric-card .metric-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.metric-card .metric-detail {
  display: flex;
  flex-direction: column;
}

.metric-card .metric-label {
  font-size: 10.5px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.metric-card .metric-val {
  font-size: 13.5px;
  font-weight: 900;
  color: #f8fafc;
  margin-top: 1px;
}

.metric-card .metric-val.highlight {
  color: #38bdf8;
  font-variant-numeric: tabular-nums;
}

.metric-card .metric-val.success {
  color: #6ee7b7;
}

/* 提示与要求 */
.fancy-review-alert {
  margin-bottom: 16px;
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
  margin-bottom: 24px;
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  padding: 16px 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
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
  margin: 0 0 6px 0;
  padding-left: 20px;
  font-size: 13px;
  color: #475569;
  line-height: 1.65;
}

.req-text {
  margin: 0;
  font-size: 12px;
  color: #64748b;
  font-style: italic;
}

/* 版块区域 */
.fancy-paper-section {
  margin-top: 28px;
}

.section-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 2px solid #0f172a;
}

.section-idx-badge {
  font-size: 14px;
  font-weight: 900;
  color: #ffffff;
  background: #0f172a;
  padding: 4px 10px;
  border-radius: 6px;
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex: 1;
}

.section-heading h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 900;
  color: #0f172a;
}

.section-score-tag {
  font-size: 12px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 6px;
}

/* 题目卡片通用样式 */
:deep(.fancy-question-card) {
  margin-top: 18px;
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  padding: 22px 24px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
  transition: all 180ms ease;
}

:deep(.fancy-question-card:hover) {
  border-color: #cbd5e1;
  box-shadow: 0 6px 24px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

:deep(.fancy-q-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

:deep(.q-header-left) {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

:deep(.q-number-badge) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  color: #ffffff;
  font-size: 12px;
  font-weight: 900;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.25);
}

:deep(.q-type-chip) {
  font-size: 11px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 3px 9px;
  border-radius: 6px;
}

:deep(.q-diff-badge) {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 6px;
}

:deep(.q-diff-badge.diff-basic) {
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
}

:deep(.q-diff-badge.diff-core) {
  color: #0369a1;
  background: #e0f2fe;
  border: 1px solid #bae6fd;
}

:deep(.q-diff-badge.diff-advanced) {
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
}

:deep(.q-cog-badge) {
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 3px 9px;
  border-radius: 6px;
}

:deep(.q-score-chip),
:deep(.q-time-chip) {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 3px 9px;
  border-radius: 6px;
  font-variant-numeric: tabular-nums;
}

:deep(.q-target-tags) {
  display: flex;
  gap: 6px;
}

:deep(.target-chip) {
  font-size: 11px;
  font-weight: 700;
  color: #6d28d9;
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  padding: 2px 8px;
  border-radius: 6px;
}

/* 题干排版 */
:deep(.fancy-q-stem) {
  margin: 14px 0 16px;
}

:deep(.fancy-q-stem h3) {
  margin: 0;
  font-size: 15.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.75;
  letter-spacing: 0.01em;
}

/* 公式高亮 Badge */
:deep(.math-badge) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13.5px;
  font-weight: 700;
  background: #eef2ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
  padding: 1px 6px;
  border-radius: 5px;
  margin: 0 2px;
}

/* 选项网格 */
:deep(.fancy-options-grid) {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 16px;
}

:deep(.fancy-option-item) {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  transition: all 180ms ease;
  cursor: pointer;
}

:deep(.fancy-option-item:hover) {
  background: #ffffff;
  border-color: #a5b4fc;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.08);
}

:deep(.fancy-option-item.is-selected) {
  background: #eef2ff;
  border-color: #6366f1;
}

:deep(.fancy-option-item.is-correct) {
  background: #f0fdf4;
  border-color: #86efac;
}

:deep(.opt-letter) {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #e0e7ff;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 900;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

:deep(.opt-letter.correct-letter) {
  background: #10b981;
  color: #ffffff;
}

:deep(.opt-text) {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  line-height: 1.5;
}

/* -------------------------------------------------------------
   高档交互式学生作答区（全宽画布 + 快捷符号栏 + 结构化填空卡片）
   ------------------------------------------------------------- */
:deep(.fancy-answer-space) {
  margin-top: 18px;
  padding: 16px 18px;
  background: #f8fafc;
  border: 1.5px solid #cbd5e1;
  border-radius: 14px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

:deep(.space-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e2e8f0;
  flex-wrap: wrap;
}

:deep(.space-header-left),
:deep(.space-header-right) {
  display: flex;
  align-items: center;
  gap: 8px;
}

:deep(.space-icon) {
  font-size: 15px;
}

:deep(.space-title) {
  font-size: 13px;
  font-weight: 800;
  color: #334155;
  letter-spacing: 0.02em;
}

:deep(.space-type-tag) {
  font-size: 11px;
  font-weight: 700;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 2px 7px;
  border-radius: 6px;
}

:deep(.char-counter) {
  font-size: 11.5px;
  font-weight: 700;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

:deep(.clear-ans-btn) {
  font-size: 11px;
  font-weight: 700;
  color: #dc2626;
  background: #fee2e2;
  border: 1px solid #fca5a5;
  padding: 2px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.clear-ans-btn:hover) {
  background: #fecaca;
}

:deep(.ans-status-pill) {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 2px 7px;
  border-radius: 6px;
}

/* 结构化填空卡片网格 */
:deep(.structured-blanks-grid) {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

:deep(.blank-slot-card) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-radius: 10px;
  transition: all 0.15s ease;
}

:deep(.blank-slot-card:focus-within) {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

:deep(.slot-badge) {
  font-size: 12px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  padding: 3px 8px;
  border-radius: 6px;
  white-space: nowrap;
}

:deep(.blank-slot-input) {
  flex: 1;
  border: none;
  outline: none;
  font-size: 13.5px;
  font-weight: 600;
  color: #0f172a;
  background: transparent;
}

:deep(.blank-slot-input::placeholder) {
  color: #94a3b8;
  font-size: 12.5px;
  font-weight: normal;
}

/* 快捷符号输入栏 */
:deep(.quick-symbol-toolbar) {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

:deep(.symbol-label) {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
}

:deep(.symbol-chips-row) {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

:deep(.symbol-chip-btn) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11.5px;
  font-weight: 700;
  color: #3730a3;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

:deep(.symbol-chip-btn:hover) {
  background: #e0e7ff;
  border-color: #818cf8;
  transform: translateY(-1px);
}

/* 答题多行输入画布 */
:deep(.textarea-wrapper) {
  width: 100%;
}

:deep(.student-textarea-input) {
  width: 100%;
  box-sizing: border-box;
  min-height: 88px;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  background: #ffffff;
  padding: 12px 16px;
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.7;
  color: #0f172a;
  resize: vertical;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

:deep(.student-textarea-input:focus) {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

:deep(.student-textarea-input::placeholder) {
  color: #94a3b8;
  font-size: 13px;
}

/* 打印横线（仅打印） */
:deep(.paper-print-ruled-lines) {
  display: none;
  margin-top: 10px;
}

:deep(.ruled-line) {
  display: block;
  height: 28px;
  border-bottom: 1px dashed #cbd5e1;
}

@media print {
  :deep(.no-print),
  :deep(.quick-symbol-toolbar),
  :deep(.textarea-wrapper) {
    display: none !important;
  }
  :deep(.print-only),
  :deep(.paper-print-ruled-lines) {
    display: block !important;
  }
}

/* 教师讲评 Callout 区域 */
:deep(.fancy-teacher-panel) {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

:deep(.teacher-callout) {
  border-radius: 12px;
  padding: 14px 18px;
  font-size: 13.5px;
  line-height: 1.7;
}

:deep(.answer-callout) {
  background: #ecfdf5;
  border: 1.5px solid #a7f3d0;
  border-left: 4px solid #10b981;
}

:deep(.analysis-callout) {
  background: #f5f3ff;
  border: 1.5px solid #ddd6fe;
  border-left: 4px solid #8b5cf6;
}

:deep(.rubric-callout) {
  background: #eff6ff;
  border: 1.5px solid #bfdbfe;
  border-left: 4px solid #3b82f6;
}

:deep(.warning-callout) {
  background: #fffbeb;
  border: 1.5px solid #fde68a;
  border-left: 4px solid #f59e0b;
}

:deep(.callout-title) {
  margin-bottom: 6px;
}

:deep(.callout-badge) {
  font-size: 11.5px;
  font-weight: 900;
  padding: 3px 9px;
  border-radius: 6px;
}

:deep(.callout-badge.green) { color: #047857; background: #d1fae5; }
:deep(.callout-badge.violet) { color: #6d28d9; background: #ede9fe; }
:deep(.callout-badge.blue) { color: #1d4ed8; background: #dbeafe; }
:deep(.callout-badge.amber) { color: #b45309; background: #fef3c7; }

:deep(.callout-body) {
  margin: 0;
  color: #1e293b;
  font-size: 13.5px;
}

:deep(.answer-body) {
  font-size: 15px;
  font-weight: 800;
  color: #047857;
}

:deep(.rubric-list) {
  margin: 4px 0 0;
  padding-left: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

:deep(.rubric-list li) {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

:deep(.rubric-pts) {
  font-weight: 900;
  color: #1d4ed8;
  background: #dbeafe;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
}

@media (max-width: 768px) {
  .masthead-metrics {
    grid-template-columns: 1fr 1fr;
  }
  :deep(.fancy-options-grid) {
    grid-template-columns: 1fr;
  }
}
</style>
