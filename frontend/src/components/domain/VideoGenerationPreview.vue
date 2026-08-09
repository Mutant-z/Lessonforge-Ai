<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { Download, Edit, RefreshRight, VideoCamera } from '@element-plus/icons-vue';
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
const loadingMedia = ref(false);
const mediaError = ref('');

const activeScene = computed(() => props.content.scenes.find(scene => scene.id === activeSceneId.value) || props.content.scenes[0]);
const totalDuration = computed(() => props.content.outputs.duration_seconds || props.content.scenes.at(-1)?.end_seconds || 0);

function timecode(seconds: number) {
  const value = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}

async function signedUrl(assetId: string | null | undefined) {
  if (!assetId) return '';
  const { data } = await api.post<{ token: string }>(`/video-assets/${assetId}/token`);
  return `/api/v1/video-assets/${assetId}/stream?token=${encodeURIComponent(data.token)}`;
}

async function loadMedia() {
  const videoAsset = props.content.outputs.preview_asset_id || props.content.outputs.final_asset_id;
  loadingMedia.value = true;
  mediaError.value = '';
  try {
    const [video, subtitle] = await Promise.all([
      signedUrl(videoAsset),
      signedUrl(props.content.outputs.subtitle_asset_id),
    ]);
    videoUrl.value = video;
    subtitleUrl.value = subtitle;
    await nextTick();
    player.value?.load();
  } catch (cause) {
    mediaError.value = errorMessage(cause);
  } finally {
    loadingMedia.value = false;
  }
}

function selectScene(scene: VideoGenerationScene) {
  activeSceneId.value = scene.id;
  if (player.value) player.value.currentTime = scene.start_seconds;
}

function syncScene() {
  const current = player.value?.currentTime || 0;
  const scene = props.content.scenes.find(item => current >= item.start_seconds && current < item.end_seconds);
  if (scene) activeSceneId.value = scene.id;
}

