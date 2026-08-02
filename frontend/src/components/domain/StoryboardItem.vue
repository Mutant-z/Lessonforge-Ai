<script setup lang="ts">
import type { StoryboardItem } from '../../types';
import { VideoCamera, Picture, Microphone } from '@element-plus/icons-vue';

defineProps<{
  scene: StoryboardItem;
}>();
</script>

<template>
  <div class="storyboard-row lf-card card-hover">
    <div class="scene-badge">
      <span class="scene-num">分镜 {{ scene.scene_number }}</span>
      <span class="time-range">{{ scene.time_range }}</span>
    </div>

    <div class="storyboard-grid">
      <div class="sb-block visual">
        <h5><el-icon><Picture /></el-icon> 画面构图与动画</h5>
        <p>{{ scene.visual_description }}</p>
      </div>

      <div class="sb-block narration">
        <h5><el-icon><Microphone /></el-icon> 旁白与配音</h5>
        <p>"{{ scene.narration }}"</p>
      </div>

      <div class="sb-block subtitle">
        <h5><el-icon><VideoCamera /></el-icon> 屏幕字幕与贴字</h5>
        <p>{{ scene.subtitle || scene.on_screen_graphic }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.storyboard-row {
  margin-bottom: 16px;
  padding: 18px;
}

.scene-badge {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-light);
}

.scene-num {
  font-size: 14px;
  font-weight: 800;
  color: var(--color-primary);
}

.time-range {
  font-size: 12px;
  color: var(--text-muted);
  font-family: monospace;
}

.storyboard-grid {
  display: grid;
  grid-template-columns: 1fr 1.2fr 1fr;
  gap: 16px;
}

@media (max-width: 768px) {
  .storyboard-grid {
    grid-template-columns: 1fr;
  }
}

.sb-block h5 {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 4px;
}

.sb-block p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.sb-block.narration p {
  color: var(--color-primary);
  font-weight: 500;
}
</style>
