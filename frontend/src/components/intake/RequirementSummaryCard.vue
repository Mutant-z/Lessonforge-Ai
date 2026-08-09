<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Check, EditPen, InfoFilled, ChatDotSquare } from '@element-plus/icons-vue';
import type { IntakeDraft, IntakeSession } from '../../types';
import RequirementConflictPanel from './RequirementConflictPanel.vue';

const props = defineProps<{ session: IntakeSession; saving?: boolean }>();
const emit = defineEmits<{
  save: [field: string, value: unknown];
  promptField: [label: string];
}>();

const editing = ref('');
const editValue = ref<string | number>('');
const isUpdatingFlash = ref(false);

watch(() => props.session.current_revision, () => {
  isUpdatingFlash.value = true;
  setTimeout(() => {
    isUpdatingFlash.value = false;
  }, 1200);
});

interface FieldDef {
  key: keyof IntakeDraft;
  label: string;
  required?: boolean;
  multiline?: boolean;
}

interface FieldGroup {
  name: string;
  icon?: string;
  fields: FieldDef[];
}

const groups: FieldGroup[] = [
  {
    name: '课程对象与场景',
    fields: [
      { key: 'title', label: '课程名称', required: true },
      { key: 'subject', label: '学科或专业', required: true },
      { key: 'grade_level', label: '学段或年级', required: true },
      { key: 'duration_minutes', label: '课程时长', required: true },
      { key: 'scenario', label: '教学场景', required: true },
    ]
  },
  {
    name: '教师希望达成的教学意图',
    fields: [
      { key: 'audience', label: '授课对象', required: true, multiline: true },
      { key: 'course_task', label: '课程核心任务', required: true, multiline: true },
      { key: 'teaching_objectives', label: '教学目标', multiline: true },
      { key: 'key_points', label: '教学重点', multiline: true },
      { key: 'difficulty_points', label: '教学难点', multiline: true },
    ]
  },
  {
    name: '教学方式与呈现偏好',
    fields: [
      { key: 'teaching_method', label: '教学方式' },
      { key: 'style_requirements', label: '风格要求' },
      { key: 'language', label: '输出语言' },
    ]
  }
];

const totalFieldsCount = 13;
const filledFieldsCount = computed(() => {
  if (!props.session?.draft) return 0;
  return Object.values(props.session.draft).filter(val => val !== undefined && val !== null && val !== '').length;
});

const completionPercentage = computed(() => {
  return Math.min(100, Math.round((filledFieldsCount.value / totalFieldsCount) * 100));
});

const assumptionFields = computed(() => new Set(props.session.assumptions.map(item => item.field)));

function begin(field: keyof IntakeDraft) {
  editing.value = field;
  editValue.value = props.session.draft[field] ?? '';
}

function save(field: keyof IntakeDraft) {
  let value: unknown = editValue.value;
  if (field === 'duration_minutes') value = Number(value);
  emit('save', field, value);
  editing.value = '';
}

function status(field: keyof IntakeDraft) {
  if (props.session.missing_fields.includes(field)) return 'missing';
  if (assumptionFields.value.has(field)) return 'assumption';
  if (props.session.draft[field] !== undefined && props.session.draft[field] !== '') return 'confirmed';
  return 'optional';
}

function promptForField(label: string) {
  emit('promptField', label);
}
</script>

