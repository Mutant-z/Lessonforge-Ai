<script setup lang="ts">
/** 教师逐字稿 V2 预览工作台：按视频场景对齐逐段渲染口播。
 *
 * - 每段展示：章节 ID / 数值时间轴 / 关联场景 / 教学动作 / 必讲口播 / 补充旁白 /
 *   语气 / 重音 / 互动提示 / 停顿秒数 / 字数与口播时长
 * - 支持选中段落作为指令作用域（selected_section_ids）
 * - V1 兼容：字符串 time_range 时回退展示，不依赖后端投影
 */
import { computed, ref } from 'vue';

const props = defineProps<{
  content: Record<string, any> | null;
  courseTitle?: string;
  sourceVersions?: Record<string, number>;
  draft?: boolean;
}>();

const emit = defineEmits<{ (event: 'select-section', sectionId: string | null): void }>();

type Section = Record<string, any>;

const isV2 = computed(() => props.content?.schema_version === '2.0');
const sections = computed<Section[]>(() => (props.content?.sections ?? []) as Section[]);
const activeSectionId = ref<string | null>(null);

const courseInfo = computed(() => props.content?.course_info ?? {});
const rate = computed(() => Number(props.content?.speaking_rate_cps ?? 4.0));

const totalDuration = computed(() => {
  if (!sections.value.length) return 0;
  const last = sections.value[sections.value.length - 1];
  const end = isV2.value ? Number(last.end_seconds ?? 0) : 0;
  return end || Number(courseInfo.value.duration_seconds ?? 0);
});

const totalWords = computed(() => {
  return sections.value.reduce((sum, s) => sum + (s.word_count || s.required_text?.length || 0), 0);
});

const timecode = (value: number) =>
  `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(Math.round(value % 60)).padStart(2, '0')}`;

function sectionTime(section: Section): string {
  if (isV2.value) {
    return `${timecode(Number(section.start_seconds ?? 0))}—${timecode(Number(section.end_seconds ?? 0))}`;
  }
  return String(section.time_range ?? '--:--');
}

function selectSection(sectionId: string) {
  activeSectionId.value = activeSectionId.value === sectionId ? null : sectionId;
  emit('select-section', activeSectionId.value);
}

const actionMeta: Record<string, { label: string; cls: string; icon: string }> = {
  hook: { label: '导入', cls: 'hook', icon: '🚀' },
  objective_guide: { label: '目标', cls: 'objective', icon: '🎯' },
  scenario_connect: { label: '情境', cls: 'scenario', icon: '🌊' },
  metaphor_explain: { label: '讲解', cls: 'metaphor', icon: '💡' },
  misconception_alert: { label: '易错', cls: 'misconception', icon: '⚠️' },
  step_demonstration: { label: '示范', cls: 'demonstration', icon: '🔍' },
  check_in: { label: '检查', cls: 'check_in', icon: '✅' },
  summary_recap: { label: '总结', cls: 'summary', icon: '📋' },
};

function formatSpeechText(text: string): string {
  if (!text) return '';
  let result = text;
  // 高亮公式与核心物理量符号 (如 p=ρgh, F浮 = F下 - F上, Δh 等)
  result = result.replace(
    /\b(p\s*=\s*ρgh|F浮\s*=\s*F下\s*[-－]\s*F上|F浮|F下|F上|Δh|ρ|g|h)\b/g,
    '<code class="vb-formula">$1</code>'
  );
  return result;
}

function formatInteractionText(text: string): string {
  if (!text) return '';
  let res = text;
  // 停顿标记
  res = res.replace(/(停顿\s*\d+(?:\.\d+)?\s*秒)/g, '<mark class="action-tag pause"><span class="tag-icon">⏱️</span>$1</mark>');
  // 镜头机位与画中画
  res = res.replace(/((?:[^\s,，。；;]*?画中画|微笑向镜头打招呼|向镜头打招呼|特写镜头|机位[^\s,，。；;]*?))/g, '<span class="action-tag camera"><span class="tag-icon">📹</span>$1</span>');
  // 肢体手势
  res = res.replace(/((?:手势[^\s,，。；;]*?|比出[^\s,，。；;]*?手势|做出[^\s,，。；;]*?状|双手[^\s,，。；;]*?|伸手[^\s,，。；;]*?|指向[^\s,，。；;]*?))/g, '<span class="action-tag gesture"><span class="tag-icon">👉</span>$1</span>');
  // 服装道具
  res = res.replace(/((?:白大褂|实验室[^\s,，。；;]*?|实验器材|预习任务单))/g, '<span class="action-tag prop"><span class="tag-icon">👔</span>$1</span>');
  return res;
}
</script>

