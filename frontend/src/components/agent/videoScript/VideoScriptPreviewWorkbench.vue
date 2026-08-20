<script setup lang="ts">
/** 视频脚本 V4 预览工作台：按动态章节分组渲染分镜，无预设目录。
 *
 * - 左侧章节列表（动态章节：标题/覆盖目标/时长/分镜数/QA 状态）
 * - 右侧分镜明细（画面/口播/连续性/术语），支持选中章节与分镜用于指令作用域
 * - 可选「候选稿/正式版本」标识；V3 传入时回退为扁平场景视图
 */
import { computed, ref, watch } from 'vue';
import type { VideoScriptContent, VideoScriptContentV4 } from '../../../types';
import { videoResolutionLabel } from '../../../utils/videoResolution';

const props = defineProps<{
  content: VideoScriptContent | VideoScriptContentV4 | null;
  sourceVersions?: Record<string, number>;
  draft?: boolean;
  affectedSectionIds?: string[];
  affectedSceneIds?: string[];
  preferredResolution?: string | null;
}>();

const emit = defineEmits<{
  (event: 'select-section', sectionId: string | null): void;
  (event: 'select-scene', sceneIds: string[]): void;
}>();

const isV4 = computed(() => props.content?.schema_version === '4.0');
const sections = computed(() => (isV4.value ? (props.content as VideoScriptContentV4).outline.sections : []));
const scenes = computed(() => (props.content?.scenes ?? []) as Array<Record<string, any>>);
const activeSectionId = ref<string | null>(null);
const selectedSceneIds = ref<string[]>([]);
const expandedScenes = ref<Set<string>>(new Set());

const total = computed(() => {
  if (props.content?.production_settings?.target_duration_seconds) {
    return props.content.production_settings.target_duration_seconds;
  }
  if (scenes.value.length) {
    const last = scenes.value[scenes.value.length - 1];
    return Number(last.end_seconds || 0);
  }
  return 0;
});

const timecode = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;

const sectionStats = computed<Record<string, { scenes: number; duration: number; objectives: string[] }>>(() => {
  const result: Record<string, { scenes: number; duration: number; objectives: string[] }> = {};
  for (const scene of scenes.value) {
    const sid = String(scene.section_id || '');
    const entry = (result[sid] ??= { scenes: 0, duration: 0, objectives: [] });
    entry.scenes += 1;
    entry.duration += Number(scene.end_seconds) - Number(scene.start_seconds);
    entry.objectives = Array.from(new Set([...entry.objectives, ...(scene.objective_ids ?? [])]));
  }
  return result;
});

function selectSection(sectionId: string | null) {
  activeSectionId.value = sectionId;
  selectedSceneIds.value = [];
  emit('select-section', sectionId);
}

function toggleScene(sceneId: string) {
  const index = selectedSceneIds.value.indexOf(sceneId);
  if (index >= 0) selectedSceneIds.value.splice(index, 1);
  else selectedSceneIds.value.push(sceneId);
  emit('select-scene', [...selectedSceneIds.value]);
}

function toggleSceneDetail(sceneId: string) {
  const next = new Set(expandedScenes.value);
  if (next.has(sceneId)) next.delete(sceneId);
  else next.add(sceneId);
  expandedScenes.value = next;
}

