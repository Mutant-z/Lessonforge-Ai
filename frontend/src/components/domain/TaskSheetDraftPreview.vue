<script setup lang="ts">
/**
 * 学习任务单 V3 预览：支持草稿实时更新或成品文档展示。
 * - mode="navigator"（默认）：左侧目录 + 右侧按需展开的导航模式（运行期草稿）
 * - mode="document"：单列文档模式，顶部卡片 + 完整内容连续滚动（类似教学设计预览）
 * - published=true：成品预览，隐藏草稿标头，展示课程信息题头
 */
import { computed } from 'vue';
import type { TaskSheetContentV3 } from '../../types/artifact';

const props = withDefaults(defineProps<{
  draft: TaskSheetContentV3 | null;
  lastPatch?: Array<Record<string, any>> | null;
  isRunning?: boolean;
  /** 成品预览模式：隐藏草稿标头，展示课程信息题头（默认 false）。 */
  published?: boolean;
  /** 布局模式：navigator=目录导航（默认），document=文档滚动（类似教学设计）。 */
  mode?: 'navigator' | 'document';
}>(), {
  mode: 'navigator',
});

const emit = defineEmits<{
  (e: 'refresh'): void;
}>();

/** 深度优先有序章节（parent_id + order） */
const orderedSections = computed(() => {
  if (!props.draft?.sections) return [];
  const sections = props.draft.sections;
  const depthMap: Record<string, number> = {};
  for (const section of sections) {
    depthMap[section.id] = section.parent_id
      ? (depthMap[section.parent_id] || 0) + 1
      : 0;
  }
  const sorted = [...sections].sort((a, b) => {
    const aKey = `${a.parent_id || ''}:${a.order}`;
    const bKey = `${b.parent_id || ''}:${b.order}`;
    return aKey.localeCompare(bKey, undefined, { numeric: true });
  });
  return sorted.map(section => ({ ...section, depth: depthMap[section.id] || 0 }));
});

const objectiveById = computed(() => {
  const map: Record<string, { statement: string; success_criterion: string }> = {};
  for (const item of props.draft?.objective_catalog || []) map[item.id] = item;
  return map;
});

function objectiveText(id: string): string {
  const item = objectiveById.value[id];
  return item ? `${item.statement}（达成标准：${item.success_criterion}）` : id;
}

function collaborationLabel(mode: string): string {
  return { individual: '独立', pair: '结对', group: '小组', whole_class: '全班' }[mode] || mode;
}

/** 统计语义要素覆盖 */
const coverage = computed(() => {
  let objectiveList = 0;
  let tasks = 0;
  let recordTables = 0;
  let assessments = 0;
  let questions = 0;
  let checklists = 0;
  for (const section of props.draft?.sections || []) {
    for (const block of section.blocks) {
      if (block.kind === 'objective_list') objectiveList += 1;
      else if (block.kind === 'learning_task') {
        tasks += 1;
        if (block.record_table) recordTables += 1;
      } else if (block.kind === 'record_table') recordTables += 1;
      else if (block.kind === 'assessment') assessments += 1;
      else if (block.kind === 'question_set') questions += 1;
      else if (block.kind === 'checklist') checklists += 1;
    }
  }
  return { objectiveList, tasks, recordTables, assessments, questions, checklists };
});

const hasPatchConflict = computed(() => Array.isArray(props.lastPatch) && props.lastPatch.length > 0);