<template>
  <div class="verbatim-preview">
    <!-- 顶部看板 Banner -->
    <header class="vb-header">
      <div class="vb-header-masthead">
        <div class="vb-header-top">
          <div class="vb-kicker">
            <span class="vb-pulse-dot"></span>
            <span>教师口播逐字稿 · 课堂提词台本</span>
          </div>
          <span class="vb-status-tag" :class="draft ? 'draft' : 'official'">
            {{ draft ? '⚡ 候选稿' : '✓ 正式稿' }}
          </span>
        </div>

        <div class="vb-header-title-row">
          <h1 class="vb-main-title">{{ props.courseTitle || courseInfo.course_title || '课堂教师口播逐字稿' }}</h1>
        </div>

        <!-- 指标看板胶囊 -->
        <div class="vb-meta-grid">
          <div class="vb-meta-card">
            <span class="meta-icon">⏱️</span>
            <div class="meta-detail">
              <span class="meta-label">预估总时长</span>
              <span class="meta-val highlight">{{ totalDuration ? timecode(totalDuration) : '05:00' }}</span>
            </div>
          </div>
          <div class="vb-meta-card">
            <span class="meta-icon">⚡</span>
            <div class="meta-detail">
              <span class="meta-label">建议语速</span>
              <span class="meta-val">{{ rate }} 字/秒 (约 {{ Math.round(rate * 60) }} 字/分)</span>
            </div>
          </div>
          <div class="vb-meta-card">
            <span class="meta-icon">📝</span>
            <div class="meta-detail">
              <span class="meta-label">总字数 / 分段</span>
              <span class="meta-val">{{ totalWords }} 字 · {{ sections.length }} 个讲授片段</span>
            </div>
          </div>
          <div v-if="courseInfo.subject || courseInfo.grade_level" class="vb-meta-card">
            <span class="meta-icon">🎯</span>
            <div class="meta-detail">
              <span class="meta-label">学科与学段</span>
              <span class="meta-val">{{ courseInfo.subject || '物理' }} · {{ courseInfo.grade_level || '八年级' }}</span>
            </div>
          </div>
        </div>
      </div>
    </header>

    <div v-if="!sections.length" class="vb-empty">
      <div class="empty-icon">🎙️</div>
      <p>逐字稿尚未生成，请在左侧向 Agent 发送指令开始生成。</p>
    </div>

    <div v-else class="vb-sections">
      <article
        v-for="section in sections"
        :key="section.id"
        class="vb-section"
        :class="{ active: activeSectionId === section.id }"
        @click="selectSection(section.id)"
      >
        <!-- 段落卡片头部 -->
        <header class="vb-section-head">
          <div class="head-left">
            <span class="vb-seq-chip">🚀 {{ section.id }}</span>
            <span class="vb-time-chip">⏱️ {{ sectionTime(section) }}</span>
            <span v-if="section.scene_id" class="vb-scene-chip">📑 场景 {{ section.scene_id }}</span>
            
            <span
              v-if="actionMeta[section.pedagogical_action]"
              class="vb-action-badge"
              :class="actionMeta[section.pedagogical_action].cls"
            >
              {{ actionMeta[section.pedagogical_action].icon }} {{ actionMeta[section.pedagogical_action].label }}
            </span>

            <span v-if="section.pause_seconds" class="vb-pause-chip">
              ⏸️ 停顿 {{ Number(section.pause_seconds).toFixed(1) }}s
            </span>
          </div>

          <div class="head-right">
            <span class="vb-stats-badge">
              {{ section.word_count ?? section.required_text?.length ?? '—' }} 字 · {{ Number(section.estimated_duration_seconds ?? 0).toFixed(1) }}s
            </span>
            <span v-if="activeSectionId === section.id" class="vb-active-indicator">当前选中</span>
          </div>
        </header>

        <!-- 必讲主口播内容 -->
        <div class="vb-body-block">
          <p class="vb-required" v-html="formatSpeechText(section.required_text)"></p>
        </div>

        <!-- 补充拓展说明 -->
        <div v-if="section.optional_text" class="vb-supplement-box">
          <div class="supplement-head">
            <span class="supplement-icon">💡</span>
            <span class="supplement-title">教学拓展与预习提示</span>
          </div>
          <p class="supplement-text">{{ section.optional_text }}</p>
        </div>

        <!-- 语气与重音强调 -->
        <div v-if="section.delivery_tone || section.key_emphasis?.length" class="vb-tags-row">
          <div v-if="section.delivery_tone" class="vb-tone-badge">
            <span class="tag-label">🎭 讲解语气:</span>
            <span class="tag-val">{{ section.delivery_tone }}</span>
          </div>

          <div v-if="section.key_emphasis?.length" class="vb-emphasis-group">
            <span class="emphasis-label">🎯 重音强调:</span>
            <div class="emphasis-chips">
              <span
                v-for="(item, idx) in section.key_emphasis"
                :key="idx"
                class="emphasis-pill"
              >
                {{ item }}
              </span>
            </div>
          </div>
        </div>

        <!-- 台风与动作互动指令 -->
        <div v-if="section.interaction" class="vb-stage-direction-box">
          <div class="direction-header">
            <span class="direction-badge">
              <span class="direction-icon">🎭</span>
              <span>台风指南 · 肢体镜头与停顿节奏</span>
            </span>
          </div>
          <div class="direction-content" v-html="formatInteractionText(section.interaction)"></div>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.verbatim-preview {
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px;
  background: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  box-sizing: border-box;
}

