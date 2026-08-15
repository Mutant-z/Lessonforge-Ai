<script setup lang="ts">
/**
 * 学习任务单 V3 动态目录编辑器：
 * 左侧目录树（增删 / 重命名 / 上移下移 / 提升层级，非拖拽）
 * + 右侧当前章节编辑（标题 / 目的 / Block 增删改）
 * + 目标 / 知识点 / 环节下拉（来自蓝图，不再手填 ID）
 * + 删除章节时必须选择「移动内容」或「删除内容」
 * + 保存前显示字段级验证提示；人工保存继续创建新版本（后端同一 V3 门禁）。
 */
import { computed, ref, watch } from 'vue';
import type {
  TaskSheetBlock,
  TaskSheetContentV3,
  TaskSheetLearningTaskBlock,
  TaskSheetSectionV3,
} from '../../types/artifact';

const props = defineProps<{
  modelValue: TaskSheetContentV3;
  blueprint?: {
    objectives: Array<{ id: string; statement: string; criterion?: string }>;
    knowledge_points: Array<{ id: string; name: string }>;
    stages: Array<{ id: string; name: string; duration_minutes?: number }>;
  } | null;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: TaskSheetContentV3): void;
  (e: 'save'): void;
  (e: 'cancel'): void;
}>();

const selectedSectionId = ref<string>('');
const renameDraft = ref<Record<string, string>>({});
const newBlockKind = ref<'text' | 'learning_task' | 'record_table' | 'question_set' | 'assessment' | 'checklist' | 'objective_list'>('text');
const deleteDialog = ref<{ open: boolean; target: string; mode: 'move' | 'delete'; moveTo: string }>({
  open: false, target: '', mode: 'delete', moveTo: '',
});

const content = computed({
  get: () => props.modelValue,
  set: (value: TaskSheetContentV3) => emit('update:modelValue', value),
});

/** 深度优先有序章节（含 depth） */
const orderedSections = computed(() => {
  if (!content.value.sections) return [];
  const sections = content.value.sections;
  const depthMap: Record<string, number> = {};
  for (const section of sections) depthMap[section.id] = section.parent_id ? (depthMap[section.parent_id] || 0) + 1 : 0;
  return [...sections]
    .sort((a, b) => `${a.parent_id || ''}:${a.order}`.localeCompare(`${b.parent_id || ''}:${b.order}`, undefined, { numeric: true }))
    .map(section => ({ ...section, depth: depthMap[section.id] || 0 }));
});

const selectedSection = computed(() =>
  content.value.sections.find(section => section.id === selectedSectionId.value) || null,
);

const objectiveOptions = computed(() =>
  (props.blueprint?.objectives || []).map(item => ({ id: item.id, label: `${item.id} · ${item.statement}` })),
);
const knowledgeOptions = computed(() =>
  (props.blueprint?.knowledge_points || []).map(item => ({ id: item.id, label: `${item.id} · ${item.name}` })),
);
const stageOptions = computed(() =>
  (props.blueprint?.stages || []).map(item => ({ id: item.id, label: `${item.id} · ${item.name}` })),
);

function newSectionId(): string {
  let index = 1;
  while (content.value.sections.some(section => section.id === `SEC-EDIT${index}`)) index += 1;
  return `SEC-EDIT${index}`;
}

function newBlockId(kind: string): string {
  const prefix = { text: 'B', learning_task: 'T', record_table: 'RT', question_set: 'Q', assessment: 'SA', checklist: 'CK', objective_list: 'OBJ' }[kind] || 'B';
  let index = 1;
  while (content.value.sections.some(section => section.blocks.some(block => block.id === `${prefix}-${index}`))) index += 1;
  return `${prefix}-${index}`;
}

function addSection(parentId: string) {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const siblings = next.sections.filter(section => (section.parent_id || '') === (parentId || ''));
  const order = siblings.length;
  next.sections.push({ id: newSectionId(), parent_id: parentId, order, title: '新章节', purpose: '', objective_ids: [], blocks: [] });
  content.value = next;
  selectedSectionId.value = next.sections[next.sections.length - 1].id;
}