function scrollToSection(sectionId: string) {
  const el = document.getElementById(`ts-draft-${sectionId}`);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
</script>

<template>
  <div class="ts-draft-preview" :class="{ 'ts-published': published }">
    <!-- 成品预览：展示课程信息题头 -->
    <header v-if="published && draft" class="ts-published-head">
      <div class="ts-pub-title">学习任务单 V3</div>
      <div class="ts-pub-meta">
        <span>{{ draft.course_info?.course_title }}</span>
        <span v-if="draft.course_info?.subject || draft.course_info?.grade_level">
          · {{ draft.course_info?.subject }} / {{ draft.course_info?.grade_level || draft.course_info?.audience }}
        </span>
        <span v-if="draft.course_info?.duration_minutes"> · 建议时长：{{ draft.course_info?.duration_minutes }} 分钟</span>
      </div>
    </header>
    <!-- 草稿模式：显示运行状态条 -->
    <header v-else-if="!published" class="ts-draft-head">
      <span class="ts-draft-badge">草稿预览</span>
      <span v-if="isRunning" class="ts-draft-live"><i class="ts-live-dot" /> 实时更新</span>
      <span v-else class="ts-draft-stale">已结束</span>
    </header>

    <div v-if="!draft" class="ts-draft-empty">
      <p>Agent 正在生成任务单草稿…</p>
    </div>

    <template v-else>
      <!-- 文档模式：顶部深色卡片（类似教学设计 STAGE 卡片） -->
      <section v-if="mode === 'document' && draft" class="ts-document-card">
        <div class="ts-card-stage">
          <span class="ts-stage-label">学习任务单</span>
          <span class="ts-stage-badge">V{{ draft.schema_version }}</span>
        </div>
        <h2 class="ts-card-title">{{ draft.course_info?.course_title || '学习任务单' }}</h2>
        <div class="ts-card-meta">
          <div class="ts-meta-chip">
            <span class="ts-meta-label">{{ draft.course_info?.subject }} · {{ draft.course_info?.grade_level }}</span>
          </div>
          <div class="ts-meta-chip">
            <span class="ts-meta-icon">⏱</span>
            <span class="ts-meta-label">微课时长：{{ draft.course_info?.duration_minutes }} 分钟</span>
          </div>
          <div class="ts-meta-chip">
            <span class="ts-meta-label">{{ draft.course_info?.audience }}</span>
          </div>
        </div>
        <div class="ts-card-stats">
          <div class="ts-stat-item">
            <div class="ts-stat-icon">🎯</div>
            <div class="ts-stat-text">
              <div class="ts-stat-label">教学目标</div>
              <div class="ts-stat-value">{{ draft.objective_catalog?.length || 0 }} 维素养目标</div>
            </div>
          </div>
          <div class="ts-stat-item">
            <div class="ts-stat-icon">📝</div>
            <div class="ts-stat-text">
              <div class="ts-stat-label">学习任务</div>
              <div class="ts-stat-value">{{ coverage.tasks }} 个可执行任务</div>
            </div>
          </div>
          <div class="ts-stat-item">
            <div class="ts-stat-icon">📊</div>
            <div class="ts-stat-text">
              <div class="ts-stat-label">记录与评价</div>
              <div class="ts-stat-value">{{ coverage.recordTables }} 张记录表 · {{ coverage.assessments }} 项自评</div>
            </div>
          </div>
        </div>
      </section>

      <!-- 语义覆盖条（文档模式隐藏） -->
      <div v-if="mode !== 'document'" class="ts-draft-coverage">
        <span class="ts-cover-chip" :class="{ ok: coverage.objectiveList > 0 }">目标 {{ coverage.objectiveList }}</span>
        <span class="ts-cover-chip" :class="{ ok: coverage.tasks > 0 }">任务 {{ coverage.tasks }}</span>
        <span class="ts-cover-chip" :class="{ ok: coverage.recordTables > 0 }">记录表 {{ coverage.recordTables }}</span>
        <span class="ts-cover-chip" :class="{ ok: coverage.assessments > 0 }">评价 {{ coverage.assessments }}</span>
        <span class="ts-cover-chip">问题 {{ coverage.questions }}</span>
        <span class="ts-cover-chip">检查表 {{ coverage.checklists }}</span>
      </div>

      <div v-if="hasPatchConflict" class="ts-draft-conflict">
        草稿已通过补丁局部更新；若与当前版本不一致，请
        <button type="button" class="ts-refresh-btn" @click="emit('refresh')">重新加载草稿</button>
      </div>

      <!-- 目录导航（文档模式隐藏） -->
      <nav v-if="mode !== 'document'" class="ts-draft-outline">
        <button
          v-for="section in orderedSections"
          :key="section.id"
          type="button"
          class="ts-outline-item"
          :style="{ paddingLeft: `${8 + section.depth * 14}px` }"
          @click="scrollToSection(section.id)"
        >
          <span class="ts-outline-title">{{ section.title }}</span>
          <span class="ts-outline-count">{{ section.blocks.length }}</span>
        </button>
      </nav>

      <!-- 章节渲染 -->
      <article
        v-for="section in orderedSections"
        :id="`ts-draft-${section.id}`"
        :key="section.id"
        class="ts-draft-section"
        :style="{ marginLeft: `${section.depth * 12}px` }"
      >
        <header class="ts-section-head">
          <h3>{{ section.title }}</h3>
          <p v-if="section.purpose" class="ts-section-purpose">{{ section.purpose }}</p>
        </header>
        <div v-for="block in section.blocks" :key="block.id" class="ts-draft-block">
          <!-- text -->
          <p v-if="block.kind === 'text'" class="ts-block-text">{{ block.text }}</p>

          <!-- objective_list -->
          <section v-else-if="block.kind === 'objective_list'" class="ts-block ts-block-objectives">
            <h4>{{ block.title || '学习目标' }}</h4>
            <ul>
              <li v-for="objectiveId in block.objective_ids" :key="objectiveId">{{ objectiveText(objectiveId) }}</li>
            </ul>
          </section>

          <!-- learning_task -->
          <section v-else-if="block.kind === 'learning_task'" class="ts-block ts-block-task">
            <header class="ts-task-head">
              <h4>{{ block.title }}</h4>
              <span class="ts-task-meta">{{ block.estimated_minutes }} 分钟 · {{ collaborationLabel(block.collaboration_mode) }}</span>
            </header>
            <p class="ts-task-action"><b>动作：</b>{{ block.action }}；<b>对象：</b>{{ block.object }}</p>
            <ol class="ts-task-steps">
              <li v-for="(step, index) in block.steps" :key="index">{{ step }}</li>
            </ol>
            <p><b>成果要求：</b>{{ block.student_output }}</p>
            <p><b>完成标准：</b>{{ block.completion_criterion }}</p>
            <p v-if="block.scaffolds?.length" class="ts-task-scaffolds">
              <b>思考支架：</b>{{ block.scaffolds.join('；') }}
            </p>
            <div v-if="block.record_table" class="ts-record-table">
              <strong>{{ block.record_table.title }}</strong>
              <p>{{ block.record_table.instructions }}</p>
              <table>
                <thead><tr><th v-for="column in block.record_table.columns" :key="column">{{ column }}</th></tr></thead>
                <tbody>
                  <tr v-for="row in block.record_table.blank_rows" :key="row">
                    <td v-for="column in block.record_table.columns" :key="column" />
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- record_table -->
          <section v-else-if="block.kind === 'record_table'" class="ts-block">
            <h4>{{ block.title }}</h4>
            <p>{{ block.instructions }}</p>
            <table>
              <thead><tr><th v-for="column in block.columns" :key="column">{{ column }}</th></tr></thead>
              <tbody>
                <tr v-for="row in block.blank_rows" :key="row">
                  <td v-for="column in block.columns" :key="column" />
                </tr>
              </tbody>
            </table>
          </section>

          <!-- question_set -->
          <section v-else-if="block.kind === 'question_set'" class="ts-block">
            <h4>{{ block.title || '课堂问题' }}</h4>
            <ul class="ts-question-list">
              <li v-for="question in block.questions" :key="question.id">{{ question.prompt }}</li>
            </ul>
          </section>

          <!-- assessment -->
          <section v-else-if="block.kind === 'assessment'" class="ts-block">
            <h4>{{ block.title || '学习成效自我评价' }}（{{ block.scale.join(' / ') }}）</h4>
            <ul>
              <li v-for="item in block.items" :key="item.id">□ {{ item.statement }}</li>
            </ul>
          </section>

          <!-- checklist -->
          <section v-else-if="block.kind === 'checklist'" class="ts-block">
            <h4>{{ block.title || '检查表' }}</h4>
            <ul>
              <li v-for="item in block.items" :key="`${item.text}-${item.text.length}`">□ {{ item.text }}</li>
            </ul>
          </section>
        </div>
      </article>
    </template>
  </div>
</template>

<style scoped>
.ts-draft-preview {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  max-height: 100%;
  overflow-y: auto;
}
.ts-published {
  border: none;
  border-radius: 0;
  padding: 16px 20px;
}
.ts-published-head {
  padding: 0 0 12px;
  border-bottom: 1px solid #e5e7eb;
  margin-bottom: 4px;
}
.ts-pub-title {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
  margin-bottom: 4px;
}
.ts-pub-meta {
  font-size: 13px;
  color: #6b7280;
}
.ts-document-card {
  background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
  border-radius: 16px;
  padding: 24px 28px;
  margin-bottom: 16px;
  color: #ffffff;
}
.ts-card-stage {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.ts-stage-label {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.ts-stage-badge {
  background: rgba(34, 197, 94, 0.2);
  color: #86efac;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 12px;
}
.ts-card-title {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 16px;
  color: #ffffff;
}
.ts-card-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.ts-meta-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 12px;
}
.ts-meta-icon {
  font-size: 14px;
}
.ts-meta-label {
  color: #e2e8f0;
  font-weight: 500;
}
.ts-card-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}
.ts-stat-item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 14px 16px;
  border-radius: 12px;
}
.ts-stat-icon {
  font-size: 24px;
}
.ts-stat-text {
  flex: 1;
}
.ts-stat-label {
  font-size: 11px;
  color: #94a3b8;
  margin-bottom: 2px;
}
.ts-stat-value {
  font-size: 13px;
  font-weight: 600;
  color: #f1f5f9;
}
.ts-draft-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ts-draft-badge {
  font-size: 11px;
  font-weight: 600;
  color: #4f46e5;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 8px;
}
.ts-draft-live { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #10b981; }
.ts-live-dot { width: 6px; height: 6px; border-radius: 50%; background: #10b981; animation: ts-pulse 1s infinite; }
@keyframes ts-pulse { 50% { opacity: 0.3; } }
.ts-draft-stale { font-size: 11px; color: #9ca3af; }
.ts-draft-empty { color: #9ca3af; font-size: 13px; padding: 24px; text-align: center; }
.ts-draft-coverage {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ts-cover-chip {
  font-size: 11px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 2px 8px;
  border-radius: 8px;
}
.ts-cover-chip.ok { color: #059669; background: #ecfdf5; }
.ts-draft-conflict {
  font-size: 12px;
  color: #d97706;
  background: #fffbeb;
  border: 1px solid #fde68a;
  padding: 6px 10px;
  border-radius: 8px;
}
.ts-refresh-btn {
  background: none;
  border: none;
  color: #4f46e5;
  cursor: pointer;
  font-size: 12px;
  text-decoration: underline;
}
.ts-draft-outline {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-bottom: 1px solid #f0f0f0;
  padding-bottom: 8px;
}
.ts-outline-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 12px;
  color: #374151;
  text-align: left;
  padding: 4px 8px;
  border-radius: 6px;
}
.ts-outline-item:hover { background: #f3f4f6; }
.ts-outline-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ts-outline-count { font-size: 10px; color: #9ca3af; }
.ts-draft-section { margin-bottom: 14px; }
.ts-section-head h3 { font-size: 15px; margin: 0 0 4px; color: #111827; }
.ts-section-purpose { font-size: 12px; color: #6b7280; margin: 0 0 8px; }
.ts-draft-block { margin-bottom: 10px; }
.ts-block { border-left: 3px solid #e5e7eb; padding-left: 10px; }
.ts-block-objectives { border-left-color: #6366f1; }
.ts-block-task { border-left-color: #10b981; }
.ts-block h4 { font-size: 13px; margin: 0 0 4px; color: #1f2937; }
.ts-block p, .ts-block li { font-size: 12px; color: #374151; line-height: 1.6; }
.ts-block-text { font-size: 13px; color: #374151; line-height: 1.7; }
.ts-block ul, .ts-block ol { margin: 4px 0; padding-left: 18px; }
.ts-task-head { display: flex; align-items: center; gap: 8px; }
.ts-task-meta { font-size: 11px; color: #059669; background: #ecfdf5; padding: 1px 6px; border-radius: 6px; }
.ts-task-action { margin: 4px 0; }
.ts-task-scaffolds { color: #6b7280; }
.ts-record-table { margin-top: 8px; }
.ts-record-table strong { font-size: 12px; }
.ts-record-table p { font-size: 11px; color: #6b7280; margin: 2px 0 6px; }
.ts-record-table table, .ts-block table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.ts-record-table th, .ts-record-table td, .ts-block th, .ts-block td {
  border: 1px solid #e5e7eb;
  padding: 6px;
  text-align: left;
}
.ts-record-table th, .ts-block th { background: #f9fafb; font-weight: 600; }
.ts-question-list { margin: 4px 0; padding-left: 18px; }
</style>
