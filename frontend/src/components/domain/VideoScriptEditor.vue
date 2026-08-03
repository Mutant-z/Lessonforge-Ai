<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue';
import type { VideoAnimationAction, VideoPedagogicalRole, VideoScene, VideoScriptContent } from '../../types';

const model = defineModel<VideoScriptContent>({ required: true });
const roles: VideoPedagogicalRole[] = ['导入', '目标', '情境', '概念讲解', '示范', '练习', '检查点', '总结', '过渡'];
const actions: VideoAnimationAction[] = ['显示', '高亮', '缩放', '平移', '标注', '转场'];

function splitLines(value: string): string[] {
  return value.split('\n').map(item => item.trim()).filter(Boolean);
}

function splitRefs(value: string): string[] {
  return value.split(/[、,\s]+/).map(item => item.trim()).filter(Boolean);
}

function addScene() {
  const source = model.value.scenes[model.value.scenes.length - 1];
  if (!source) return;
  const midpoint = Math.max(source.start_seconds + 1, Math.floor((source.start_seconds + source.end_seconds) / 2));
  const oldEnd = source.end_seconds;
  source.end_seconds = midpoint;
  const sourceDuration = midpoint - source.start_seconds;
  source.visual_track.animation_cues = source.visual_track.animation_cues.filter(cue => cue.offset_seconds <= sourceDuration);
  source.audio_track.pause_cues = source.audio_track.pause_cues.filter(cue => cue.offset_seconds + cue.duration_seconds <= sourceDuration);
  source.audio_track.sound_cues = source.audio_track.sound_cues.filter(cue => cue.offset_seconds <= sourceDuration);
  source.text_track.subtitle_chunks = [{ start_offset_seconds: 0, end_offset_seconds: sourceDuration, text: source.audio_track.narration_text }];
  if (source.interaction) source.interaction.wait_seconds = Math.min(source.interaction.wait_seconds, sourceDuration);
  const scene: VideoScene = JSON.parse(JSON.stringify(source));
  scene.id = `VS-${String(model.value.scenes.length + 1).padStart(2, '0')}`;
  scene.sequence = model.value.scenes.length + 1;
  scene.title = `${source.title} · 补充分镜`;
  scene.start_seconds = midpoint;
  scene.end_seconds = oldEnd;
  scene.learning_purpose = '补充当前页面的讲解或演示步骤';
  scene.audio_track.narration_text = '请补充本分镜可直接录制的旁白。';
  scene.text_track.subtitle_chunks = [{ start_offset_seconds: 0, end_offset_seconds: oldEnd - midpoint, text: scene.audio_track.narration_text }];
  scene.visual_track.animation_cues = [];
  scene.audio_track.pause_cues = [];
  scene.audio_track.sound_cues = [];
  scene.interaction = null;
  model.value.scenes.push(scene);
}

function removeScene(index: number) {
  const scene = model.value.scenes[index];
  if (!scene || !canRemoveScene(scene)) return;
  const previous = model.value.scenes[index - 1];
  const next = model.value.scenes[index + 1];
  if (previous?.slide_id === scene.slide_id) {
    previous.end_seconds = scene.end_seconds;
    previous.text_track.subtitle_chunks = [{
      start_offset_seconds: 0,
      end_offset_seconds: previous.end_seconds - previous.start_seconds,
      text: previous.audio_track.narration_text,
    }];
  } else if (next?.slide_id === scene.slide_id) {
    next.start_seconds = scene.start_seconds;
  }
  model.value.scenes.splice(index, 1);
  model.value.scenes.forEach((scene, sceneIndex) => { scene.sequence = sceneIndex + 1; });
}

function canRemoveScene(scene: VideoScene) {
  return model.value.scenes.filter(item => item.slide_id === scene.slide_id).length > 1;
}

function addAnimation(scene: VideoScene) {
  scene.visual_track.animation_cues.push({ offset_seconds: 0, target: '当前要点', action: '高亮', instruction: '随旁白突出当前信息' });
}

function addSubtitle(scene: VideoScene) {
  scene.text_track.subtitle_chunks.push({ start_offset_seconds: 0, end_offset_seconds: Math.max(1, scene.end_seconds - scene.start_seconds), text: '请输入字幕' });
}

function addPause(scene: VideoScene) {
  scene.audio_track.pause_cues.push({ offset_seconds: 0, duration_seconds: 2, purpose: '留出思考时间' });
}

function enableInteraction(scene: VideoScene) {
  scene.interaction = { prompt: '请输入互动问题', wait_seconds: 2, expected_response: '请输入预期回应', feedback_transition: '请输入反馈衔接' };
}
</script>