const roleColors: Record<string, { bg: string; color: string; border: string }> = {
  '导入': { bg: '#f5f3ff', color: '#6d28d9', border: '#ddd6fe' },
  '情境': { bg: '#ecfeff', color: '#0e7490', border: '#a5f3fc' },
  '目标': { bg: '#eef2ff', color: '#4338ca', border: '#c7d2fe' },
  '概念讲解': { bg: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' },
  '讲解': { bg: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' },
  '示范': { bg: '#ecfdf5', color: '#047857', border: '#a7f3d0' },
  '检查点': { bg: '#f0fdfa', color: '#0f766e', border: '#99f6e4' },
  '易错': { bg: '#fffbeb', color: '#b45309', border: '#fde68a' },
  '总结': { bg: '#faf5ff', color: '#7e22ce', border: '#e9d5ff' },
};

function getRoleStyle(role: string) {
  return roleColors[role] || { bg: '#f1f5f9', color: '#475569', border: '#cbd5e1' };
}

watch(() => props.content, () => {
  const sectionIds = new Set(sections.value.map(item => String(item.id)));
  const sceneIds = new Set(scenes.value.map(item => String(item.id)));
  if (activeSectionId.value && !sectionIds.has(activeSectionId.value)) activeSectionId.value = null;
  selectedSceneIds.value = selectedSceneIds.value.filter(id => sceneIds.has(id));
});
</script>

<template>
  <div class="v4-script">
    <!-- 顶部高档深色看板 -->
    <header class="masthead">
      <div class="masthead-left">
        <div class="masthead-badge-row">
          <span class="masthead-kicker"><span class="pulse-dot"></span>VIDEO SCRIPT / {{ isV4 ? 'V4 · 动态章节' : 'V3' }}</span>
          <span class="masthead-status-chip" :class="draft ? 'draft' : 'official'">{{ draft ? '⚡ 候选稿' : '✓ 正式版本' }}</span>
        </div>
        <h1 class="masthead-title">{{ content?.course_info?.course_title || '微课视频脚本设计' }}</h1>
        <p class="masthead-desc">Doubao-Seedance-2.5 原生有声分段脚本 · AI 导演级视听规划</p>
      </div>

      <div class="masthead-metrics">
        <div class="metric-card">
          <span class="metric-icon">⏱️</span>
          <div class="metric-detail">
            <span class="metric-label">总时长</span>
            <span class="metric-val highlight">{{ timecode(total) }}</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-icon">🎬</span>
          <div class="metric-detail">
            <span class="metric-label">分镜头数</span>
            <span class="metric-val">{{ scenes.length }}</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-icon">📑</span>
          <div class="metric-detail">
            <span class="metric-label">章节划分</span>
            <span class="metric-val">{{ isV4 ? `${sections.length} 章` : '单幕流式' }}</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-icon">💡</span>
          <div class="metric-detail">
            <span class="metric-label">脚本状态</span>
            <span class="metric-val success">{{ draft ? '推演中' : '交付就绪' }}</span>
          </div>
        </div>
      </div>
    </header>

    <!-- 生产契约与渲染参数 -->
    <section class="contract-banner">
      <div class="contract-label"><span class="contract-icon">📋</span>生产契约</div>
      <div class="contract-tags">
        <span class="contract-tag">📐 16:9 画幅</span>
        <span class="contract-tag">📺 {{ videoResolutionLabel(props.preferredResolution) }} 分辨率</span>
        <span class="contract-tag">
          ⏱️ {{ content?.production_settings?.min_clip_seconds && content?.production_settings?.max_clip_seconds ? `${content.production_settings.min_clip_seconds}–${content.production_settings.max_clip_seconds} 秒/段` : '8–15 秒/段' }}
        </span>
        <span class="contract-tag voice">🎙️ 模型原生语音</span>
        <span class="contract-tag subtitle">💬 字幕由 ASR 生成</span>
      </div>
      <div class="contract-source">
        <span>对齐: 教学设计 V{{ sourceVersions?.lesson_plan || '8' }}</span>
      </div>
    </section>

    <!-- V3 回退：扁平场景视图 -->
    <template v-if="!isV4">
      <!-- 现代化时间轴尺 -->
      <div class="timeline-ruler">
        <div
          v-for="scene in scenes"
          :key="scene.id"
          class="timeline-segment"
          :style="{
            flexGrow: Math.max(1, (scene.end_seconds - scene.start_seconds) || 1),
            background: getRoleStyle(scene.pedagogical_role).bg,
            borderColor: getRoleStyle(scene.pedagogical_role).border,
            color: getRoleStyle(scene.pedagogical_role).color
          }"
        >
          <span class="timeline-seq">{{ String(scene.sequence).padStart(2, '0') }}</span>
          <span class="timeline-role">{{ scene.pedagogical_role }}</span>
          <span class="timeline-duration">{{ ((scene.end_seconds - scene.start_seconds) || 0).toFixed(0) }}s</span>
        </div>
      </div>

      <!-- 分镜头卡片列表 -->
      <section class="scene-stream">
        <article v-for="scene in scenes" :key="scene.id" class="storyboard-card">
          <header class="card-header">
            <div class="card-header-left">
              <span class="scene-id-badge">🎬 {{ scene.id }}</span>
              <span v-if="scene.continuity_group" class="continuity-badge">组: {{ scene.continuity_group }}</span>
              <span class="time-range-badge">⏱️ {{ timecode(scene.start_seconds) }} — {{ timecode(scene.end_seconds) }}</span>
            </div>
            <div class="card-header-right">
              <span
                class="role-badge"
                :style="{
                  background: getRoleStyle(scene.pedagogical_role).bg,
                  borderColor: getRoleStyle(scene.pedagogical_role).border,
                  color: getRoleStyle(scene.pedagogical_role).color
                }"
              >
                {{ scene.pedagogical_role }}
              </span>
              <span class="duration-pill">{{ ((scene.end_seconds - scene.start_seconds) || 0).toFixed(0) }} 秒</span>
            </div>
          </header>

          <div class="card-title-row">
            <h2 class="scene-title">{{ scene.title }}</h2>
          </div>

          <div class="scene-content-grid">
            <div class="visual-box">
              <div class="box-head">
                <span class="box-icon">🎨</span>
                <span class="box-label">画面任务与视觉动作</span>
              </div>
              <p class="box-text">{{ scene.visual_prompt || '以对应 PPT 为主画面，结合知识点图示展示概念结构。' }}</p>
            </div>

            <div class="spoken-box">
              <div class="box-head">
                <span class="box-icon">🎙️</span>
                <span class="box-label">模型原生口播台词</span>
              </div>
              <blockquote class="spoken-quote">
                “{{ scene.spoken_text || '同学们好，接下来我们一起来观察实验现象，建立核心物理概念。' }}”
              </blockquote>
            </div>
          </div>

          <footer v-if="scene.required_terms?.length || scene.required_numbers?.length || scene.voice_direction" class="card-footer">
            <span v-for="term in scene.required_terms" :key="term" class="term-pill">
              <span class="pill-dot blue"></span>术语: {{ term }}
            </span>
            <span v-for="number in scene.required_numbers" :key="number" class="number-pill">
              <span class="pill-dot amber"></span>数值: {{ number }}
            </span>
            <span v-if="scene.voice_direction" class="voice-pill">
              <span class="pill-dot purple"></span>声音: {{ scene.voice_direction }}
            </span>
          </footer>
        </article>
      </section>
    </template>

    <!-- V4：动态章节分组 -->
    <template v-else>
      <div class="section-list">
        <button
          v-for="section in sections"
          :key="section.id"
          type="button"
          class="section-card"
          :class="{ active: activeSectionId === section.id, updated: affectedSectionIds?.includes(section.id) }"
          @click="selectSection(activeSectionId === section.id ? null : section.id)"
        >
          <div class="section-num">{{ section.sequence }}</div>
          <div class="section-meta">
            <h3>{{ section.title }}</h3>
            <p>{{ section.purpose }}</p>
            <small>
              {{ sectionStats[section.id]?.scenes ?? 0 }} 个分镜 ·
              {{ timecode(sectionStats[section.id]?.duration ?? 0) }} ·
              {{ (section.objective_ids ?? []).join('、') || '未绑定目标' }}
            </small>
          </div>
        </button>
      </div>

      <section class="scene-stream">
        <template v-for="section in sections" :key="section.id">
          <div v-if="activeSectionId === null || activeSectionId === section.id" class="section-block">
            <header class="section-head">
              <span class="section-title">章节 {{ section.sequence }} · {{ section.title }}</span>
              <small class="section-stats">{{ sectionStats[section.id]?.scenes ?? 0 }} 个分镜 · {{ timecode(sectionStats[section.id]?.duration ?? 0) }}</small>
            </header>
            <article
              v-for="scene in scenes.filter(item => item.section_id === section.id)"
              :key="scene.id"
              class="storyboard-card"
              :class="{ selected: selectedSceneIds.includes(scene.id), updated: affectedSceneIds?.includes(scene.id) }"
              @click="toggleScene(scene.id)"
            >
              <header class="card-header">
                <div class="card-header-left">
                  <span class="scene-id-badge">🎬 {{ scene.id }}</span>
                  <span v-if="scene.continuity_group" class="continuity-badge">组: {{ scene.continuity_group }}</span>
                  <span class="time-range-badge">⏱️ {{ timecode(scene.start_seconds) }} — {{ timecode(scene.end_seconds) }}</span>
                </div>
                <div class="card-header-right">
                  <span
                    class="role-badge"
                    :style="{
                      background: getRoleStyle(scene.pedagogical_role).bg,
                      borderColor: getRoleStyle(scene.pedagogical_role).border,
                      color: getRoleStyle(scene.pedagogical_role).color
                    }"
                  >
                    {{ scene.pedagogical_role }}
                  </span>
                  <span class="duration-pill">{{ ((scene.end_seconds - scene.start_seconds) || 0).toFixed(0) }} 秒</span>
                </div>
              </header>

              <div class="card-title-row">
                <h2 class="scene-title">{{ scene.title }}</h2>
                <button type="button" class="detail-toggle-btn" @click.stop="toggleSceneDetail(scene.id)">
                  {{ expandedScenes.has(scene.id) ? '收起视听明细 ▲' : '展开视听明细 ▼' }}
                </button>
              </div>

              <div v-if="expandedScenes.has(scene.id)" class="scene-content-grid">
                <div class="visual-box">
                  <div class="box-head">
                    <span class="box-icon">🎨</span>
                    <span class="box-label">画面任务与视觉动作</span>
                  </div>
                  <p class="box-text">{{ scene.visual_prompt || '以对应 PPT 为主画面，结合知识点图示展示概念结构。' }}</p>
                </div>

                <div class="spoken-box">
                  <div class="box-head">
                    <span class="box-icon">🎙️</span>
                    <span class="box-label">模型原生口播台词</span>
                  </div>
                  <blockquote class="spoken-quote">
                    “{{ scene.spoken_text || '同学们好，接下来我们一起来观察实验现象，建立核心物理概念。' }}”
                  </blockquote>
                </div>
              </div>

              <footer v-if="scene.required_terms?.length || scene.required_numbers?.length || scene.voice_direction" class="card-footer">
                <span v-for="term in scene.required_terms" :key="term" class="term-pill">
                  <span class="pill-dot blue"></span>术语: {{ term }}
                </span>
                <span v-for="number in scene.required_numbers" :key="number" class="number-pill">
                  <span class="pill-dot amber"></span>数值: {{ number }}
                </span>
                <span v-if="scene.voice_direction" class="voice-pill">
                  <span class="pill-dot purple"></span>声音: {{ scene.voice_direction }}
                </span>
              </footer>
            </article>
          </div>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
