<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { 
  Clock, 
  Cpu, 
  Download, 
  Edit, 
  Film, 
  Microphone, 
  RefreshRight, 
  VideoCamera, 
  VideoPlay 
} from '@element-plus/icons-vue';
import { api, errorMessage } from '../../api/client';
import type { VideoGenerationContent, VideoGenerationScene } from '../../types';

const props = defineProps<{
  content: VideoGenerationContent;
  version: number;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  edit: [scene: VideoGenerationScene];
  recompose: [];
}>();

const player = ref<HTMLVideoElement | null>(null);
const videoUrl = ref('');
const subtitleUrl = ref('');
const activeSceneId = ref(props.content.scenes[0]?.id || '');
const loading = ref(false);
const mediaError = ref('');

const activeScene = computed(() => props.content.scenes.find(s => s.id === activeSceneId.value) || props.content.scenes[0]);
const duration = computed(() => props.content.outputs.duration_seconds || props.content.scenes.at(-1)?.end_seconds || 0);
const resolutionLabel = computed(() => props.content.production_settings.resolution === '854x480' ? '480p' : '720p');

const timecode = (seconds: number) => 
  `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;

async function signedUrl(id?: string | null) {
  if (!id) return '';
  const { data } = await api.post<{ token: string }>(`/video-assets/${id}/token`);
  return `/api/v1/video-assets/${id}/stream?token=${encodeURIComponent(data.token)}`;
}

const playableScene = computed(() => props.content.scenes.find(scene => scene.status === 'ready' && scene.video_asset_id));

async function loadMedia() {
  loading.value = true;
  mediaError.value = '';
  try {
    const mediaId = props.content.outputs.preview_asset_id || 
                    props.content.outputs.final_asset_id || 
                    activeScene.value?.video_asset_id || 
                    playableScene.value?.video_asset_id;
    [videoUrl.value, subtitleUrl.value] = await Promise.all([
      signedUrl(mediaId),
      signedUrl(props.content.outputs.subtitle_asset_id)
    ]);
    await nextTick();
    player.value?.load();
  } catch (e) {
    mediaError.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
}

function select(scene: VideoGenerationScene) {
  activeSceneId.value = scene.id;
  if (player.value) player.value.currentTime = scene.start_seconds;
}

function sync() {
  const current = player.value?.currentTime || 0;
  const found = props.content.scenes.find(s => current >= s.start_seconds && current < s.end_seconds);
  if (found) activeSceneId.value = found.id;
}

function qaLabel(status?: string) {
  if (status === 'passed') return '音轨检查通过';
  if (status === 'warning') return '建议人工复核';
  return '已使用脚本字幕';
}

async function download() {
  const id = props.content.outputs.final_asset_id || 
             activeScene.value?.video_asset_id || 
             playableScene.value?.video_asset_id;
  if (!id) return;
  const { data } = await api.get(`/video-assets/${id}/download`, { responseType: 'blob' });
  const url = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = url;
  a.download = `微课视频_V${props.version}.mp4`;
  a.click();
  URL.revokeObjectURL(url);
}

watch(() => [props.content.outputs.preview_asset_id, props.content.outputs.final_asset_id, activeScene.value?.video_asset_id], loadMedia);
onMounted(loadMedia);
</script>

<template>
  <div class="native-preview">
    <!-- Masthead Summary Banner -->
    <header class="masthead">
      <div class="masthead-left">
        <span class="version-chip">微课成片 · V{{ version }}</span>
        <h1>微课视频预览</h1>
        <p>基于分镜脚本 V{{ content.source_versions.video_script }} · 模型: {{ content.production_settings.model_name }}</p>
      </div>

      <dl class="masthead-stats">
        <div class="stat-cell">
          <dt><el-icon><Clock /></el-icon> 视频时长</dt>
          <dd>{{ timecode(duration) }}</dd>
        </div>
        <div class="stat-cell">
          <dt><el-icon><Film /></el-icon> 分镜数量</dt>
          <dd>{{ content.scenes.length }} 个片段</dd>
        </div>
        <div class="stat-cell">
          <dt><el-icon><Microphone /></el-icon> 伴声音轨</dt>
          <dd>原生音视频合成</dd>
        </div>
        <div class="stat-cell">
          <dt><el-icon><VideoCamera /></el-icon> 画质规格</dt>
          <dd>{{ resolutionLabel }} / 25fps</dd>
        </div>
      </dl>
    </header>

    <!-- Player & Scene Details Grid -->
    <section class="player-grid">
      <!-- 16:9 Video Canvas -->
      <div class="player-container">
        <div v-if="loading" class="player-state">
          <el-icon class="is-loading"><VideoCamera /></el-icon>
          <span>正在加载视频资源...</span>
        </div>
        <video 
          v-else-if="videoUrl" 
          ref="player" 
          controls 
          playsinline 
          @timeupdate="sync"
        >
          <source :src="videoUrl" type="video/mp4" />
          <track 
            v-if="subtitleUrl" 
            kind="subtitles" 
            srclang="zh" 
            label="中文字幕" 
            :src="subtitleUrl" 
            default 
          />
        </video>
        <div v-else class="player-state error">
          <el-icon><VideoCamera /></el-icon>
          <span>{{ mediaError || '视频资源生成中或暂不可用' }}</span>
        </div>
      </div>

      <!-- Active Scene Aside Detail Card -->
      <aside v-if="activeScene" class="scene-detail-card">
        <div class="scene-card-header">
          <span class="scene-num-badge">片段 {{ String(activeScene.sequence).padStart(2, '0') }}</span>
          <span class="scene-status-chip" :class="activeScene.qa?.status || 'passed'">
            {{ qaLabel(activeScene.qa?.status) }}
          </span>
        </div>

        <h2 class="scene-group-title">{{ activeScene.continuity_group || `分镜 #${activeScene.sequence}` }}</h2>

        <div class="scene-section">
          <label class="section-label">确认口播脚本</label>
          <div class="speech-box">
            <p>{{ activeScene.spoken_text }}</p>
          </div>
        </div>

        <div class="scene-section">
          <label class="section-label">音轨与画面检验</label>
          <p class="qa-msg">{{ activeScene.qa?.message || qaLabel(activeScene.qa?.status) }}</p>
        </div>

        <dl class="scene-meta-list">
          <div class="meta-row">
            <dt>生成状态</dt>
            <dd>{{ activeScene.status === 'ready' ? '已就绪' : activeScene.status }}</dd>
          </div>
          <div class="meta-row">
            <dt>关联镜头</dt>
            <dd>{{ activeScene.reference_scene_ids.length ? `${activeScene.reference_scene_ids.length} 个依赖` : '独立镜头' }}</dd>
          </div>
        </dl>

        <div class="scene-card-actions">
          <el-button 
            type="primary" 
            plain 
            :icon="Edit" 
            :disabled="disabled" 
            class="btn-edit-scene" 
            @click="emit('edit', activeScene)"
          >
            修改本片段内容
          </el-button>
        </div>
      </aside>
    </section>

    <!-- Multi-Scene Timeline Ruler Track -->
    <section class="timeline-ruler-section">
      <header class="timeline-header">
        <div class="timeline-title-group">
          <el-icon><Film /></el-icon>
          <h3>分镜时间轴</h3>
          <span class="timeline-sub">点击分镜可精准跳转播放并调优画面与台词</span>
        </div>
        <div class="timeline-actions">
          <el-button 
            size="small" 
            :icon="RefreshRight" 
            :disabled="disabled" 
            @click="emit('recompose')"
          >
            重新拼接视频
          </el-button>
          <el-button 
            size="small" 
            type="primary" 
            :icon="Download" 
            @click="download"
          >
            下载 MP4
          </el-button>
        </div>
      </header>

      <div class="scenes-track">
        <button 
          v-for="scene in content.scenes" 
          :key="scene.id" 
          class="scene-track-btn"
          :class="[scene.status, { active: scene.id === activeSceneId }]" 
          :style="{ flexGrow: Math.max(1, scene.end_seconds - scene.start_seconds) }" 
          @click="select(scene)"
        >
          <div class="track-btn-top">
            <b class="scene-seq">#{{ String(scene.sequence).padStart(2, '0') }}</b>
            <span class="scene-dur">{{ (scene.end_seconds - scene.start_seconds).toFixed(1) }}s</span>
          </div>
          <span class="scene-qa-pill">{{ qaLabel(scene.qa?.status) }}</span>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.native-preview {
  min-height: 100%;
  padding: 20px 24px 36px;
  box-sizing: border-box;
  color: var(--text-primary, #0f172a);
  background: var(--bg-page, #f5f7fa);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 1. Masthead */
.masthead {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #1e293b 100%);
  border-radius: var(--radius-card, 16px);
  color: #ffffff;
  overflow: hidden;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.14);
}

.masthead-left {
  padding: 20px 24px;
  border-right: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.version-chip {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 800;
  color: #818cf8;
  letter-spacing: 0.06em;
  margin-bottom: 6px;
}

.masthead h1 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 900;
  color: #ffffff;
  letter-spacing: -0.02em;
}

.masthead p {
  margin: 0;
  color: #94a3b8;
  font-size: 12.5px;
}

.masthead-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 0;
  background: rgba(255, 255, 255, 0.02);
}

.stat-cell {
  padding: 14px 18px;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.stat-cell:nth-child(2n) {
  border-right: 0;
}

.stat-cell:nth-child(n+3) {
  border-bottom: 0;
}

dt {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

dd {
  margin: 4px 0 0;
  font-size: 14.5px;
  font-weight: 800;
  color: #f8fafc;
  font-variant-numeric: tabular-nums;
}

/* 2. Player Grid */
.player-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 16px;
}

.player-container {
  aspect-ratio: 16/9;
  background: #090d16;
  border-radius: var(--radius-card, 16px);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
  border: 1px solid #e2e8f0;
}

.player-container video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.player-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
}

.player-state.error {
  color: #f87171;
}

.player-state .el-icon {
  font-size: 28px;
}

/* Scene Aside Detail Card */
.scene-detail-card {
  padding: 18px 20px;
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  background: #ffffff;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
}

.scene-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.scene-num-badge {
  font-size: 11px;
  font-weight: 800;
  color: var(--primary-600, #4f46e5);
  background: var(--primary-50, #eef2ff);
  padding: 2px 8px;
  border-radius: 6px;
}

.scene-status-chip {
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.scene-status-chip.warning {
  background: #fffbeb;
  color: #b45309;
  border-color: #fde68a;
}

.scene-group-title {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.scene-section {
  margin-bottom: 10px;
}

.section-label {
  display: block;
  margin-bottom: 4px;
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.speech-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 8px 12px;
  border-radius: 10px;
}

.speech-box p {
  margin: 0;
  color: #334155;
  font-size: 12.5px;
  line-height: 1.6;
}

.qa-msg {
  margin: 0;
  font-size: 12px;
  color: #475569;
}

.scene-meta-list {
  display: grid;
  gap: 6px;
  margin: 0 0 14px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.meta-row {
  display: grid;
  grid-template-columns: 75px 1fr;
  gap: 8px;
  align-items: center;
}

.meta-row dt {
  font-size: 11px;
  color: #64748b;
}

.meta-row dd {
  margin: 0;
  font-size: 12px;
  color: var(--text-primary, #0f172a);
  font-weight: 700;
}

.scene-card-actions {
  margin-top: auto;
}

.btn-edit-scene {
  width: 100%;
  border-radius: var(--radius-pill, 999px) !important;
}

/* 3. Timeline Ruler */
.timeline-ruler-section {
  padding: 16px 20px;
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  background: #ffffff;
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.timeline-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.timeline-title-group .el-icon {
  font-size: 18px;
  color: var(--primary-600, #4f46e5);
}

.timeline-title-group h3 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.timeline-sub {
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.timeline-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.timeline-actions :deep(.el-button) {
  border-radius: var(--radius-pill, 999px) !important;
}

.scenes-track {
  display: flex;
  min-height: 76px;
  border: 1.5px solid #cbd5e1;
  border-radius: 12px;
  overflow: hidden;
  background: #f1f5f9;
  gap: 2px;
  padding: 2px;
}

.scene-track-btn {
  min-width: 68px;
  padding: 8px 10px;
  border: 0;
  background: #ffffff;
  color: #1e3a8a;
  text-align: left;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.scene-track-btn:hover {
  background: #e0e7ff;
}

.scene-track-btn.active {
  background: #4f46e5;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.35);
}

.track-btn-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px;
}

.scene-seq {
  font-size: 13px;
  font-weight: 900;
}

.scene-dur {
  font-size: 10.5px;
  font-weight: 700;
  opacity: 0.85;
}

.scene-qa-pill {
  font-size: 9.5px;
  font-weight: 700;
  opacity: 0.85;
}

.scene-track-btn.active .scene-dur,
.scene-track-btn.active .scene-qa-pill {
  color: #e0e7ff;
}

.scene-track-btn.qa_failed,
.scene-track-btn.failed {
  background: #fee2e2;
  color: #991b1b;
}

@media (max-width: 850px) {
  .masthead,
  .player-grid {
    grid-template-columns: 1fr;
  }
  .masthead-left {
    border-right: 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }
}
</style>