function renameSection(sectionId: string) {
  const title = (renameDraft.value[sectionId] || '').trim();
  if (!title) return;
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const section = next.sections.find(item => item.id === sectionId);
  if (section) section.title = title;
  delete renameDraft.value[sectionId];
  content.value = next;
}

function moveSection(sectionId: string, direction: -1 | 1) {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const sections = next.sections;
  const section = sections.find(item => item.id === sectionId);
  if (!section) return;
  const siblings = sections
    .filter(item => (item.parent_id || '') === (section.parent_id || ''))
    .sort((a, b) => a.order - b.order);
  const index = siblings.findIndex(item => item.id === sectionId);
  const target = index + direction;
  if (target < 0 || target >= siblings.length) return;
  const swap = siblings[target];
  const sectionOrder = section.order;
  section.order = swap.order;
  swap.order = sectionOrder;
  content.value = next;
}

function promoteSection(sectionId: string) {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const section = next.sections.find(item => item.id === sectionId);
  if (!section || !section.parent_id) return;
  const parent = next.sections.find(item => item.id === section.parent_id);
  if (!parent) return;
  const siblings = next.sections
    .filter(item => (item.parent_id || '') === (parent.parent_id || ''))
    .sort((a, b) => a.order - b.order);
  section.parent_id = parent.parent_id || '';
  section.order = siblings.length;
  content.value = next;
}

function indentSection(sectionId: string) {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const sections = next.sections;
  const section = sections.find(item => item.id === sectionId);
  if (!section) return;
  const siblings = sections
    .filter(item => (item.parent_id || '') === (section.parent_id || ''))
    .sort((a, b) => a.order - b.order);
  const index = siblings.findIndex(item => item.id === sectionId);
  const targetParent = index > 0 ? siblings[index - 1] : null;
  if (!targetParent) return;
  if (sections.some(item => item.parent_id === targetParent.id)) return; // 最多 3 层
  section.parent_id = targetParent.id;
  section.order = sections.filter(item => item.parent_id === targetParent.id).length;
  content.value = next;
}

function openDeleteDialog(sectionId: string) {
  deleteDialog.value = { open: true, target: sectionId, mode: 'delete', moveTo: '' };
}

function confirmDelete() {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const { target, mode, moveTo } = deleteDialog.value;
  const section = next.sections.find(item => item.id === target);
  if (!section) { deleteDialog.value.open = false; return; }
  const descendantIds = new Set<string>([target]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const item of next.sections) {
      if (item.parent_id && descendantIds.has(item.parent_id) && !descendantIds.has(item.id)) {
        descendantIds.add(item.id);
        changed = true;
      }
    }
  }
  const removedBlocks = section.blocks;
  if (mode === 'move' && moveTo && next.sections.some(item => item.id === moveTo)) {
    const targetSection = next.sections.find(item => item.id === moveTo)!;
    targetSection.blocks.push(...removedBlocks);
  }
  next.sections = next.sections.filter(item => !descendantIds.has(item.id));
  // 重新排序同级
  const parentId = section.parent_id || '';
  const siblings = next.sections.filter(item => (item.parent_id || '') === parentId).sort((a, b) => a.order - b.order);
  siblings.forEach((item, index) => { item.order = index; });
  content.value = next;
  if (selectedSectionId.value === target) selectedSectionId.value = '';
  deleteDialog.value.open = false;
}