/* 顶部看板 Banner */
.vb-header {
  margin-bottom: 22px;
}

.vb-header-masthead {
  padding: 22px 24px;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #1e293b 100%);
  border-radius: 18px;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.12);
  position: relative;
  overflow: hidden;
}

.vb-header-masthead::after {
  content: '';
  position: absolute;
  top: -40%;
  right: -20%;
  width: 260px;
  height: 260px;
  background: radial-gradient(circle, rgba(129, 140, 248, 0.25) 0%, rgba(129, 140, 248, 0) 70%);
  pointer-events: none;
}

.vb-header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.vb-kicker {
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

.vb-pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 8px #34d399;
  animation: vb-pulse 2s infinite ease-in-out;
}

@keyframes vb-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

.vb-status-tag {
  font-size: 11px;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 999px;
}

.vb-status-tag.draft {
  color: #fef08a;
  background: rgba(234, 179, 8, 0.2);
  border: 1px solid rgba(234, 179, 8, 0.4);
}

.vb-status-tag.official {
  color: #6ee7b7;
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid rgba(16, 185, 129, 0.4);
}

.vb-header-title-row {
  margin-bottom: 16px;
}

.vb-main-title {
  margin: 0;
  font-size: 22px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.02em;
}

.vb-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}

.vb-meta-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  backdrop-filter: blur(8px);
}

.vb-meta-card .meta-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.vb-meta-card .meta-detail {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.vb-meta-card .meta-label {
  font-size: 10.5px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.vb-meta-card .meta-val {
  font-size: 12.5px;
  font-weight: 800;
  color: #f8fafc;
  margin-top: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.vb-meta-card .meta-val.highlight {
  color: #38bdf8;
  font-variant-numeric: tabular-nums;
}

/* 空状态 */
.vb-empty {
  padding: 60px 16px;
  text-align: center;
  color: #94a3b8;
  background: #ffffff;
  border-radius: 16px;
  border: 1.5px dashed #cbd5e1;
}

.vb-empty .empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

/* 段落卡片流 */
.vb-sections {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.vb-section {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  padding: 18px 22px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.03);
}

.vb-section:hover {
  border-color: #cbd5e1;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.07);
  transform: translateY(-1px);
}

.vb-section.active {
  border-color: #6366f1;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.15);
  background: #ffffff;
}

/* 段落头部 */
.vb-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.head-left,
.head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.vb-seq-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  padding: 4px 12px;
  border-radius: 999px;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.3);
}

.vb-time-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 800;
  color: #0369a1;
  background: #e0f2fe;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid #bae6fd;
  font-variant-numeric: tabular-nums;
}

