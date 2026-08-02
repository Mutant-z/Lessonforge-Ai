<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { useCourseStore } from '../../stores/courses';
import { useTaskCenterStore } from '../../stores/taskCenter';
import { 
  Plus, 
  Cpu, 
  User, 
  Setting, 
  SwitchButton, 
  Search,
  Check
} from '@element-plus/icons-vue';

const auth = useAuthStore();
const courses = useCourseStore();
const taskCenter = useTaskCenterStore();
const router = useRouter();
const route = useRoute();

const searchQuery = ref('');

const currentCourseTitle = computed(() => courses.current?.title);

const reviewPendingCount = computed(() => {
  return courses.items.filter(x => ['blueprint_review', 'teacher_review'].includes(x.status)).length;
});

function handleCommand(cmd: string) {
  if (cmd === 'settings') router.push('/settings');
  if (cmd === 'logout') auth.logout();
}

function handleSearch() {
  if (searchQuery.value.trim()) {
    router.push({ path: '/', query: { search: searchQuery.value } });
  }
}
</script>

<template>
  <header class="app-header bg-glass">
    <!-- Header Left: Breadcrumb & Page Context -->
    <div class="header-left">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item :to="{ path: '/' }">
          <span class="bc-home">{{ auth.user ? '教师工作台' : 'LessonForge AI' }}</span>
        </el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentCourseTitle">
          <span class="bc-course">{{ currentCourseTitle }}</span>
        </el-breadcrumb-item>
        <el-breadcrumb-item v-else-if="route.path === '/courses/new'">
          <span class="bc-curr">新建微课项目</span>
        </el-breadcrumb-item>
        <el-breadcrumb-item v-else-if="route.path === '/settings'">
          <span class="bc-curr">系统偏好设置</span>
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <!-- Header Middle: Global Search & Save Status -->
    <div class="header-center">
      <div class="search-input-box">
        <el-input
          v-model="searchQuery"
          placeholder="搜索课程、学科、知识点或资源..."
          :prefix-icon="Search"
          clearable
          size="large"
          @keyup.enter="handleSearch"
        />
      </div>

      <div class="save-status-indicator">
        <el-icon class="save-ic"><Check /></el-icon>
        <span>已实时云同步</span>
      </div>
    </div>

    <!-- Header Right: Tasks, Notifications & User Menu -->
    <div class="header-right">
      <!-- Human Review Pending Hint -->
      <div 
        v-if="reviewPendingCount > 0" 
        class="review-pending-pill animate-fade-in"
        @click="router.push('/')"
      >
        <span class="review-amber-dot"></span>
        <span>{{ reviewPendingCount }} 个项目待处理</span>
      </div>

      <!-- Background Agent Tasks Indicator -->
      <div 
        v-if="taskCenter.runningCount > 0" 
        class="task-indicator-btn animate-fade-in"
        @click="taskCenter.toggleDrawer()"
      >
        <span class="task-ping-dot animate-pulse"></span>
        <span class="task-count-text">{{ taskCenter.runningCount }} 个 Agent 任务运行中</span>
      </div>

      <!-- User Logged In Actions -->
      <template v-if="auth.user">
        <el-button type="primary" size="large" :icon="Plus" @click="router.push('/courses/new')">
          新建微课
        </el-button>

        <el-dropdown trigger="click" @command="handleCommand">
          <div class="user-avatar-trigger">
            <div class="avatar-circle">{{ auth.user.username.charAt(0).toUpperCase() }}</div>
            <span class="user-name-text">{{ auth.user.username }}</span>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="settings" :icon="Setting">模型与系统设置</el-dropdown-item>
              <el-dropdown-item divided command="logout" :icon="SwitchButton">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </template>

      <!-- Guest Actions -->
      <template v-else>
        <el-button size="large" @click="router.push('/login')">登录</el-button>
        <el-button size="large" type="primary" @click="router.push({ path: '/login', query: { mode: 'register' } })">
          免费注册
        </el-button>
      </template>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  height: var(--header-height);
  border-bottom: 1px solid var(--border-default);
  padding: 0 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 20;
  gap: 20px;
}

.header-left {
  display: flex;
  align-items: center;
}

.bc-home {
  font-weight: 800;
  font-size: 14.5px;
  color: var(--text-primary);
}

.bc-course {
  font-weight: 800;
  font-size: 14.5px;
  color: var(--color-primary);
}

.bc-curr {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-secondary);
}

.header-center {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  max-width: 520px;
}

@media (max-width: 1024px) {
  .header-center {
    display: none;
  }
}

.search-input-box {
  width: 100%;
}

.save-status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-muted);
  white-space: nowrap;
  font-weight: 600;
}

.save-ic {
  color: var(--accent-mint);
  font-size: 14px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.review-pending-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: var(--accent-amber-soft);
  border: 1px solid rgba(217, 119, 6, 0.3);
  border-radius: var(--radius-pill);
  cursor: pointer;
  font-size: 13px;
  font-weight: 800;
  color: var(--accent-amber);
}

.review-amber-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent-amber);
}

.task-indicator-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: var(--color-primary-soft);
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-pill);
  cursor: pointer;
  font-size: 13px;
  font-weight: 800;
  color: var(--color-primary);
  transition: transform var(--motion-fast);
}

.task-indicator-btn:hover {
  transform: translateY(-1px);
}

.task-ping-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-primary);
}

.user-avatar-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 5px 10px;
  border-radius: var(--radius-pill);
  transition: background var(--motion-fast);
}

.user-avatar-trigger:hover {
  background: var(--bg-hover);
}

.avatar-circle {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #fff;
  font-weight: 900;
  font-size: 15px;
  display: grid;
  place-items: center;
}

.user-name-text {
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary);
}
</style>