.v4-script {
  height: 100%;
  overflow-y: auto;
  padding: 22px 24px;
  box-sizing: border-box;
  color: #1e293b;
  background: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

/* 顶部深色 Masthead 看板 */
.masthead {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #1e293b 100%);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 18px;
  color: #ffffff;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
  position: relative;
  overflow: hidden;
}

.masthead::after {
  content: '';
  position: absolute;
  top: -40%;
  right: -20%;
  width: 260px;
  height: 260px;
  background: radial-gradient(circle, rgba(129, 140, 248, 0.25) 0%, rgba(129, 140, 248, 0) 70%);
  pointer-events: none;
}

.masthead-left {
  padding: 24px 28px;
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}

.masthead-badge-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
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
  animation: script-pulse 2s infinite ease-in-out;
}

@keyframes script-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}

.masthead-status-chip {
  font-size: 11px;
  font-weight: 800;
  padding: 3px 10px;
  border-radius: 999px;
}

.masthead-status-chip.draft {
  color: #fef08a;
  background: rgba(234, 179, 8, 0.2);
  border: 1px solid rgba(234, 179, 8, 0.4);
}

.masthead-status-chip.official {
  color: #6ee7b7;
  background: rgba(16, 185, 129, 0.2);
  border: 1px solid rgba(16, 185, 129, 0.4);
}

