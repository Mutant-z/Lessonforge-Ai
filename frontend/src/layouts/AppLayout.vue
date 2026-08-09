<script setup lang="ts">
import { onMounted } from 'vue';
import { useAuthStore } from '../stores/auth';
import { useCourseStore } from '../stores/courses';
import AppSidebar from '../components/layout/AppSidebar.vue';
import AppHeader from '../components/layout/AppHeader.vue';

const auth = useAuthStore();
const courses = useCourseStore();

onMounted(async () => {
  await auth.restore();
  if (auth.user) await courses.load();
});

async function retryConnect() {
  auth.initialized = false;
  auth.retryPending = false;
  await auth.restore();
  if (auth.user) await courses.load();
}
</script>

<template>
  <div v-if="!auth.initialized" class="app-auth-loading">
    <div class="auth-loading-box">
      <div class="brand-logo-icon animate-pulse">LF</div>
      <span class="loading-text">正在恢复登录状态...</span>
    </div>
  </div>

  <div v-else-if="auth.retryPending && !auth.user" class="app-auth-loading">
    <div class="auth-loading-box">
      <div class="brand-logo-icon animate-pulse">LF</div>
      <span class="loading-text">服务器暂时无法连接，请检查服务是否已启动</span>
      <button class="retry-btn" type="button" @click="retryConnect">重新连接</button>
    </div>
  </div>

  <div v-else-if="auth.user" class="app-layout-shell">
    <AppSidebar />

    <div class="app-layout-main">
      <AppHeader />
      <main class="app-layout-content">
        <router-view v-slot="{ Component, route }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" :key="route.fullPath" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>

  <div v-else class="app-guest-shell">
    <router-view v-slot="{ Component, route }">
      <transition name="page-fade" mode="out-in">
        <component :is="Component" :key="route.fullPath" />
      </transition>
    </router-view>
  </div>
</template>

<style scoped>
.app-auth-loading {
  height: 100vh;
  width: 100vw;
  display: grid;
  place-items: center;
  background: var(--bg-page, #f8fafc);
}

.auth-loading-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.brand-logo-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  display: grid;
  place-items: center;
  font-weight: 900;
  font-size: 18px;
  box-shadow: 0 4px 16px rgba(79, 70, 229, 0.3);
}

.loading-text {
  font-size: 13px;
  font-weight: 700;
  color: #64748b;
}

.retry-btn {
  margin-top: 4px;
  padding: 6px 18px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #ffffff;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.retry-btn:hover {
  border-color: #4f46e5;
  color: #4f46e5;
}

.app-layout-shell {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: var(--bg-page);
}

.app-guest-shell {
  min-height: 100vh;
  background-color: var(--bg-page);
}

.app-layout-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100vh;
  overflow: hidden;
}

.app-layout-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
}

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity var(--motion-normal) var(--ease-out-smooth), transform var(--motion-normal) var(--ease-out-smooth);
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