<template>
  <aside class="requirement-card" :class="{ 'flash-update': isUpdatingFlash }">
    <!-- Header with Progress -->
    <header class="card-header">
      <div class="header-main">
        <div class="title-row">
          <span class="revision-tag">v{{ session.current_revision }}</span>
          <h2 class="card-title">Agent 对教学意图的理解</h2>
        </div>
        <span class="header-sub-note">请确认以下理解是否准确，修改后会同步到项目任务</span>
      </div>

      <div class="readiness-wrap">
        <div class="completion-pill">
          <span>意图完整度 {{ completionPercentage }}%</span>
          <div class="mini-progress-bar">
            <div class="progress-fill" :style="{ width: `${completionPercentage}%` }" />
          </div>
        </div>
      </div>
    </header>

    <RequirementConflictPanel :conflicts="session.conflicts" />

    <div class="field-groups-scroll">
      <div v-for="group in groups" :key="group.name" class="group-block">
        <div class="group-title-strip">
          <span class="group-name">{{ group.name }}</span>
        </div>

        <div class="group-fields-grid">
          <div 
            v-for="field in group.fields" 
            :key="field.key" 
            class="field-cell"
            :class="status(field.key)"
          >
            <div class="field-head">
              <div class="label-wrap">
                <span class="field-label">{{ field.label }}</span>
                <span v-if="field.required" class="req-star" title="核心必备项">*</span>
              </div>
              <div class="head-right">
                <span v-if="status(field.key) === 'confirmed'" class="status-chip confirmed">
                  <el-icon><Check /></el-icon> 已理解
                </span>
                <span v-else-if="status(field.key) === 'assumption'" class="status-chip assumption">
                  Agent 判断
                </span>
                <span 
                  v-else-if="status(field.key) === 'missing'" 
                  class="status-chip missing clickable"
                  title="点击在对话中追问"
                  @click="promptForField(field.label)"
                >
                  <el-icon><ChatDotSquare /></el-icon> 待补充
                </span>
                <span v-else class="status-chip optional">可选</span>

                <button type="button" class="edit-btn" :aria-label="`编辑${field.label}`" @click="begin(field.key)">
                  <el-icon><EditPen /></el-icon>
                </button>
              </div>
            </div>

            <!-- Inline Edit Box -->
            <template v-if="editing === field.key">
              <div class="edit-box">
                <el-input v-if="field.multiline" v-model="editValue" type="textarea" :rows="2" />
                <el-input v-else v-model="editValue" :type="field.key === 'duration_minutes' ? 'number' : 'text'" size="small" />
                <div class="edit-actions">
                  <el-button size="small" text @click="editing = ''">取消</el-button>
                  <el-button size="small" type="primary" :icon="Check" :loading="saving" @click="save(field.key)">保存</el-button>
                </div>
              </div>
            </template>

            <!-- Field Value -->
            <div v-else class="field-value-body">
              <p v-if="session.draft[field.key] !== undefined && session.draft[field.key] !== ''" class="field-val">
                {{ session.draft[field.key] }}{{ field.key === 'duration_minutes' ? ' 分钟' : '' }}
              </p>
              <p v-else class="empty-value" @click="status(field.key) === 'missing' && promptForField(field.label)">
                <span class="empty-hint">
                  {{ field.required ? '继续对话补充这一项' : '可在对话中补充偏好' }}
                </span>
              </p>

              <!-- Assumption Reason Pill -->
              <div v-if="assumptionFields.has(field.key)" class="assumption-bar">
                <el-icon><InfoFilled /></el-icon>
                <span>{{ session.assumptions.find(item => item.field === field.key)?.reason }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.requirement-card {
  background: #ffffff;
  border: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  transition: all 300ms cubic-bezier(0.16, 1, 0.3, 1);
}

.requirement-card.flash-update {
  animation: cardFlash 1.2s ease-in-out;
}

@keyframes cardFlash {
  0% { box-shadow: inset 0 0 0 2px #6366f1; }
  100% { box-shadow: inset 0 0 0 0 transparent; }
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  flex-shrink: 0;
}

.header-main {
  display: flex;
  flex-direction: column;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.revision-tag {
  font-size: 11px;
  font-weight: 800;
  color: #4338ca;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 1px 8px;
  border-radius: 999px;
}

.card-title {
  margin: 0;
  font-size: 15.5px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.header-sub-note {
  font-size: 11.5px;
  color: #64748b;
  margin-top: 2px;
  font-weight: 500;
}

.completion-pill {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.completion-pill span {
  font-size: 12px;
  font-weight: 800;
  color: #4f46e5;
}

.mini-progress-bar {
  width: 90px;
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1 0%, #4338ca 100%);
  border-radius: 999px;
  transition: width 400ms cubic-bezier(0.16, 1, 0.3, 1);
}

.field-groups-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.group-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.group-title-strip {
  display: flex;
  align-items: center;
}

.group-name {
  font-size: 12px;
  font-weight: 800;
  color: #334155;
  letter-spacing: 0.02em;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 3px 12px;
  border-radius: 999px;
}

.group-fields-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field-cell {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px 16px;
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
}

.field-cell:hover {
  border-color: #cbd5e1;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
}

.field-cell.confirmed {
  border-left: 4px solid #4f46e5;
  background: #ffffff;
}

.field-cell.assumption {
  border-left: 4px solid #f59e0b;
  background: #fffdf5;
  border-color: #fde68a;
}

.field-cell.missing {
  border: 1.5px dashed #cbd5e1;
  border-left: 4px solid #94a3b8;
  background: #f8fafc;
}

.field-cell.missing:hover {
  border-color: #6366f1;
  background: #f1f5f9;
}

.field-cell.optional {
  border-left: 4px solid #cbd5e1;
}

.field-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.label-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
}

.field-label {
  font-size: 13.5px;
  font-weight: 800;
  color: #0f172a;
}

.req-star {
  color: #4f46e5;
  font-size: 13px;
  font-weight: 900;
}

.head-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-chip {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 9px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.status-chip.confirmed {
  background: #eef2ff;
  color: #4338ca;
  border: 1px solid #c7d2fe;
}

.status-chip.assumption {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
}

.status-chip.missing {
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #ffedd5;
  cursor: pointer;
  transition: all 150ms ease;
}

.status-chip.missing:hover {
  background: #ffedd5;
  color: #9a3412;
}

.status-chip.optional {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

.edit-btn {
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  transition: all 150ms ease;
  display: grid;
  place-items: center;
}

.edit-btn:hover {
  color: #4f46e5;
  background: #eef2ff;
}

.field-value-body {
  min-width: 0;
}

.field-val {
  margin: 2px 0 0;
  color: #1e293b;
  font-size: 13.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  font-weight: 600;
}

.empty-value {
  margin: 2px 0 0;
  cursor: pointer;
}

.empty-hint {
  font-size: 12px;
  color: #94a3b8;
  font-style: italic;
  font-weight: 500;
}

.field-cell.missing .empty-hint {
  color: #64748b;
  font-style: normal;
}

.assumption-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 5px 12px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  color: #b45309;
  font-size: 11.5px;
  font-weight: 600;
}

.edit-box {
  margin-top: 6px;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 6px;
}
</style>