.masthead-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.02em;
}

.masthead-desc {
  margin: 0;
  color: #94a3b8;
  font-size: 13px;
}

.masthead-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 16px;
  gap: 10px;
  background: rgba(255, 255, 255, 0.03);
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  backdrop-filter: blur(8px);
}

.metric-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.metric-detail {
  display: flex;
  flex-direction: column;
}

.metric-label {
  font-size: 10px;
  font-weight: 700;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.metric-val {
  font-size: 14px;
  font-weight: 900;
  color: #f8fafc;
  margin-top: 1px;
}

.metric-val.highlight {
  color: #38bdf8;
  font-variant-numeric: tabular-nums;
}

.metric-val.success {
  color: #6ee7b7;
}

/* 生产契约条 */
.contract-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
  padding: 12px 18px;
  border: 1.5px solid #e2e8f0;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
  flex-wrap: wrap;
}

.contract-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 800;
  color: #4338ca;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.contract-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.contract-tag {
  font-size: 11.5px;
  font-weight: 700;
  color: #334155;
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
  padding: 4px 10px;
  border-radius: 8px;
}

.contract-tag.voice {
  color: #4338ca;
  background: #eef2ff;
  border-color: #c7d2fe;
}

.contract-tag.subtitle {
  color: #047857;
  background: #ecfdf5;
  border-color: #a7f3d0;
}

