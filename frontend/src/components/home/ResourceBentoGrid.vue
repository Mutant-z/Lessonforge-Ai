<script setup lang="ts">
import { 
  Document, 
  Files, 
  List, 
  EditPen, 
  VideoCamera, 
  Microphone, 
  CircleCheck, 
  ArrowRight,
  Checked
} from '@element-plus/icons-vue';

const resources = [
  {
    key: 'design',
    name: '教学设计方案',
    tag: 'DOCX / 规范教学案',
    color: 'cyan',
    icon: Document,
    bentoSpan: 'col-2',
    description: '自动对齐新课标与三维教学目标，输出导入、新授、探究、总结全环节规范案。',
    snippetTitle: '《牛顿第二定律》教学设计节选',
    snippetLines: [
      '【教学目标】理解加速度与作用力的正比关系及质量的反比关系',
      '【核心素养】科学思维：构建 F=ma 理想模型与物理量推导',
      '【教学重难点】实验数据归纳与矢量性理解'
    ]
  },
  {
    key: 'ppt',
    name: '16:9 PPT 课件',
    tag: 'PPTX / 矢量排版',
    color: 'violet',
    icon: Files,
    bentoSpan: 'col-1',
    description: '内置高颜值微课模板，自动生成幻灯片结构与视觉提炼。',
    snippetTitle: 'Slide 03 / 探究实验设计',
    snippetItem: '小车质量 M 保持恒定，改变拉力 F 测定加速度 a'
  },
  {
    key: 'task',
    name: '学习任务单',
    tag: 'DOCX / 导学卡',
    color: 'mint',
    icon: List,
    bentoSpan: 'col-1',
    description: '配套课堂互动导学单，引导学生自主探究与思考记录。',
    snippetTitle: '任务一：数据记录表',
    snippetItem: '填写 Hooke 法则与 Hooke 弹簧拉力测量值'
  },
  {
    key: 'exercise',
    name: '分层梯度练习',
    tag: 'DOCX / 梯度解析',
    color: 'amber',
    icon: EditPen,
    bentoSpan: 'col-1',
    description: '基础巩固、能力提升与拓展迁移三阶题目，带详细答题解析。',
    snippetTitle: '【能力提升题】',
    snippetItem: '如图所示，质量为 m 的物体在斜面上滑行...'
  },
  {
    key: 'verbatim',
    name: '教师逐字稿',
    tag: 'DOCX / 提词器模式',
    color: 'rose',
    icon: Microphone,
    bentoSpan: 'col-1',
    description: '实时生成授课口述文稿，可直接一键开启提词器模式。',
    snippetTitle: '微课讲稿 / 01:15',
    snippetItem: '“同学们，前面我们学习了物体的运动规律...”'
  },
  {
    key: 'script',
    name: '视频录制脚本',
    tag: 'DOCX / 画面与音轨',
    color: 'primary',
    icon: VideoCamera,
    bentoSpan: 'col-2',
    description: '15分钟微课分秒级音视频脚本，明确分屏画面、动画提示与讲解语音。',
    snippetTitle: '02:30 - 04:15 [画面：打点计时器实验动画]',
    snippetItem: '教师解说：大家注意看纸带上的点距变化，当拉力加倍时...'
  },
  {
    key: 'quality',
    name: '多维度质量巡检',
    tag: 'Agent / 自动合规',
    color: 'mint',
    icon: Checked,
    bentoSpan: 'col-1',
    description: '基于 20+ 教学规范规则自动校验格式、错字与蓝图一致性。',
    snippetTitle: '合规性巡检结论',
    snippetItem: '✔ 目标对齐度 99% · 无知识点脱节'
  }
];
</script>

<template>
  <section id="resources" class="bento-resources-section">
    <div class="section-header">
      <span class="section-eyebrow">FULL-STACK RESOURCES</span>
      <h2 class="section-title">一套课程蓝图，<span class="text-gradient">全套交付级教学资源。</span></h2>
      <p class="section-subtext">不再需要跨多个工具来回复制粘贴，多 Agent 协作同时输出全环节教学配套。</p>
    </div>

    <div class="bento-grid-container">
      <div 
        v-for="res in resources" 
        :key="res.key"
        class="bento-card card-hover"
        :class="[res.bentoSpan, res.color]"
      >
        <div class="bento-card-top">
          <div class="icon-badge">
            <component :is="res.icon" />
          </div>
          <span class="res-tag">{{ res.tag }}</span>
        </div>

        <h3 class="res-name">{{ res.name }}</h3>
        <p class="res-desc">{{ res.description }}</p>

        <!-- Unique Card Content Preview Snippet -->
        <div class="res-snippet-box">
          <div class="snippet-header">
            <span class="snippet-dot"></span>
            <span class="snippet-title">{{ res.snippetTitle }}</span>
          </div>

          <div v-if="res.snippetLines" class="snippet-multiline">
            <p v-for="(line, idx) in res.snippetLines" :key="idx">{{ line }}</p>
          </div>
          <div v-else-if="res.snippetItem" class="snippet-single">
            <p>{{ res.snippetItem }}</p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.bento-resources-section {
  padding: 36px 0 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.section-header {
  text-align: center;
  max-width: 680px;
  margin-bottom: 28px;
}

.section-eyebrow {
  font-size: 12px;
  font-weight: 800;
  color: var(--color-primary);
  letter-spacing: 0.12em;
}

.section-title {
  font-size: 38px;
  font-weight: 900;
  line-height: 1.18;
  letter-spacing: -0.03em;
  margin: 12px 0 16px;
  color: var(--text-primary);
}

.section-subtext {
  font-size: 16px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.bento-grid-container {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  width: 100%;
  max-width: 1200px;
}

@media (max-width: 1024px) {
  .bento-grid-container {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .bento-grid-container {
    grid-template-columns: 1fr;
  }
  .bento-card.col-2 {
    grid-column: span 1;
  }
}

.bento-card {
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-panel);
  padding: 28px;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-sm);
  position: relative;
  overflow: hidden;
}

.bento-card.col-2 {
  grid-column: span 2;
}

@media (max-width: 1024px) {
  .bento-card.col-2 {
    grid-column: span 2;
  }
}

.bento-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.icon-badge {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-card);
  display: grid;
  place-items: center;
  font-size: 22px;
}

.cyan .icon-badge { background: var(--accent-cyan-soft); color: var(--accent-cyan); }
.violet .icon-badge { background: var(--accent-violet-soft); color: var(--accent-violet); }
.mint .icon-badge { background: var(--accent-mint-soft); color: var(--accent-mint); }
.amber .icon-badge { background: var(--accent-amber-soft); color: var(--accent-amber); }
.rose .icon-badge { background: var(--accent-rose-soft); color: var(--accent-rose); }
.primary .icon-badge { background: var(--color-primary-soft); color: var(--color-primary); }

.res-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  background: var(--surface-secondary);
  color: var(--text-secondary);
  border: 1px solid var(--border-light);
}

.res-name {
  font-size: 20px;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.res-desc {
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin: 0 0 20px;
}

.res-snippet-box {
  margin-top: auto;
  padding: 14px 16px;
  background: var(--surface-secondary);
  border-radius: var(--radius-card);
  border: 1px dashed var(--border-default);
}

.snippet-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.snippet-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
}

.snippet-title {
  font-size: 11.5px;
  font-weight: 700;
  color: var(--text-primary);
}

.snippet-multiline p, .snippet-single p {
  margin: 4px 0;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}
</style>
