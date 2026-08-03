<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue';
import type { TaskRecordTable, TaskSheetContent, TaskSheetTask } from '../../types';

const model = defineModel<TaskSheetContent>({ required: true });

function splitLines(value: string): string[] {
  return value.split('\n').map(item => item.trim()).filter(Boolean);
}

function splitRefs(value: string): string[] {
  return value.split(/[、,\s]+/).map(item => item.trim()).filter(Boolean);
}

function nextId(prefix: string, values: Array<{ id: string }>): string {
  const used = new Set(values.map(item => item.id));
  let index = values.length + 1;
  while (used.has(`${prefix}-${String(index).padStart(2, '0')}`)) index += 1;
  return `${prefix}-${String(index).padStart(2, '0')}`;
}

function addTask() {
  const firstObjective = model.value.learning_objectives[0]?.id || 'OBJ-01';
  const firstKnowledge = model.value.tasks[0]?.knowledge_point_ids[0] || 'KP-01';
  model.value.tasks.push({
    id: nextId('T', model.value.tasks), title: '新学习任务', phase: 'in_class', stage_id: null,
    objective_ids: [firstObjective], knowledge_point_ids: [firstKnowledge], action: '完成', object: '指定学习对象',
    steps: ['阅读任务要求', '按步骤完成并记录'], student_output: '一份可检查的学习成果',
    completion_criterion: '内容完整且符合任务要求', estimated_minutes: 3,
    collaboration_mode: 'individual', scaffolds: [], record_table: null,
  });
}

function addRecordTable(task: TaskSheetTask) {
  task.record_table = { title: '学习记录表', instructions: '按列填写学习过程和结果。', columns: ['记录项', '我的内容'], blank_rows: 3 };
}

function addGlobalRecordTable() {
  model.value.record_table = {
    title: '学习记录表', instructions: '按列填写学习过程和结果。',
    columns: ['任务', '我的记录', '检查结果'], blank_rows: 4,
  };
}

function updateRecordColumns(table: TaskRecordTable, value: string) {
  table.columns = splitRefs(value);
}

function addQuestion() {
  model.value.learning_questions.push({
    id: nextId('LQ', model.value.learning_questions), prompt: '请输入课堂问题',
    objective_ids: [model.value.learning_objectives[0]?.id || 'OBJ-01'],
    stage_id: model.value.tasks.find(task => task.phase === 'in_class' && task.stage_id)?.stage_id || '',
  });
}

function addAssessment() {
  model.value.self_assessment.push({
    id: nextId('SA', model.value.self_assessment), statement: '我能按照要求完成学习任务',
    objective_ids: [model.value.learning_objectives[0]?.id || 'OBJ-01'],
  });
}
</script>

