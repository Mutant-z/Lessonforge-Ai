<script setup lang="ts">
import type { VideoPedagogicalRole, VideoScriptContent } from '../../types';

const model = defineModel<VideoScriptContent>({ required: true });
const roles: VideoPedagogicalRole[] = ['导入','目标','情境','概念讲解','示范','练习','检查点','总结','过渡'];
const split = (value: string) => value.split(/\n|、|,/).map(item => item.trim()).filter(Boolean);

function updateDuration(index: number, duration: number) {
  let cursor = 0;
  model.value.scenes.forEach((scene, i) => {
    const length = i === index ? duration : scene.end_seconds - scene.start_seconds;
    scene.start_seconds = cursor;
    scene.end_seconds = cursor + Math.max(4, Math.min(15, length));
    cursor = scene.end_seconds;
  });
  model.value.production_settings.target_duration_seconds = cursor;
  model.value.course_info.duration_seconds = Math.round(cursor);
}
</script>

<template>
  <div class="script-editor">
    <header><div><span>SEEDANCE SCRIPT V3</span><h2>原生有声片段设计</h2></div><p>每个片段都是独立计费、可复用和可重生的完整音视频单元。</p></header>
    <section class="global-fields">
      <label><span>全片视觉说明</span><el-input v-model="model.production_settings.global_visual_style" type="textarea" :rows="3" /></label>
      <label><span>统一教师声音</span><el-input v-model="model.production_settings.global_voice_direction" type="textarea" :rows="3" /></label>
    </section>
    <section class="scenes">
      <article v-for="(scene,index) in model.scenes" :key="scene.id">
        <header><b>{{ scene.id }}</b><el-input v-model="scene.title" /><el-select v-model="scene.pedagogical_role"><el-option v-for="role in roles" :key="role" :label="role" :value="role" /></el-select><el-input-number :model-value="scene.end_seconds-scene.start_seconds" :min="4" :max="15" @update:model-value="(value: number | undefined) => updateDuration(index, Number(value))" /></header>
        <div class="fields">
          <label class="wide"><span>画面提示词</span><el-input v-model="scene.visual_prompt" type="textarea" :rows="4" /></label>
          <label class="wide"><span>原生口播原文</span><el-input v-model="scene.spoken_text" type="textarea" :rows="4" /></label>
          <label><span>连续性分组</span><el-input v-model="scene.continuity_group" /></label>
          <label><span>声音指导</span><el-input v-model="scene.voice_direction" /></label>
          <label><span>必需术语</span><el-input :model-value="scene.required_terms.join('、')" @update:model-value="(value: string) => scene.required_terms=split(value)" /></label>
          <label><span>必需数字/单位</span><el-input :model-value="scene.required_numbers.join('、')" @update:model-value="(value: string) => scene.required_numbers=split(value)" /></label>
          <label class="wide"><span>教学事实（每行一项）</span><el-input :model-value="scene.required_facts.join('\n')" type="textarea" :rows="3" @update:model-value="(value: string) => scene.required_facts=split(value)" /></label>
          <label class="wide"><span>禁止内容</span><el-input :model-value="scene.negative_constraints.join('、')" type="textarea" :rows="2" @update:model-value="(value: string) => scene.negative_constraints=split(value)" /></label>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.script-editor{padding:22px;color:#111318;background:#f5f5f3;font-family:Helvetica Neue,Helvetica,Arial,sans-serif}.script-editor>header{display:flex;justify-content:space-between;gap:24px;padding:20px;border:1px solid #b9bdc5;background:#fff}.script-editor>header span,.fields label>span,.global-fields label>span{color:#002fa7;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.script-editor h2{margin:6px 0 0}.script-editor>header p{max-width:430px;margin:0;color:#656a73;font-size:12px;line-height:1.6}.global-fields{display:grid;grid-template-columns:1fr 1fr;margin-top:12px;border:1px solid #b9bdc5;background:#fff}.global-fields label{display:grid;gap:6px;padding:16px}.global-fields label+label{border-left:1px solid #d9dbe0}.scenes{display:grid;gap:12px;margin-top:12px}.scenes article{border:1px solid #b9bdc5;background:#fff}.scenes article>header{display:grid;grid-template-columns:70px 1fr 130px 120px;gap:8px;align-items:center;padding:11px;border-bottom:1px solid #d9dbe0}.scenes article>header b{color:#002fa7}.fields{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:16px}.fields label{display:grid;gap:6px}.fields .wide{grid-column:1/-1}:deep(.el-input__wrapper),:deep(.el-textarea__inner),:deep(.el-select__wrapper),:deep(.el-input-number){border-radius:0!important}.el-input-number{width:100%}@media(max-width:800px){.global-fields,.fields{grid-template-columns:1fr}.global-fields label+label{border-left:0;border-top:1px solid #d9dbe0}.scenes article>header{grid-template-columns:60px 1fr}.fields .wide{grid-column:auto}}
</style>