function addBlock(kind: string) {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const section = next.sections.find(item => item.id === selectedSectionId.value);
  if (!section) return;
  const blockId = newBlockId(kind);
  let block: TaskSheetBlock;
  if (kind === 'learning_task') {
    block = {
      kind, id: blockId, title: '新任务', action: '', object: '', steps: [''],
      student_output: '', completion_criterion: '', estimated_minutes: 1,
      collaboration_mode: 'individual', objective_ids: [], knowledge_point_ids: [], stage_id: null,
      scaffolds: [], record_table: null,
    } as TaskSheetLearningTaskBlock;
  } else if (kind === 'objective_list') {
    block = { kind, id: blockId, title: '学习目标', objective_ids: (objectiveOptions.value[0] ? [objectiveOptions.value[0].id] : []) } as TaskSheetBlock;
  } else if (kind === 'record_table') {
    block = { kind, id: blockId, title: '记录表', instructions: '', columns: ['观察项', '记录'], blank_rows: 3 } as TaskSheetBlock;
  } else if (kind === 'question_set') {
    block = { kind, id: blockId, title: '课堂问题', questions: [{ id: `${blockId}-Q1`, prompt: '', objective_ids: [], stage_id: null }] } as TaskSheetBlock;
  } else if (kind === 'assessment') {
    block = { kind, id: blockId, title: '学习成效自我评价', scale: ['尚未做到', '基本做到', '能够做到'], items: [{ id: `${blockId}-A1`, statement: '', objective_ids: [] }] } as TaskSheetBlock;
  } else if (kind === 'checklist') {
    block = { kind, id: blockId, title: '检查表', items: [{ text: '' }] } as TaskSheetBlock;
  } else {
    block = { kind: 'text', id: blockId, text: '' } as TaskSheetBlock;
  }
  section.blocks.push(block);
  content.value = next;
}

function removeBlock(blockId: string) {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const section = next.sections.find(item => item.id === selectedSectionId.value);
  if (!section) return;
  section.blocks = section.blocks.filter(block => block.id !== blockId);
  content.value = next;
}

function patchBlock(blockId: string, patch: Record<string, unknown>) {
  const next = JSON.parse(JSON.stringify(content.value)) as TaskSheetContentV3;
  const section = next.sections.find(item => item.id === selectedSectionId.value);
  if (!section) return;
  const block = section.blocks.find(item => item.id === blockId);
  if (!block) return;
  Object.assign(block, patch);
  content.value = next;
}

/** 保存前字段级验证提示 */
const validationNotes = computed(() => {
  const notes: string[] = [];
  if (!content.value.sections.length) notes.push('目录为空，请至少保留一个章节');
  if (!content.value.sections.some(section => section.blocks.some(block => block.kind === 'objective_list'))) {
    notes.push('缺少「目标列表」Block（必备语义要素）');
  }
  if (!content.value.sections.some(section => section.blocks.some(block => block.kind === 'learning_task'))) {
    notes.push('缺少「学习任务」Block（必备语义要素）');
  }
  if (!content.value.sections.some(section => section.blocks.some(block => block.kind === 'record_table' || (block.kind === 'learning_task' && block.record_table)))) {
    notes.push('缺少「记录表」Block（必备语义要素）');
  }
  if (!content.value.sections.some(section => section.blocks.some(block => block.kind === 'assessment'))) {
    notes.push('缺少「学生评价」Block（必备语义要素）');
  }
  const uncovered = new Set((content.value.objective_catalog || []).map(item => item.id));
  for (const section of content.value.sections) {
    for (const block of section.blocks) {
      if (block.kind === 'learning_task') {
        for (const objectiveId of block.objective_ids) uncovered.delete(objectiveId);
      }
    }
  }
  if (uncovered.size) notes.push(`以下目标未被任何任务覆盖：${[...uncovered].join('、')}`);
  return notes;
});

function save() {
  if (validationNotes.value.length) return; // 前端拦截；后端仍执行同一门禁
  emit('save');
}
</script>