.vb-scene-chip {
  font-size: 11.5px;
  font-weight: 700;
  color: #475569;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 3px 9px;
  border-radius: 8px;
}

/* 教学动作 Badge */
.vb-action-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 999px;
}

.vb-action-badge.hook {
  background: #f5f3ff;
  color: #6d28d9;
  border: 1px solid #ddd6fe;
}

.vb-action-badge.objective {
  background: #eef2ff;
  color: #4338ca;
  border: 1px solid #c7d2fe;
}

.vb-action-badge.scenario {
  background: #ecfeff;
  color: #0e7490;
  border: 1px solid #a5f3fc;
}

.vb-action-badge.metaphor {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.vb-action-badge.misconception {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
}

.vb-action-badge.demonstration {
  background: #f0f9ff;
  color: #0284c7;
  border: 1px solid #bae6fd;
}

.vb-action-badge.check_in {
  background: #f0fdfa;
  color: #0f766e;
  border: 1px solid #99f6e4;
}

.vb-action-badge.summary {
  background: #faf5ff;
  color: #7e22ce;
  border: 1px solid #e9d5ff;
}

.vb-pause-chip {
  font-size: 11.5px;
  font-weight: 800;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
  padding: 3px 9px;
  border-radius: 999px;
}

.vb-stats-badge {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 3px 10px;
  border-radius: 8px;
  font-variant-numeric: tabular-nums;
}

.vb-active-indicator {
  font-size: 11px;
  font-weight: 800;
  color: #4f46e5;
  background: #e0e7ff;
  padding: 3px 8px;
  border-radius: 6px;
}

/* 口播正文 */
.vb-body-block {
  margin: 12px 0 14px;
}

.vb-required {
  margin: 0;
  font-size: 15px;
  line-height: 1.8;
  color: #0f172a;
  font-weight: 500;
  letter-spacing: 0.01em;
}

:deep(.vb-formula) {
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

/* 补充说明 Callout */
.vb-supplement-box {
  margin: 12px 0;
  padding: 12px 16px;
  background: #faf5ff;
  border: 1.5px solid #e9d5ff;
  border-left: 4px solid #a855f7;
  border-radius: 10px;
}

.supplement-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.supplement-icon {
  font-size: 13px;
}

.supplement-title {
  font-size: 11.5px;
  font-weight: 800;
  color: #7e22ce;
  text-transform: uppercase;
}

.supplement-text {
  margin: 0;
  font-size: 13px;
  color: #581c87;
  line-height: 1.6;
}

/* 语气与重音 */
.vb-tags-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0 10px;
  flex-wrap: wrap;
}

.vb-tone-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 8px;
}

.vb-tone-badge .tag-label {
  color: #475569;
  font-weight: 700;
}

.vb-tone-badge .tag-val {
  color: #0f172a;
  font-weight: 800;
}

.vb-emphasis-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.emphasis-label {
  font-size: 12px;
  font-weight: 800;
  color: #991b1b;
}

.emphasis-chips {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.emphasis-pill {
  font-size: 11.5px;
  font-weight: 800;
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  padding: 3px 9px;
  border-radius: 6px;
}

/* 台风指南 Box */
.vb-stage-direction-box {
  margin-top: 14px;
  padding: 14px 16px;
  background: #f0fdf4;
  border: 1.5px solid #bbf7d0;
  border-left: 4px solid #22c55e;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(34, 197, 94, 0.04);
}

.direction-header {
  margin-bottom: 8px;
}

.direction-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 800;
  color: #15803d;
  text-transform: uppercase;
}

.direction-content {
  font-size: 13px;
  line-height: 1.7;
  color: #14532d;
}

/* 动作高亮标签 */
:deep(.action-tag) {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 6px;
  margin: 0 2px;
  vertical-align: baseline;
}

:deep(.action-tag.pause) {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

:deep(.action-tag.camera) {
  background: #e0e7ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
}

:deep(.action-tag.gesture) {
  background: #dcfce7;
  color: #166534;
  border: 1px solid #bbf7d0;
}

:deep(.action-tag.prop) {
  background: #f3e8ff;
  color: #6b21a8;
  border: 1px solid #e9d5ff;
}

:deep(.tag-icon) {
  font-size: 11px;
}
</style>
