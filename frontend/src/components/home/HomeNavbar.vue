<script setup lang="ts">
import { useRouter } from 'vue-router';
import { Plus, User, ArrowRight } from '@element-plus/icons-vue';

const router = useRouter();

function handleNavClick(targetId: string, event: Event) {
  event.preventDefault();
  const targetEl = document.getElementById(targetId);
  if (!targetEl) return;

  // 寻找滚动的容器（.landing-page-shell 或 window）
  const container = targetEl.closest('.landing-page-shell') || document.documentElement || document.body;

  if (container.classList && container.classList.contains('landing-page-shell')) {
    const containerRect = container.getBoundingClientRect();
    const targetRect = targetEl.getBoundingClientRect();
    const relativeTop = targetRect.top - containerRect.top + container.scrollTop - 70; // 扣除 70px 吸顶 Header 高度
    container.scrollTo({
      top: Math.max(0, relativeTop),
      behavior: 'smooth'
    });
  } else {
    const offsetTop = targetEl.getBoundingClientRect().top + window.pageYOffset - 70;
    window.scrollTo({
      top: Math.max(0, offsetTop),
      behavior: 'smooth'
    });
  }
}
</script>

<template>
  <header class="home-navbar bg-glass">
    <div class="navbar-container">
      <!-- Brand Logo -->
      <div class="navbar-brand" @click="router.push('/')">
        <div class="brand-logo-icon">LF</div>
        <div class="brand-text-group">
          <span class="brand-title">课启智造</span>
          <span class="brand-subtitle">LessonForge AI</span>
        </div>
      </div>

      <!-- Quick Nav Links -->
      <nav class="navbar-links">
        <a href="#features" class="nav-link" @click="handleNavClick('features', $event)">功能特色</a>
        <a href="#workflow" class="nav-link" @click="handleNavClick('workflow', $event)">Agent 流程</a>
        <a href="#resources" class="nav-link" @click="handleNavClick('resources', $event)">教学资源</a>
        <a href="#examples" class="nav-link" @click="handleNavClick('examples', $event)">示例微课</a>
      </nav>

      <!-- Auth Actions -->
      <div class="navbar-actions">
        <el-button 
          class="btn-login" 
          @click="router.push('/login')"
        >
          账号登录
        </el-button>
        <el-button 
          type="primary" 
          :icon="Plus"
          @click="router.push({ path: '/login', query: { mode: 'register', redirect: '/courses/new' } })"
        >
          免费开始使用
        </el-button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.home-navbar {
  position: sticky;
  top: 0;
  left: 0;
  right: 0;
  height: 68px;
  border-bottom: 1px solid var(--border-default);
  z-index: 1000;
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04);
}

.navbar-container {
  width: 100%;
  max-width: 1240px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.navbar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
}

.brand-logo-icon {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-card);
  background: linear-gradient(135deg, var(--primary-500) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  font-weight: 900;
  font-size: 17px;
  display: grid;
  place-items: center;
  box-shadow: var(--shadow-sm);
}

.brand-text-group {
  display: flex;
  flex-direction: column;
}

.brand-title {
  font-size: 16px;
  font-weight: 900;
  color: var(--text-primary);
  line-height: 1.2;
}

.brand-subtitle {
  font-size: 10.5px;
  color: var(--text-muted);
  letter-spacing: 0.04em;
}

.navbar-links {
  display: flex;
  align-items: center;
  gap: 28px;
}

@media (max-width: 800px) {
  .navbar-links {
    display: none;
  }
}

.nav-link {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  text-decoration: none;
  transition: color var(--motion-fast);
}

.nav-link:hover {
  color: var(--color-primary);
}

.navbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-login {
  border-radius: var(--radius-control) !important;
  font-weight: 600 !important;
}
</style>