.contract-source {
  margin-left: auto;
  font-size: 11.5px;
  font-weight: 700;
  color: #64748b;
  background: #f8fafc;
  padding: 3px 8px;
  border-radius: 6px;
}

/* 时间轴分段条 */
.timeline-ruler {
  display: flex;
  min-height: 72px;
  margin-top: 16px;
  border: 1.5px solid #cbd5e1;
  border-radius: 14px;
  background: #f8fafc;
  overflow-x: auto;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
}

.timeline-segment {
  min-width: 68px;
  padding: 10px 8px;
  border-right: 1.5px solid #ffffff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  transition: all 0.2s ease;
  cursor: default;
}

.timeline-segment:last-child {
  border-right: 0;
}

.timeline-segment:hover {
  filter: brightness(0.95);
  transform: translateY(-1px);
}

.timeline-seq {
  font-size: 12px;
  font-weight: 900;
}

.timeline-role {
  font-size: 10.5px;
  font-weight: 700;
  margin: 3px 0 1px;
}

.timeline-duration {
  font-size: 10px;
  font-weight: 800;
  opacity: 0.8;
}

/* 分镜故事板卡片流 */
.scene-stream {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 18px;
}

.storyboard-card {
  background: #ffffff;
  border: 1.5px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
  overflow: hidden;
  transition: all 0.2s ease;
}

.storyboard-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.storyboard-card.selected {
  border-color: #6366f1;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.16);
}

.storyboard-card.updated {
  border-color: #2563eb;
  box-shadow: inset 3px 0 0 #2563eb;
  animation: revision-highlight 1.4s ease-out;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-bottom: 1.5px solid #e2e8f0;
  flex-wrap: wrap;
}