<template>
  <div class="task-sheet-editor">
    <section>
      <header><span>01</span><h3>课程信息</h3></header>
      <div class="field-grid four">
        <label><span>课程名称</span><el-input v-model="model.course_info.course_title" /></label>
        <label><span>学科</span><el-input v-model="model.course_info.subject" /></label>
        <label><span>年级</span><el-input v-model="model.course_info.grade_level" /></label>
        <label><span>时长（分钟）</span><el-input-number v-model="model.course_info.duration_minutes" :min="1" /></label>
      </div>
    </section>

    <section>
      <header><span>02</span><h3>学习目标</h3></header>
      <div v-for="objective in model.learning_objectives" :key="objective.id" class="editor-card objective-card">
        <b>{{ objective.id }}</b>
        <el-input v-model="objective.statement" placeholder="学生可理解的目标描述" />
        <el-input v-model="objective.success_criterion" placeholder="可验收的达成标准" />
      </div>
    </section>

    <section>
      <header><span>03</span><h3>课前准备</h3></header>
      <el-input :model-value="model.preparation.join('\n')" type="textarea" :rows="3" placeholder="每行一项" @input="model.preparation = splitLines(String($event))" />
    </section>

    <section>
      <header><span>04</span><h3>学习任务</h3><el-button :icon="Plus" size="small" @click="addTask">添加任务</el-button></header>
      <article v-for="(task, taskIndex) in model.tasks" :key="task.id" class="editor-card task-editor-card">
        <div class="card-title-row"><b>{{ task.id }}</b><el-input v-model="task.title" /><el-button :icon="Delete" text type="danger" :disabled="model.tasks.length === 1" @click="model.tasks.splice(taskIndex, 1)" /></div>
        <div class="field-grid four">
          <label><span>阶段</span><el-select v-model="task.phase"><el-option label="课前" value="pre_class" /><el-option label="课中" value="in_class" /><el-option label="课后" value="after_class" /></el-select></label>
          <label><span>蓝图环节 ID</span><el-input v-model="task.stage_id" placeholder="ACT-01" /></label>
          <label><span>预计用时</span><el-input-number v-model="task.estimated_minutes" :min="0.5" :step="0.5" /></label>
          <label><span>协作方式</span><el-select v-model="task.collaboration_mode"><el-option label="独立" value="individual" /><el-option label="结对" value="pair" /><el-option label="小组" value="group" /><el-option label="全班" value="whole_class" /></el-select></label>
        </div>
        <div class="field-grid two">
          <label><span>目标 ID（顿号分隔）</span><el-input :model-value="task.objective_ids.join('、')" @input="task.objective_ids = splitRefs(String($event))" /></label>
          <label><span>知识点 ID（顿号分隔）</span><el-input :model-value="task.knowledge_point_ids.join('、')" @input="task.knowledge_point_ids = splitRefs(String($event))" /></label>
          <label><span>学习动作</span><el-input v-model="task.action" /></label>
          <label><span>操作对象</span><el-input v-model="task.object" /></label>
        </div>
        <label class="block-field"><span>操作步骤（每行一步）</span><el-input :model-value="task.steps.join('\n')" type="textarea" :rows="4" @input="task.steps = splitLines(String($event))" /></label>
        <div class="field-grid two">
          <label><span>成果要求</span><el-input v-model="task.student_output" type="textarea" :rows="2" /></label>
          <label><span>完成标准</span><el-input v-model="task.completion_criterion" type="textarea" :rows="2" /></label>
        </div>
        <label class="block-field"><span>思考支架（每行一项）</span><el-input :model-value="task.scaffolds.join('\n')" type="textarea" :rows="2" @input="task.scaffolds = splitLines(String($event))" /></label>
        <div v-if="task.record_table" class="record-editor">
          <div class="card-title-row"><b>记录表</b><el-input v-model="task.record_table.title" /><el-button :icon="Delete" text type="danger" @click="task.record_table = null" /></div>
          <el-input v-model="task.record_table.instructions" placeholder="填写说明" />
          <div class="field-grid two">
            <label><span>列名（顿号分隔）</span><el-input :model-value="task.record_table.columns.join('、')" @input="updateRecordColumns(task.record_table!, String($event))" /></label>
            <label><span>空白行数</span><el-input-number v-model="task.record_table.blank_rows" :min="1" :max="12" /></label>
          </div>
        </div>
        <el-button v-else :icon="Plus" size="small" @click="addRecordTable(task)">增加记录表</el-button>
      </article>
    </section>

    <section>
      <header><span>05</span><h3>综合记录表</h3><el-button v-if="!model.record_table" :icon="Plus" size="small" @click="addGlobalRecordTable">添加记录表</el-button></header>
      <div v-if="model.record_table" class="record-editor">
        <div class="card-title-row"><b>记录表</b><el-input v-model="model.record_table.title" /><el-button :icon="Delete" text type="danger" @click="model.record_table = null" /></div>
        <el-input v-model="model.record_table.instructions" placeholder="填写说明" />
        <div class="field-grid two">
          <label><span>列名（顿号分隔）</span><el-input :model-value="model.record_table.columns.join('、')" @input="updateRecordColumns(model.record_table!, String($event))" /></label>
          <label><span>空白行数</span><el-input-number v-model="model.record_table.blank_rows" :min="1" :max="12" /></label>
        </div>
      </div>
      <p v-else class="empty-hint">至少保留一处综合记录表或任务内记录表，学生才能直接填写学习证据。</p>
    </section>

    <section>
      <header><span>06</span><h3>课堂问题</h3><el-button :icon="Plus" size="small" @click="addQuestion">添加问题</el-button></header>
      <div v-for="(question, index) in model.learning_questions" :key="question.id" class="editor-card inline-editor-row">
        <b>{{ question.id }}</b><el-input v-model="question.prompt" /><el-input :model-value="question.objective_ids.join('、')" placeholder="目标 ID" @input="question.objective_ids = splitRefs(String($event))" /><el-input v-model="question.stage_id" placeholder="环节 ID" /><el-button :icon="Delete" text type="danger" @click="model.learning_questions.splice(index, 1)" />
      </div>
    </section>

    <section>
      <header><span>07</span><h3>自我评价</h3><el-button :icon="Plus" size="small" @click="addAssessment">添加自评</el-button></header>
      <label class="block-field"><span>评价档位（顿号分隔）</span><el-input :model-value="model.self_assessment_scale.join('、')" @input="model.self_assessment_scale = splitRefs(String($event))" /></label>
      <div v-for="(item, index) in model.self_assessment" :key="item.id" class="editor-card inline-editor-row">
        <b>{{ item.id }}</b><el-input v-model="item.statement" /><el-input :model-value="item.objective_ids.join('、')" placeholder="目标 ID" @input="item.objective_ids = splitRefs(String($event))" /><el-button :icon="Delete" text type="danger" :disabled="model.self_assessment.length === 1" @click="model.self_assessment.splice(index, 1)" />
      </div>
    </section>

    <section>
      <header><span>08</span><h3>课后拓展</h3></header>
      <el-input :model-value="model.extension.join('\n')" type="textarea" :rows="3" placeholder="每行一项" @input="model.extension = splitLines(String($event))" />
    </section>
  </div>
