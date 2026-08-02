<script setup lang="ts">
import { useRouter } from 'vue-router';
import HeroBadge from '../visual/HeroBadge.vue';
import AgentWorkflowDemo from './AgentWorkflowDemo.vue';
import { Plus, ArrowRight, Check, Select, MagicStick, Collection } from '@element-plus/icons-vue';

const router = useRouter();
</script>

<template>
  <section class="home-hero-section">
    <div class="hero-container">
      <!-- Left Content Column -->
      <div class="hero-left-col">
        <HeroBadge badge="多 Agent 协作" text="LessonForge AI 教学微课 AI 深度开发平台" />

        <h1 class="hero-main-title">
          从一个教学主题，<br>
          <span class="text-gradient">到整套精雕细琢的微课资源。</span>
        </h1>

        <p class="hero-description">
          基于统一课程蓝图事实源，由教学设计、16:9 PPT 课件、学习任务单、梯度练习、视频脚本与教师逐字稿专属 Agent 深度并行生成。
        </p>

        <div class="hero-cta-group">
          <el-button 
            type="primary" 
            size="large" 
            :icon="Plus"
            class="cta-primary-btn"
            @click="router.push({ path: '/login', query: { mode: 'register', redirect: '/courses/new' } })"
          >
            免费开始使用
          </el-button>

          <el-button 
            size="large" 
            class="cta-secondary-btn"
            @click="router.push({ path: '/login', query: { redirect: '/courses/new' } })"
          >
            已有账号登录
          </el-button>
        </div>

        <!-- Trust & Value Badges Below CTA -->
        <div class="hero-trust-bar">
          <div class="trust-item">
            <el-icon class="check-ic"><Select /></el-icon>
            <span>符合新课标规范</span>
          </div>
          <div class="trust-item">
            <el-icon class="check-ic"><Select /></el-icon>
            <span>标准 16:9 PPTX 导出</span>
          </div>
          <div class="trust-item">
            <el-icon class="check-ic"><Select /></el-icon>
            <span>质量巡检 Agent 校验</span>
          </div>
        </div>
      </div>

      <!-- Right Multi-Agent Interactive Workstation Demo -->
      <div class="hero-right-col">
        <AgentWorkflowDemo />
      </div>
    </div>
  </section>
</template>

<style scoped>
.home-hero-section {
  padding: 36px 0 24px;
  position: relative;
  z-index: 1;
}

.hero-container {
  width: 100%;
  max-width: 1240px;
  margin: 0 auto;
  padding: 0 24px;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 48px;
  align-items: center;
}

@media (max-width: 1024px) {
  .hero-container {
    grid-template-columns: 1fr;
    gap: 40px;
  }
}

.hero-left-col {
  display: flex;
  flex-direction: column;
}

.hero-main-title {
  font-size: 52px;
  font-weight: 900;
  line-height: 1.12;
  letter-spacing: -0.04em;
  margin: 20px 0 24px;
  color: var(--text-primary);
}

@media (max-width: 1280px) {
  .hero-main-title {
    font-size: 44px;
  }
}

.hero-description {
  font-size: 17px;
  line-height: 1.75;
  color: var(--text-secondary);
  margin: 0 0 36px;
  max-width: 560px;
}

.hero-cta-group {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 32px;
}

.cta-primary-btn {
  box-shadow: var(--shadow-glow-primary) !important;
  font-size: 16px !important;
  padding: 14px 28px !important;
}

.cta-secondary-btn {
  border-radius: var(--radius-control) !important;
  font-weight: 600 !important;
  font-size: 15px !important;
}

.hero-trust-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--border-default);
}

@media (max-width: 640px) {
  .hero-trust-bar {
    flex-wrap: wrap;
    gap: 12px;
  }
}

.trust-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-secondary);
}

.check-ic {
  color: var(--accent-mint);
  font-size: 14px;
}
</style>