<template>
  <div class="video-script-editor">
    <section>
      <header><span>00</span><h3>制作规格</h3></header>
      <div class="field-grid four">
        <label><span>课程名称</span><el-input v-model="model.course_info.course_title" /></label>
        <label><span>目标时长（秒）</span><el-input-number v-model="model.production_settings.target_duration_seconds" :min="1" @change="model.course_info.duration_seconds = Number($event)" /></label>
        <label><span>旁白语速（字/分钟）</span><el-input-number v-model="model.production_settings.narration_chars_per_minute" :min="120" :max="360" /></label>
        <label><span>字幕行宽</span><el-input-number v-model="model.production_settings.subtitle_max_chars_per_line" :min="8" :max="30" /></label>
      </div>
    </section>

    <section>
      <header><span>01</span><h3>结构化分镜</h3><el-button :icon="Plus" size="small" @click="addScene">拆分末尾场景</el-button></header>
      <article v-for="(scene, sceneIndex) in model.scenes" :key="scene.id" class="scene-editor-card">
        <div class="scene-title-row">
          <b>{{ String(scene.sequence).padStart(2, '0') }}</b>
          <el-input v-model="scene.id" />
          <el-input v-model="scene.title" />
          <el-select v-model="scene.pedagogical_role"><el-option v-for="role in roles" :key="role" :label="role" :value="role" /></el-select>
          <el-button :icon="Delete" text type="danger" :disabled="!canRemoveScene(scene)" @click="removeScene(sceneIndex)" />
        </div>

        <div class="field-grid four">
          <label><span>开始秒数</span><el-input-number v-model="scene.start_seconds" :min="0" :step="1" /></label>
          <label><span>结束秒数</span><el-input-number v-model="scene.end_seconds" :min="1" :step="1" /></label>
          <label><span>PPT 页面 ID</span><el-input v-model="scene.slide_id" /></label>
          <label><span>教学环节 ID</span><el-input v-model="scene.lesson_stage_id" /></label>
          <label><span>目标 ID（顿号分隔）</span><el-input :model-value="scene.objective_ids.join('、')" @input="scene.objective_ids = splitRefs(String($event))" /></label>
          <label><span>知识点 ID（顿号分隔）</span><el-input :model-value="scene.knowledge_point_ids.join('、')" @input="scene.knowledge_point_ids = splitRefs(String($event))" /></label>
        </div>
        <label class="block-field"><span>学习目的</span><el-input v-model="scene.learning_purpose" /></label>

        <div class="track-editor-grid">
          <section class="track-editor">
            <header><h4>画面与动效</h4><el-button :icon="Plus" text @click="addAnimation(scene)">添加动效</el-button></header>
            <el-input v-model="scene.visual_track.composition" type="textarea" :rows="3" />
            <div v-for="(cue, cueIndex) in scene.visual_track.animation_cues" :key="cueIndex" class="cue-editor animation">
              <el-input-number v-model="cue.offset_seconds" :min="0" :step="0.5" />
              <el-select v-model="cue.action"><el-option v-for="action in actions" :key="action" :label="action" :value="action" /></el-select>
              <el-input v-model="cue.target" placeholder="目标对象" />
              <el-input v-model="cue.instruction" placeholder="执行说明" />
              <el-button :icon="Delete" text type="danger" @click="scene.visual_track.animation_cues.splice(cueIndex, 1)" />
            </div>
          </section>

          <section class="track-editor">
            <header><h4>旁白与声音</h4><el-button :icon="Plus" text @click="addPause(scene)">添加停顿</el-button></header>
            <el-input v-model="scene.audio_track.narration_text" type="textarea" :rows="5" />
            <div class="field-grid two">
              <label><span>讲述语气</span><el-input v-model="scene.audio_track.delivery_tone" /></label>
              <label><span>强调词</span><el-input :model-value="scene.audio_track.emphasis_terms.join('、')" @input="scene.audio_track.emphasis_terms = splitRefs(String($event))" /></label>
            </div>
            <div v-for="(cue, cueIndex) in scene.audio_track.pause_cues" :key="cueIndex" class="cue-editor pause">
              <el-input-number v-model="cue.offset_seconds" :min="0" :step="0.5" />
              <el-input-number v-model="cue.duration_seconds" :min="0.5" :step="0.5" />
              <el-input v-model="cue.purpose" placeholder="停顿目的" />
              <el-button :icon="Delete" text type="danger" @click="scene.audio_track.pause_cues.splice(cueIndex, 1)" />
            </div>
          </section>

          <section class="track-editor">
            <header><h4>字幕与屏显</h4><el-button :icon="Plus" text @click="addSubtitle(scene)">添加字幕</el-button></header>
            <label class="block-field"><span>屏幕贴字（每行一项）</span><el-input :model-value="scene.text_track.on_screen_text.join('\n')" type="textarea" :rows="2" @input="scene.text_track.on_screen_text = splitLines(String($event))" /></label>
            <div v-for="(cue, cueIndex) in scene.text_track.subtitle_chunks" :key="cueIndex" class="cue-editor subtitle">
              <el-input-number v-model="cue.start_offset_seconds" :min="0" :step="0.5" />
              <el-input-number v-model="cue.end_offset_seconds" :min="0.5" :step="0.5" />
              <el-input v-model="cue.text" placeholder="字幕文本" />
              <el-button :icon="Delete" text type="danger" :disabled="scene.text_track.subtitle_chunks.length === 1" @click="scene.text_track.subtitle_chunks.splice(cueIndex, 1)" />
            </div>
          </section>

          <section class="track-editor">
            <header><h4>互动与制作备注</h4><el-button v-if="!scene.interaction" :icon="Plus" text @click="enableInteraction(scene)">添加互动</el-button><el-button v-else :icon="Delete" text type="danger" @click="scene.interaction = null">移除互动</el-button></header>
            <div v-if="scene.interaction" class="interaction-editor">
              <el-input v-model="scene.interaction.prompt" placeholder="互动问题" />
              <el-input-number v-model="scene.interaction.wait_seconds" :min="0.5" :max="30" :step="0.5" />
              <el-input v-model="scene.interaction.expected_response" placeholder="预期回应" />
              <el-input v-model="scene.interaction.feedback_transition" placeholder="反馈衔接" />
            </div>
            <label class="block-field"><span>制作备注（每行一项）</span><el-input :model-value="scene.production_notes.join('\n')" type="textarea" :rows="4" @input="scene.production_notes = splitLines(String($event))" /></label>
          </section>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.video-script-editor { display: grid; gap: 14px; }