</template>

<style scoped>
.task-sheet-editor { display: grid; gap: 14px; }.task-sheet-editor section { padding: 16px; border: 1px solid #cfd2d9; background: #fff; }.task-sheet-editor section > header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }.task-sheet-editor section > header > span { color: #002fa7; font-size: 20px; font-weight: 800; }.task-sheet-editor h3 { margin: 0 auto 0 0; font-size: 15px; }
.field-grid { display: grid; gap: 10px; }.field-grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }.field-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }.field-grid label, .block-field { display: grid; gap: 5px; }.field-grid label > span, .block-field > span { color: #656a73; font-size: 11px; font-weight: 700; }
.editor-card { padding: 12px; border: 1px solid #cfd2d9; background: #f7f7f8; }.editor-card + .editor-card { margin-top: 10px; }.objective-card { display: grid; grid-template-columns: 70px minmax(0, 1fr) minmax(0, 1fr); gap: 10px; align-items: center; }.objective-card b, .card-title-row b, .inline-editor-row b { color: #002fa7; font-size: 12px; }
.task-editor-card { display: grid; gap: 12px; }.card-title-row { display: grid; grid-template-columns: 70px minmax(0, 1fr) auto; gap: 10px; align-items: center; }.record-editor { padding: 12px; border-left: 3px solid #002fa7; background: #fff; display: grid; gap: 10px; }.inline-editor-row { display: grid; grid-template-columns: 70px minmax(0, 1fr) 160px 120px auto; gap: 10px; align-items: center; }
.empty-hint { margin: 0; color: #656a73; font-size: 12px; }
:deep(.el-input__wrapper), :deep(.el-textarea__inner), :deep(.el-select__wrapper), :deep(.el-input-number) { border-radius: 0 !important; }.el-input-number { width: 100%; }
@media (max-width: 850px) { .field-grid.four, .field-grid.two { grid-template-columns: 1fr 1fr; }.objective-card, .inline-editor-row { grid-template-columns: 60px minmax(0, 1fr); }.objective-card > :last-child, .inline-editor-row > :nth-child(3) { grid-column: 2; } }
@media (max-width: 560px) { .field-grid.four, .field-grid.two { grid-template-columns: 1fr; }.objective-card, .inline-editor-row { grid-template-columns: 1fr; }.objective-card > :last-child, .inline-editor-row > :nth-child(3) { grid-column: auto; } }
</style>