.card-header-left,
.card-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.scene-id-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  padding: 4px 12px;
  border-radius: 999px;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.3);
}

.continuity-badge {
  font-size: 11px;
  font-weight: 800;
  color: #7c3aed;
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  padding: 3px 8px;
  border-radius: 6px;
}

.time-range-badge {
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

.role-badge {
  font-size: 11.5px;
  font-weight: 800;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid;
}

.duration-pill {
  font-size: 11.5px;
  font-weight: 700;
  color: #64748b;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  padding: 3px 8px;
  border-radius: 6px;
  font-variant-numeric: tabular-nums;
}

.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px 0;
}

.scene-title {
  margin: 0;
  font-size: 17px;
  font-weight: 900;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.detail-toggle-btn {
  font-size: 11.5px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  border: 1px solid #c7d2fe;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.detail-toggle-btn:hover {
  background: #e0e7ff;
}

.scene-content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 14px 20px 16px;
}

.visual-box,
.spoken-box {
  border-radius: 12px;
  padding: 14px 16px;
}

.visual-box {
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
}

.spoken-box {
  background: #f0fdf4;
  border: 1.5px solid #bbf7d0;
}

.box-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.box-icon {
  font-size: 14px;
}

.box-label {
  font-size: 11.5px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.visual-box .box-label {
  color: #334155;
}

.spoken-box .box-label {
  color: #15803d;
}

.box-text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.7;
  color: #334155;
}

.spoken-quote {
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: #14532d;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.75;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: #fafbfc;
  border-top: 1px solid #e2e8f0;
  flex-wrap: wrap;
}

.term-pill,
.number-pill,
.voice-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 6px;
}

.term-pill {
  color: #1e40af;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.number-pill {
  color: #92400e;
  background: #fef3c7;
  border: 1px solid #fde68a;
}

.voice-pill {
  color: #6b21a8;
  background: #faf5ff;
  border: 1px solid #e9d5ff;
}

.pill-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}

.pill-dot.blue { background: #3b82f6; }
.pill-dot.amber { background: #f59e0b; }
.pill-dot.purple { background: #a855f7; }

/* V4 章节卡片 */
.section-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
}

.section-card {
  display: grid;
  grid-template-columns: 48px 1fr;
  gap: 14px;
  align-items: center;
  text-align: left;
  padding: 14px 18px;
  border: 1.5px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s ease;
  color: inherit;
}

.section-card:hover {
  border-color: #c7d2fe;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.08);
}

.section-card.active {
  border-color: #6366f1;
  background: #f5f7ff;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.12);
}

.section-card.updated {
  border-color: #2563eb;
  box-shadow: inset 3px 0 0 #2563eb;
  animation: revision-highlight 1.4s ease-out;
}

@keyframes revision-highlight {
  from { background: #dbeafe; }
  to { background: #ffffff; }
}

.section-num {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: #eef2ff;
  color: #4f46e5;
  font-size: 18px;
  font-weight: 900;
  display: grid;
  place-items: center;
}

.section-card.active .section-num {
  background: #4f46e5;
  color: #ffffff;
}

.section-meta h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 900;
  color: #0f172a;
}

.section-meta p {
  margin: 3px 0 4px;
  color: #475569;
  font-size: 12.5px;
}

.section-meta small {
  color: #64748b;
  font-size: 11.5px;
  font-weight: 600;
}

.section-block {
  margin-bottom: 24px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 18px;
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border-radius: 14px 14px 0 0;
  color: #ffffff;
}

.section-head .section-title {
  font-size: 15px;
  font-weight: 900;
}

.section-head .section-stats {
  font-size: 12px;
  color: #94a3b8;
}

@media (max-width: 820px) {
  .masthead,
  .scene-content-grid {
    grid-template-columns: 1fr;
  }
  .masthead-left {
    border-right: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
  }
}
</style>
