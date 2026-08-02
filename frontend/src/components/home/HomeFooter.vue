<script setup lang="ts">
</script>

<template>
  <footer class="home-footer">
    <div class="footer-container">
      <div class="footer-brand">
        <div class="brand-logo-icon">LF</div>
        <div class="brand-info">
          <span class="brand-title">课启智造 LessonForge AI</span>
          <p class="brand-desc">多 Agent 协作微课 AI 深度开发平台，为教师打造高质量教学资源包。</p>
        </div>
      </div>

      <div class="footer-links-group">
        <div class="footer-col">
          <h4>核心能力</h4>
          <span>统一课程蓝图</span>
          <span>多 Agent 并发推理</span>
          <span>质量巡检 Agent</span>
          <span>16:9 PPTX 导出</span>
        </div>

        <div class="footer-col">
          <h4>教学资源</h4>
          <span>教学设计方案</span>
          <span>互动学习任务单</span>
          <span>梯度练习与解析</span>
          <span>视频脚本与逐字稿</span>
        </div>

        <div class="footer-col">
          <h4>服务保障</h4>
          <span>符合新课标规范</span>
          <span>支持标准 DOCX/PPTX</span>
          <span>本地打包 ZIP 下载</span>
          <span>教师编辑掌控</span>
        </div>
      </div>
    </div>

    <div class="footer-bottom">
      <span>© 2026 LessonForge AI · 课启智造 多 Agent 教学微课 AI 开发平台. All rights reserved.</span>
    </div>
  </footer>
</template>

<style scoped>
.home-footer {
  background: var(--surface-dark);
  color: var(--text-on-dark);
  padding: 36px 0 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  position: relative;
  z-index: 10;
}

.footer-container {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px 40px;
  display: flex;
  justify-content: space-between;
  gap: 40px;
}

@media (max-width: 800px) {
  .footer-container {
    flex-direction: column;
  }
}

.footer-brand {
  display: flex;
  gap: 16px;
  max-width: 360px;
}

.brand-logo-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-card);
  background: linear-gradient(135deg, var(--primary-500) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  font-weight: 900;
  font-size: 18px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.brand-title {
  font-size: 16px;
  font-weight: 800;
  color: #ffffff;
}

.brand-desc {
  font-size: 13px;
  color: var(--text-on-dark-muted);
  line-height: 1.6;
  margin-top: 6px;
}

.footer-links-group {
  display: flex;
  gap: 60px;
}

@media (max-width: 600px) {
  .footer-links-group {
    flex-wrap: wrap;
    gap: 30px;
  }
}

.footer-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.footer-col h4 {
  font-size: 13px;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 4px;
}

.footer-col span {
  font-size: 12.5px;
  color: var(--text-on-dark-muted);
}

.footer-bottom {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 24px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  text-align: center;
  font-size: 12px;
  color: var(--text-on-dark-muted);
}
</style>