<template>
  <div class="ts-outline-editor">
    <!-- 左侧：目录树 -->
    <aside class="ts-tree-pane">
      <header class="ts-tree-head">
        <strong>目录</strong>
        <button type="button" class="ts-add-root" title="新增顶级章节" @click="addSection('')">＋ 章节</button>
      </header>
      <div class="ts-tree-scroll">
        <div v-for="section in orderedSections" :key="section.id" class="ts-tree-row" :style="{ paddingLeft: `${section.depth * 16}px` }">
          <div
            class="ts-tree-item"
            :class="{ active: section.id === selectedSectionId }"
            @click="selectedSectionId = section.id"
          >
            <input
              v-if="renameDraft[section.id] !== undefined"
              v-model="renameDraft[section.id]"
              class="ts-rename-input"
              @keydown.enter="renameSection(section.id)"
              @blur="renameSection(section.id)"
              @click.stop
            />
            <template v-else>
              <span class="ts-tree-title">{{ section.title }}</span>
              <span class="ts-tree-count">{{ section.blocks.length }}</span>
            </template>
          </div>
          <div class="ts-tree-actions" @click.stop>
            <button title="重命名" @click="renameDraft[section.id] = section.title">✎</button>
            <button title="上移" @click="moveSection(section.id, -1)">↑</button>
            <button title="下移" @click="moveSection(section.id, 1)">↓</button>
            <button title="提升层级" @click="promoteSection(section.id)">⇤</button>
            <button title="缩进为子章节" @click="indentSection(section.id)">⇥</button>
            <button title="删除章节" class="ts-danger" @click="openDeleteDialog(section.id)">✕</button>
          </div>
        </div>
      </div>
    </aside>

    <!-- 右侧：章节编辑 -->
    <main class="ts-edit-pane">
      <template v-if="selectedSection">
        <header class="ts-section-edit-head">
          <h3>章节：{{ selectedSection.title }}</h3>
          <button type="button" class="ts-save-btn" :disabled="validationNotes.length > 0" @click="save">保存新版本</button>
        </header>

        <div class="ts-field">
          <label>章节标题</label>
          <input v-model="selectedSection.title" type="text" />
        </div>
        <div class="ts-field">
          <label>章节目的</label>
          <textarea v-model="selectedSection.purpose" rows="2" />
        </div>

        <!-- Block 列表 -->
        <section class="ts-block-editor">
          <header class="ts-block-editor-head">
            <strong>内容块（{{ selectedSection.blocks.length }}）</strong>
            <div class="ts-add-block">
              <select v-model="newBlockKind">
                <option value="text">文本</option>
                <option value="objective_list">目标列表</option>
                <option value="learning_task">学习任务</option>
                <option value="record_table">记录表</option>
                <option value="question_set">问题</option>
                <option value="assessment">评价</option>
                <option value="checklist">检查表</option>
              </select>
              <button type="button" @click="addBlock(newBlockKind)">＋ 添加</button>
            </div>
          </header>

          <div v-for="block in selectedSection.blocks" :key="block.id" class="ts-block-card">
            <header class="ts-block-card-head">
              <strong>{{ block.id }}</strong>
              <span class="ts-block-kind">{{ block.kind }}</span>
              <button type="button" class="ts-danger" title="删除内容块" @click="removeBlock(block.id)">✕</button>
            </header>

            <!-- text -->
            <div v-if="block.kind === 'text'" class="ts-field">
              <label>正文</label>
              <textarea v-model="block.text" rows="3" />
            </div>

            <!-- objective_list -->
            <div v-else-if="block.kind === 'objective_list'" class="ts-field">
              <label>目标列表</label>
              <div v-for="objectiveId in block.objective_ids" :key="objectiveId" class="ts-pick-row">
                <input type="checkbox" :checked="true" disabled />
                <span>{{ objectiveId }}</span>
                <button type="button" title="移除" @click="block.objective_ids = block.objective_ids.filter(id => id !== objectiveId)">✕</button>
              </div>
              <select
                v-if="objectiveOptions.length"
                :value="''"
                @change="patchBlock(block.id, { objective_ids: [...block.objective_ids, ($event.target as HTMLSelectElement).value] })"
              >
                <option value="">＋ 选择目标…</option>
                <option v-for="option in objectiveOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
              </select>
            </div>

            <!-- learning_task -->
            <div v-else-if="block.kind === 'learning_task'" class="ts-task-form">
              <div class="ts-field">
                <label>任务标题</label>
                <input v-model="block.title" type="text" />
              </div>
              <div class="ts-field">
                <label>学习动作</label>
                <input v-model="block.action" type="text" />
              </div>
              <div class="ts-field">
                <label>操作对象</label>
                <input v-model="block.object" type="text" />
              </div>
              <div class="ts-field">
                <label>预计用时（分钟）</label>
                <input v-model.number="block.estimated_minutes" type="number" min="0.5" step="0.5" />
              </div>
              <div class="ts-field">
                <label>协作方式</label>
                <select v-model="block.collaboration_mode">
                  <option value="individual">独立</option>
                  <option value="pair">结对</option>
                  <option value="group">小组</option>
                  <option value="whole_class">全班</option>
                </select>
              </div>
              <div class="ts-field">
                <label>教学环节（stage_id）</label>
                <select v-model="block.stage_id">
                  <option :value="null">— 不映射 —</option>
                  <option v-for="option in stageOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
                </select>
              </div>
              <div class="ts-field">
                <label>对应目标</label>
                <div class="ts-pick-list">
                  <span v-for="objectiveId in block.objective_ids" :key="objectiveId" class="ts-pick-chip">
                    {{ objectiveId }}
                    <button type="button" @click="block.objective_ids = block.objective_ids.filter(id => id !== objectiveId)">✕</button>
                  </span>
                </div>
                <select
                  v-if="objectiveOptions.length"
                  :value="''"
                  @change="patchBlock(block.id, { objective_ids: [...block.objective_ids, ($event.target as HTMLSelectElement).value] })"
                >
                  <option value="">＋ 选择目标…</option>
                  <option v-for="option in objectiveOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
                </select>
              </div>
              <div class="ts-field">
                <label>对应知识点</label>
                <div class="ts-pick-list">
                  <span v-for="knowledgeId in block.knowledge_point_ids" :key="knowledgeId" class="ts-pick-chip">
                    {{ knowledgeId }}
                    <button type="button" @click="block.knowledge_point_ids = block.knowledge_point_ids.filter(id => id !== knowledgeId)">✕</button>
                  </span>
                </div>
                <select
                  v-if="knowledgeOptions.length"
                  :value="''"
                  @change="patchBlock(block.id, { knowledge_point_ids: [...block.knowledge_point_ids, ($event.target as HTMLSelectElement).value] })"
                >
                  <option value="">＋ 选择知识点…</option>
                  <option v-for="option in knowledgeOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
                </select>
              </div>
              <div class="ts-field">
                <label>操作步骤</label>
                <div v-for="(step, index) in block.steps" :key="index" class="ts-step-row">
                  <input v-model="block.steps[index]" type="text" />
                  <button type="button" @click="block.steps.splice(index, 1)">✕</button>
                </div>
                <button type="button" class="ts-add-row" @click="block.steps.push('')">＋ 步骤</button>
              </div>
              <div class="ts-field">
                <label>成果要求</label>
                <textarea v-model="block.student_output" rows="2" />
              </div>
              <div class="ts-field">
                <label>完成标准</label>
                <textarea v-model="block.completion_criterion" rows="2" />
              </div>
              <div class="ts-field">
                <label>思考支架</label>
                <div v-for="(scaffold, index) in block.scaffolds" :key="index" class="ts-step-row">
                  <input v-model="block.scaffolds[index]" type="text" />
                  <button type="button" @click="block.scaffolds.splice(index, 1)">✕</button>
                </div>
                <button type="button" class="ts-add-row" @click="block.scaffolds.push('')">＋ 支架</button>
              </div>
            </div>

            <!-- record_table -->
            <div v-else-if="block.kind === 'record_table'" class="ts-table-form">
              <div class="ts-field">
                <label>表标题</label>
                <input v-model="block.title" type="text" />
              </div>
              <div class="ts-field">
                <label>填写说明</label>
                <textarea v-model="block.instructions" rows="2" />
              </div>
              <div class="ts-field">
                <label>列</label>
                <div v-for="(column, index) in block.columns" :key="index" class="ts-step-row">
                  <input v-model="block.columns[index]" type="text" />
                  <button type="button" @click="block.columns.splice(index, 1)">✕</button>
                </div>
                <button type="button" class="ts-add-row" @click="block.columns.push('')">＋ 列</button>
              </div>
              <div class="ts-field">
                <label>空白行数</label>
                <input v-model.number="block.blank_rows" type="number" min="1" max="12" />
              </div>
            </div>

            <!-- question_set -->
            <div v-else-if="block.kind === 'question_set'" class="ts-questions-form">
              <div v-for="question in block.questions" :key="question.id" class="ts-field">
                <label>{{ question.id }}</label>
                <textarea v-model="question.prompt" rows="2" />
              </div>
              <button type="button" class="ts-add-row" @click="block.questions.push({ id: `${block.id}-Q${block.questions.length + 1}`, prompt: '', objective_ids: [], stage_id: null })">＋ 问题</button>
            </div>

            <!-- assessment -->
            <div v-else-if="block.kind === 'assessment'" class="ts-assessment-form">
              <div class="ts-field">
                <label>评价档位（/ 分隔）</label>
                <input
                  type="text"
                  :value="block.scale.join(' / ')"
                  @change="block.scale = ($event.target as HTMLInputElement).value.split('/').map(item => item.trim()).filter(Boolean)"
                />
              </div>
              <div v-for="item in block.items" :key="item.id" class="ts-field">
                <label>{{ item.id }} · 评价条目</label>
                <textarea v-model="item.statement" rows="2" />
              </div>
              <button type="button" class="ts-add-row" @click="block.items.push({ id: `${block.id}-A${block.items.length + 1}`, statement: '', objective_ids: [] })">＋ 条目</button>
            </div>

            <!-- checklist -->
            <div v-else-if="block.kind === 'checklist'" class="ts-checklist-form">
              <div v-for="(item, index) in block.items" :key="`${item.text}-${index}`" class="ts-step-row">
                <input v-model="block.items[index].text" type="text" />
                <button type="button" @click="block.items.splice(index, 1)">✕</button>
              </div>
              <button type="button" class="ts-add-row" @click="block.items.push({ text: '' })">＋ 项目</button>
            </div>
          </div>
        </section>
      </template>

      <div v-else class="ts-no-selection">
        <p>从左侧选择一个章节开始编辑，或「＋ 章节」新增顶级章节。</p>
      </div>

      <!-- 验证提示 -->
      <div v-if="validationNotes.length" class="ts-validation">
        <strong>保存前请解决以下问题（后端会执行同一门禁）：</strong>
        <ul>
          <li v-for="note in validationNotes" :key="note">{{ note }}</li>
        </ul>
      </div>
    </main>

    <!-- 删除确认对话框 -->
    <div v-if="deleteDialog.open" class="ts-dialog-mask" @click.self="deleteDialog.open = false">
      <div class="ts-dialog">
        <h4>删除章节</h4>
        <p>该章节下的内容块如何处理？</p>
        <label class="ts-dialog-option">
          <input type="radio" v-model="deleteDialog.mode" value="delete" />
          按指令删除内容（不保留这些内容块）
        </label>
        <label class="ts-dialog-option">
          <input type="radio" v-model="deleteDialog.mode" value="move" />
          将内容移动到其他章节
        </label>
        <select v-if="deleteDialog.mode === 'move'" v-model="deleteDialog.moveTo" class="ts-dialog-select">
          <option value="">选择目标章节…</option>
          <option
            v-for="section in orderedSections.filter(item => item.id !== deleteDialog.target)"
            :key="section.id"
            :value="section.id"
          >{{ '　'.repeat(section.depth) }}{{ section.title }}</option>
        </select>
        <div class="ts-dialog-actions">
          <button type="button" @click="deleteDialog.open = false">取消</button>
          <button
            type="button"
            class="ts-danger"
            :disabled="deleteDialog.mode === 'move' && !deleteDialog.moveTo"
            @click="confirmDelete"
          >确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ts-outline-editor {
  display: flex;
  height: 100%;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
}
.ts-tree-pane {
  width: 280px;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.ts-tree-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f0f0;
}
.ts-add-root {
  background: #eef2ff;
  border: none;
  color: #4f46e5;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 8px;
  cursor: pointer;
}
.ts-tree-scroll { flex: 1; overflow-y: auto; padding: 8px; }
.ts-tree-row { display: flex; align-items: center; gap: 4px; }
.ts-tree-item {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.ts-tree-item:hover { background: #f3f4f6; }
.ts-tree-item.active { background: #eef2ff; color: #4f46e5; }
.ts-tree-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ts-tree-count { font-size: 10px; color: #9ca3af; }
.ts-rename-input { width: 100%; font-size: 12px; border: 1px solid #6366f1; border-radius: 4px; padding: 2px 4px; }
.ts-tree-actions { display: none; gap: 2px; }
.ts-tree-row:hover .ts-tree-actions { display: flex; }
.ts-tree-actions button {
  background: none;
  border: none;
  font-size: 11px;
  color: #6b7280;
  cursor: pointer;
  padding: 2px 4px;
}
.ts-tree-actions button.ts-danger { color: #ef4444; }
.ts-edit-pane { flex: 1; overflow-y: auto; padding: 14px 18px; }
.ts-section-edit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.ts-section-edit-head h3 { margin: 0; font-size: 16px; }
.ts-save-btn {
  background: #4f46e5;
  color: #fff;
  border: none;
  padding: 6px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.ts-save-btn:disabled { background: #c7d2fe; cursor: not-allowed; }
.ts-field { margin-bottom: 10px; }
.ts-field label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 4px; }
.ts-field input[type='text'], .ts-field input[type='number'], .ts-field textarea, .ts-field select, .ts-dialog-select {
  width: 100%;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  box-sizing: border-box;
}
.ts-field textarea { resize: vertical; }
.ts-block-editor { margin-top: 16px; }
.ts-block-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.ts-add-block { display: flex; gap: 6px; }
.ts-add-block select { font-size: 12px; border: 1px solid #d1d5db; border-radius: 6px; padding: 4px; }
.ts-add-block button {
  background: #4f46e5;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.ts-block-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 10px;
}
.ts-block-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.ts-block-card-head strong { font-size: 12px; color: #4f46e5; }
.ts-block-kind {
  font-size: 10px;
  color: #059669;
  background: #ecfdf5;
  padding: 1px 6px;
  border-radius: 6px;
}
.ts-block-card-head .ts-danger { margin-left: auto; }
.ts-danger { background: none; border: none; color: #ef4444; cursor: pointer; font-size: 13px; }
.ts-step-row { display: flex; gap: 6px; margin-bottom: 4px; }
.ts-step-row input { flex: 1; border: 1px solid #d1d5db; border-radius: 6px; padding: 5px 8px; font-size: 13px; }
.ts-add-row {
  background: #f3f4f6;
  border: 1px dashed #d1d5db;
  color: #6b7280;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  margin-top: 4px;
}
.ts-pick-list { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.ts-pick-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #eef2ff;
  color: #4f46e5;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
}
.ts-pick-chip button { background: none; border: none; color: #4f46e5; cursor: pointer; font-size: 11px; }
.ts-pick-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 13px; }
.ts-pick-row button { margin-left: auto; }
.ts-validation {
  margin-top: 16px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  color: #92400e;
}
.ts-validation ul { margin: 6px 0 0; padding-left: 18px; }
.ts-no-selection { color: #9ca3af; text-align: center; padding: 60px 20px; }
.ts-dialog-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 40;
}
.ts-dialog {
  background: #fff;
  border-radius: 12px;
  padding: 18px;
  width: 360px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ts-dialog h4 { margin: 0; }
.ts-dialog-option { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.ts-dialog-select { width: 100%; }
.ts-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.ts-dialog-actions button {
  border: 1px solid #d1d5db;
  background: #fff;
  border-radius: 6px;
  padding: 5px 12px;
  cursor: pointer;
  font-size: 13px;
}
.ts-dialog-actions .ts-danger { border-color: #fecaca; color: #dc2626; }
.ts-dialog-actions .ts-danger:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
