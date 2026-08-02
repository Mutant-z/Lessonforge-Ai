<script setup lang="ts">
import { useRouter } from 'vue-router';
import { Plus, ArrowRight, MagicStick } from '@element-plus/icons-vue';

const router = useRouter();
</script>

<template>
  <section class="home-cta-section">
    <div class="cta-banner-card card-hover">
      <div class="cta-content">
        <div class="cta-badge">
          <el-icon><MagicStick /></el-icon>
          <span>智能备课 · 零门槛体验</span>
        </div>

        <h2 class="cta-title">
          准备好体验全新的 <span class="text-gradient">AI 智能微课开发流程</span> 了吗？
        </h2>

        <p class="cta-subtext">
          告别传统机械重复的文档与 PPT 制作。输入教学主题，由多 Agent 团队为您自动构建符合新课标的整套微课资源包。
        </p>

        <div class="cta-actions">
          <el-button 
            type="primary" 
            size="large" 
            :icon="Plus"
            class="cta-main-btn"
            @click="router.push({ path: '/login', query: { mode: 'register', redirect: '/courses/new' } })"
          >
            免费开始体验
          </el-button>

          <el-button 
            size="large" 
            class="cta-secondary-btn"
            @click="router.push('/login')"
          >
            已有账号登录
          </el-button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.home-cta-section {
  padding: 24px 24px 32px;
  max-width: 1200px;
  margin: 0 auto;
  position: relative;
  z-index: 1;
}

.cta-banner-card {
  background: linear-gradient(135deg, #ffffff 0%, #f0f2ff 50%, #eef2ff 100%);
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-hero);
  padding: 40px 32px;
  box-shadow: var(--shadow-lg);
  text-align: center;
  position: relative;
  overflow: hidden;
}

.cta-content {
  max-width: 720px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.cta-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--surface-primary);
  padding: 4px 14px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--color-primary-border);
  box-shadow: var(--shadow-xs);
  margin-bottom: 16px;
}

.cta-title {
  font-size: 38px;
  font-weight: 900;
  line-height: 1.2;
  letter-spacing: -0.03em;
  margin: 0 0 16px;
  color: var(--text-primary);
}

@media (max-width: 768px) {
  .cta-title {
    font-size: 28px;
  }
  .cta-banner-card {
    padding: 36px 20px;
  }
}

.cta-subtext {
  font-size: 16px;
  color: var(--text-secondary);
  line-height: 1.65;
  margin: 0 0 32px;
}

.cta-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.cta-main-btn {
  box-shadow: var(--shadow-glow-primary) !important;
  padding: 14px 32px !important;
  font-size: 16px !important;
}

.cta-secondary-btn {
  border-radius: var(--radius-control) !important;
  font-weight: 600 !important;
  font-size: 15px !important;
}
</style>
