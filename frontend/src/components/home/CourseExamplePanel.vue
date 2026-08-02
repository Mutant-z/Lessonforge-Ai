<script setup lang="ts">
import { CircleCheck, DataAnalysis, Download, Document, Files, Reading } from '@element-plus/icons-vue';

const sampleCourses = [
  {
    title: '《牛顿第二定律》15分钟精讲微课',
    subject: '高中物理 · 必修一',
    score: '98.5 质检优',
    duration: '15 Min',
    items: [
      { name: '教学设计方案', format: 'DOCX', status: '已完成' },
      { name: '16:9 演示 PPT', format: 'PPTX (18页)', status: '已完成' },
      { name: '学生学习任务单', format: 'DOCX', status: '已完成' },
      { name: '梯度测试题 (含解析)', format: 'DOCX', status: '已完成' },
      { name: '视频音轨逐字稿', format: 'DOCX', status: '已完成' }
    ]
  },
  {
    title: '《Python数据分析：Pandas缺失值处理》',
    subject: '信息技术 · 拓展课',
    score: '96.8 质检优',
    duration: '12 Min',
    items: [
      { name: '教学设计方案', format: 'DOCX', status: '已完成' },
      { name: '16:9 演示 PPT', format: 'PPTX (14页)', status: '已完成' },
      { name: '代码导学任务单', format: 'DOCX', status: '已完成' },
      { name: '课后巩固练习', format: 'DOCX', status: '已完成' },
      { name: '教师讲稿与代码段', format: 'DOCX', status: '已完成' }
    ]
  }
];
</script>

<template>
  <section class="course-example-section">
    <div class="section-header">
      <span class="section-eyebrow">READY-TO-USE OUTPUT</span>
      <h2 class="section-title">真实示例：<span class="text-gradient-cyan">直接交付课堂使用</span></h2>
      <p class="section-subtext">通过统一蓝图把控质量，每个 Agent 产出的资源均可直接编辑导出。</p>
    </div>

    <div class="examples-grid">
      <div 
        v-for="(course, index) in sampleCourses" 
        :key="index"
        class="example-card card-hover"
      >
        <div class="example-card-header">
          <div class="title-meta">
            <span class="course-subject">{{ course.subject }}</span>
            <h3 class="course-title">{{ course.title }}</h3>
          </div>
          <div class="score-badge">
            <el-icon><DataAnalysis /></el-icon>
            <span>{{ course.score }}</span>
          </div>
        </div>

        <div class="example-resources-list">
          <div 
            v-for="(item, i) in course.items" 
            :key="i"
            class="resource-row"
          >
            <div class="res-info">
              <el-icon class="check-icon"><CircleCheck /></el-icon>
              <span class="res-name">{{ item.name }}</span>
            </div>
            <div class="res-right">
              <span class="res-format">{{ item.format }}</span>
              <span class="res-status">{{ item.status }}</span>
            </div>
          </div>
        </div>

        <div class="example-card-footer">
          <span class="duration-text">标准微课时长：{{ course.duration }}</span>
          <div class="package-btn">
            <el-icon><Download /></el-icon>
            <span>打包下载资源 (.ZIP)</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.course-example-section {
  padding: 32px 0 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.section-header {
  text-align: center;
  max-width: 640px;
  margin-bottom: 24px;
}

.section-eyebrow {
  font-size: 12px;
  font-weight: 800;
  color: var(--accent-cyan);
  letter-spacing: 0.12em;
}

.section-title {
  font-size: 36px;
  font-weight: 900;
  line-height: 1.2;
  margin: 10px 0 14px;
  color: var(--text-primary);
}

.section-subtext {
  font-size: 15px;
  color: var(--text-secondary);
}

.examples-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
  width: 100%;
  max-width: 1200px;
}

@media (max-width: 900px) {
  .examples-grid {
    grid-template-columns: 1fr;
  }
}

.example-card {
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-panel);
  padding: 28px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.example-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.course-subject {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-primary);
}

.course-title {
  margin: 4px 0 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--text-primary);
}

.score-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-mint);
  background: var(--accent-mint-soft);
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  flex-shrink: 0;
}

.example-resources-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 24px;
}

.resource-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--surface-secondary);
  border-radius: var(--radius-card);
}

.res-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.check-icon {
  color: var(--accent-mint);
  font-size: 16px;
}

.res-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.res-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.res-format {
  font-size: 11px;
  color: var(--text-muted);
}

.res-status {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent-mint);
}

.example-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
}

.duration-text {
  font-size: 12px;
  color: var(--text-muted);
}

.package-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--color-primary);
  cursor: pointer;
}

.package-btn:hover {
  text-decoration: underline;
}
</style>
