<script setup lang="ts">
import { onMounted } from 'vue';
import { useAuthStore } from '../stores/auth';
import { useCourseStore } from '../stores/courses';
import AppSidebar from '../components/layout/AppSidebar.vue';
import AppHeader from '../components/layout/AppHeader.vue';
import TaskCenterDrawer from '../components/layout/TaskCenterDrawer.vue';

const auth = useAuthStore();
const courses = useCourseStore();

onMounted(async () => {
  await auth.restore();
  if (auth.user) await courses.load();
});
</script>

<template>
  <div v-if="auth.user" class="app-layout-shell">
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

    <TaskCenterDrawer />
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