.video-script-editor > section { padding: 16px; border: 1px solid #cfd2d9; background: #fff; }
.video-script-editor > section > header, .track-editor > header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.video-script-editor > section > header > span { color: #002fa7; font-size: 20px; font-weight: 800; }
h3, h4 { margin: 0 auto 0 0; } h3 { font-size: 15px; } h4 { font-size: 12px; color: #283750; }
.field-grid { display: grid; gap: 10px; }.field-grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }.field-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field-grid label, .block-field { display: grid; gap: 5px; }.field-grid label > span, .block-field > span { color: #656a73; font-size: 11px; font-weight: 700; }
.scene-editor-card { display: grid; gap: 12px; padding: 14px; border: 1px solid #cfd2d9; background: #f7f7f8; }.scene-editor-card + .scene-editor-card { margin-top: 12px; }
.scene-title-row { display: grid; grid-template-columns: 42px 90px minmax(180px, 1fr) 130px auto; gap: 8px; align-items: center; }.scene-title-row b { color: #002fa7; font-size: 18px; }
.track-editor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.track-editor { min-width: 0; padding: 12px; border: 1px solid #d8dde6; background: #fff; }.track-editor > header { margin-bottom: 10px; border-bottom: 1px solid #e4e7ec; padding-bottom: 8px; }
.cue-editor { display: grid; gap: 6px; align-items: center; margin-top: 8px; }.cue-editor.animation { grid-template-columns: 100px 90px minmax(100px, .7fr) minmax(140px, 1fr) auto; }.cue-editor.pause, .cue-editor.subtitle { grid-template-columns: 100px 100px minmax(130px, 1fr) auto; }
.interaction-editor { display: grid; grid-template-columns: 1fr 110px; gap: 8px; margin-bottom: 10px; }.interaction-editor > :nth-child(n+3) { grid-column: 1 / -1; }
:deep(.el-input__wrapper), :deep(.el-textarea__inner), :deep(.el-select__wrapper), :deep(.el-input-number) { border-radius: 0 !important; }.el-input-number { width: 100%; }
@media (max-width: 1000px) { .field-grid.four, .track-editor-grid { grid-template-columns: 1fr 1fr; }.scene-title-row { grid-template-columns: 42px 90px 1fr; }.scene-title-row > :nth-child(4) { grid-column: 3; } }
@media (max-width: 720px) { .field-grid.four, .field-grid.two, .track-editor-grid { grid-template-columns: 1fr; }.scene-title-row { grid-template-columns: 42px 1fr; }.scene-title-row > :nth-child(n+3) { grid-column: 2; }.cue-editor.animation, .cue-editor.pause, .cue-editor.subtitle, .interaction-editor { grid-template-columns: 1fr; }.interaction-editor > :nth-child(n+3) { grid-column: auto; } }
</style>
