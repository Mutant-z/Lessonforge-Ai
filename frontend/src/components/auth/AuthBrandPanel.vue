<script setup lang="ts">
import { useRouter } from 'vue-router';
import AuthAgentPreview from './AuthAgentPreview.vue';
import { Check } from '@element-plus/icons-vue';

const router = useRouter();
</script>

<template>
  <div class="auth-brand-panel">
    <!-- Top Brand Logo -->
    <div class="brand-top-row" @click="router.push('/')">
      <div class="logo-box">LF</div>
      <div class="brand-meta">
        <span class="brand-name">课启智造</span>
        <span class="brand-sub">LessonForge AI</span>
      </div>
    </div>

    <!-- Main Hero Text & Agent Preview -->
    <div class="brand-main-content">
      <div class="hero-text-block">
        <div class="badge-row">
          <span class="pill-tag">多 Agent 教学微课 AI 深度开发平台</span>
        </div>

        <h1 class="hero-headline">
          从统一课程蓝图<br>
          <span class="gradient-text-light">到整套交付级微课资源。</span>
        </h1>

        <p class="hero-subtext">
          告别单一 GPT 对话的低效碎片输出。由教学设计、PPT、任务单、练习与脚本专属 Agent 并行生成。
        </p>
      </div>

      <!-- Live Agent Stack Preview -->
      <AuthAgentPreview />
    </div>

    <!-- Foot Trust Tags -->
    <div class="brand-foot-tags">
      <span class="trust-tag"><el-icon><Check /></el-icon> 教学设计.docx</span>
      <span class="trust-tag"><el-icon><Check /></el-icon> 16:9 PPT.pptx</span>
      <span class="trust-tag"><el-icon><Check /></el-icon> 学习任务单</span>
      <span class="trust-tag"><el-icon><Check /></el-icon> 视频脚本&逐字稿</span>
    </div>
  </div>
</template>

<style scoped>
.auth-brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 24px 36px;
  height: 100%;
  box-sizing: border-box;
  color: #ffffff;
  position: relative;
  z-index: 1;
}

.brand-top-row {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  width: fit-content;
}

.logo-box {
  width: 42px;
  height: 42px;
  border-radius: var(--radius-card);
  background: linear-gradient(135deg, var(--primary-500) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  font-weight: 900;
  font-size: 19px;
  display: grid;
  place-items: center;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.45);
}

.brand-meta {
  display: flex;
  flex-direction: column;
}

.brand-name {
  font-size: 18px;
  font-weight: 900;
  color: #ffffff;
}

.brand-sub {
  font-size: 11px;
  color: #a5b4fc;
}

.brand-main-content {
  margin: 16px 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 520px;
}

.pill-tag {
  font-size: 12px;
  font-weight: 800;
  color: #818cf8;
  background: rgba(129, 140, 248, 0.15);
  border: 1px solid rgba(129, 140, 248, 0.3);
  padding: 4px 12px;
  border-radius: var(--radius-pill);
}

.hero-headline {
  font-size: 36px;
  font-weight: 900;
  line-height: 1.18;
  letter-spacing: -0.03em;
  margin: 10px 0 10px;
}

.gradient-text-light {
  background: linear-gradient(135deg, #a5b4fc 0%, #c084fc 50%, #38bdf8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtext {
  font-size: 14px;
  line-height: 1.6;
  color: #cbd5e1;
  margin: 0;
}

.brand-foot-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
}

.trust-tag {
  font-size: 12.5px;
  font-weight: 700;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 5px;
}
</style>