async function downloadFinal() {
  const assetId = props.content.outputs.final_asset_id;
  if (!assetId) return;
  mediaError.value = '';
  try {
    const { data } = await api.get(`/video-assets/${assetId}/download`, { responseType: 'blob' });
    const url = URL.createObjectURL(data);
    const link = document.createElement('a');
    link.href = url;
    link.download = `微课视频_V${props.version}.mp4`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (cause) {
    mediaError.value = errorMessage(cause);
  }
}

watch(() => [props.content.outputs.preview_asset_id, props.content.outputs.final_asset_id], loadMedia);
onMounted(loadMedia);
</script>

<template>
  <div class="video-generation-preview">
    <header class="video-masthead">
      <div>
        <span>视频成片 V{{ version }}</span>
        <h1>混合生成微课</h1>
        <p>视频脚本 V{{ content.source_versions.video_script || '—' }} · PPT V{{ content.source_versions.ppt || '—' }}</p>
      </div>
      <dl>
        <div><dt>总时长</dt><dd>{{ timecode(totalDuration) }}</dd></div>
        <div><dt>分镜</dt><dd>{{ content.scenes.length }}</dd></div>
        <div><dt>规格</dt><dd>{{ content.production_settings.resolution }}</dd></div>
        <div><dt>字幕</dt><dd>{{ content.production_settings.subtitle_enabled ? '开启' : '关闭' }}</dd></div>
      </dl>
    </header>

    <section class="player-grid">
      <div class="player-frame">
        <div v-if="loadingMedia" class="player-state"><el-icon class="is-loading"><VideoCamera /></el-icon><span>正在加载视频</span></div>
        <video v-else-if="videoUrl" ref="player" controls preload="metadata" playsinline @timeupdate="syncScene">
          <source :src="videoUrl" type="video/mp4" />
          <track v-if="subtitleUrl" kind="subtitles" srclang="zh" label="中文" :src="subtitleUrl" default />
        </video>
        <div v-else class="player-state"><el-icon><VideoCamera /></el-icon><span>{{ mediaError || '视频资源不可用' }}</span></div>
      </div>
      <aside v-if="activeScene" class="active-scene-panel">
        <span>{{ activeScene.id }} · {{ activeScene.script_scene_id }}</span>
        <h2>分镜 {{ String(activeScene.sequence).padStart(2, '0') }}</h2>
        <p>{{ activeScene.narration_text }}</p>
        <div class="scene-time">{{ timecode(activeScene.start_seconds) }}—{{ timecode(activeScene.end_seconds) }}</div>
        <el-button :icon="Edit" :disabled="disabled" @click="emit('edit', activeScene)">调整此分镜</el-button>
      </aside>
    </section>

    <section class="timeline-section">
      <header>
        <div><span>分镜时间尺</span><strong>{{ activeScene?.id }}</strong></div>
        <div class="timeline-actions">
          <el-button size="small" :icon="RefreshRight" :disabled="disabled" @click="emit('recompose')">重新合成</el-button>
          <el-button size="small" type="primary" :icon="Download" :disabled="!content.outputs.final_asset_id" @click="downloadFinal">下载 MP4</el-button>
        </div>
      </header>
      <div class="timeline-track">
        <button
          v-for="scene in content.scenes"
          :key="scene.id"
          type="button"
          :class="[scene.status, { active: scene.id === activeSceneId }]"
          :style="{ flexGrow: Math.max(1, scene.end_seconds - scene.start_seconds) }"
          @click="selectScene(scene)"
        >
          <b>{{ String(scene.sequence).padStart(2, '0') }}</b>
          <span>{{ scene.script_scene_id }}</span>
          <small>{{ Math.round(scene.end_seconds - scene.start_seconds) }}s</small>
        </button>
      </div>
      <div class="timeline-scale"><span>00:00</span><span>{{ timecode(totalDuration / 2) }}</span><span>{{ timecode(totalDuration) }}</span></div>
    </section>

    <p v-if="mediaError" class="media-error">{{ mediaError }}</p>
  </div>
</template>

<style scoped>
.video-generation-preview { min-height: 100%; padding: 24px; color: #111827; background: #f7f7f8; font-family: Helvetica Neue, Helvetica, Arial, sans-serif; }
.video-masthead { display: grid; grid-template-columns: 1.05fr 1fr; border: 1px solid #cfd2d9; background: #fff; }
.video-masthead > div { padding: 24px 28px; border-right: 1px solid #cfd2d9; }
.video-masthead > div > span, .timeline-section header span { color: #002fa7; font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.video-masthead h1 { margin: 8px 0 6px; font-size: 30px; line-height: 1.05; letter-spacing: -.04em; }
.video-masthead p { margin: 0; color: #656a73; font-size: 13px; }
.video-masthead dl { display: grid; grid-template-columns: repeat(2, 1fr); margin: 0; }
.video-masthead dl div { padding: 16px 18px; border-right: 1px solid #dfe2e7; border-bottom: 1px solid #dfe2e7; }
.video-masthead dl div:nth-child(2n) { border-right: 0; }.video-masthead dl div:nth-child(n+3) { border-bottom: 0; }
.video-masthead dt { color: #656a73; font-size: 11px; }.video-masthead dd { margin: 4px 0 0; font-size: 16px; font-weight: 800; font-variant-numeric: tabular-nums; }
.player-grid { display: grid; grid-template-columns: minmax(0, 1fr) 260px; margin-top: 18px; border: 1px solid #cfd2d9; background: #fff; }
.player-frame { aspect-ratio: 16 / 9; min-height: 320px; background: #0b1020; }.player-frame video { display: block; width: 100%; height: 100%; object-fit: contain; }
.player-state { height: 100%; display: flex; align-items: center; justify-content: center; gap: 10px; color: #fff; font-size: 13px; }
.active-scene-panel { padding: 24px; border-left: 1px solid #cfd2d9; display: flex; flex-direction: column; align-items: flex-start; }
.active-scene-panel > span { color: #002fa7; font-size: 11px; font-weight: 800; }.active-scene-panel h2 { margin: 10px 0 12px; font-size: 22px; }
.active-scene-panel p { flex: 1; margin: 0 0 18px; color: #3f4652; font-size: 13px; line-height: 1.7; }
.scene-time { width: 100%; padding: 9px 0; margin-bottom: 14px; border-top: 1px solid #cfd2d9; border-bottom: 1px solid #cfd2d9; font-weight: 800; font-variant-numeric: tabular-nums; }
.timeline-section { margin-top: 18px; padding: 18px; border: 1px solid #cfd2d9; background: #fff; }
.timeline-section header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 13px; }.timeline-section header strong { margin-left: 10px; font-size: 12px; }
.timeline-actions { display: flex; gap: 8px; }
.timeline-track { display: flex; min-height: 68px; border: 1px solid #aeb4bd; overflow: hidden; }
.timeline-track button { min-width: 58px; padding: 8px 9px; border: 0; border-right: 1px solid #fff; background: #dfe8ff; color: #18377d; text-align: left; cursor: pointer; transition: background 150ms ease; }
.timeline-track button:hover { background: #cad9ff; }.timeline-track button.active { color: #fff; background: #002fa7; }.timeline-track button.failed { background: #fee2e2; color: #991b1b; }
.timeline-track b, .timeline-track span, .timeline-track small { display: block; }.timeline-track b { font-size: 15px; }.timeline-track span { margin: 3px 0; font-size: 10px; }.timeline-track small { opacity: .72; font-variant-numeric: tabular-nums; }
.timeline-scale { display: flex; justify-content: space-between; margin-top: 7px; color: #656a73; font-size: 10px; font-variant-numeric: tabular-nums; }
.media-error { color: #b42318; font-size: 12px; }
:deep(.el-button) { border-radius: 0; }
@media (max-width: 900px) { .video-masthead, .player-grid { grid-template-columns: 1fr; }.video-masthead > div, .active-scene-panel { border: 0; border-bottom: 1px solid #cfd2d9; }.player-frame { min-height: 220px; } }
</style>
