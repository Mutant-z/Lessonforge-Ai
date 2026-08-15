<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { useCourseStore } from '../../stores/courses';
import { 
  Plus, 
  Setting, 
  SwitchButton, 
  Search,
  Check,
  ArrowDown
} from '@element-plus/icons-vue';

const auth = useAuthStore();
const courses = useCourseStore();
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
          <span class="bc-home" :class="{ 'is-active-root': route.path === '/' }">{{ auth.user ? '教师工作台' : 'LessonForge AI' }}</span>
        </el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentCourseTitle && route.path.startsWith('/courses/') && route.path !== '/courses/new'">
          <span class="bc-course">{{ currentCourseTitle.length > 18 ? currentCourseTitle.slice(0, 18) + '...' : currentCourseTitle }}</span>
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
          size="default"
          @keyup.enter="handleSearch"
        />
      </div>

      <div v-if="!currentCourseTitle" class="save-status-indicator">
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

      <!-- User Logged In Actions -->
      <template v-if="auth.user">
        <el-button type="primary" size="default" class="btn-create-header" :icon="Plus" @click="router.push('/courses/new')">
          新建微课
        </el-button>

        <el-dropdown trigger="click" popper-class="user-dropdown-popper" @command="handleCommand">
          <div class="user-avatar-trigger">
            <div class="avatar-circle">{{ auth.user.username.charAt(0).toUpperCase() }}</div>
            <span class="user-name-text">{{ auth.user.username }}</span>
            <el-icon class="arrow-down-ic"><ArrowDown /></el-icon>
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
        <el-button size="default" @click="router.push('/login')">登录</el-button>
        <el-button size="default" type="primary" @click="router.push({ path: '/login', query: { mode: 'register' } })">
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
  background: #fff7ed;
  border: 1.5px solid #fed7aa;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 800;
  color: #c2410c;
  box-shadow: 0 2px 8px rgba(249, 115, 22, 0.1);
  transition: all 180ms ease;
}

.review-pending-pill:hover {
  background: #ffedd5;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(249, 115, 22, 0.18);
}

.review-amber-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #ea580c;
  box-shadow: 0 0 6px #ea580c;
}

.btn-create-header {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
  color: #ffffff !important;
  border: 0 !important;
  border-radius: 999px !important;
  font-size: 13.5px !important;
  font-weight: 800 !important;
  padding: 8px 18px !important;
  box-shadow: 0 3px 12px rgba(79, 70, 229, 0.28) !important;
  transition: all 180ms ease !important;
}

.btn-create-header:hover {
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 18px rgba(79, 70, 229, 0.38) !important;
}

.user-avatar-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 14px 4px 4px;
  border-radius: 999px;
  background: #f1f5f9;
  border: 1.5px solid #e2e8f0;
  transition: all 180ms ease;
}

.user-avatar-trigger:hover {
  background: #ffffff;
  border-color: #a5b4fc;
  box-shadow: 0 3px 12px rgba(79, 70, 229, 0.1);
}

.avatar-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #ffffff;
  font-weight: 900;
  font-size: 14px;
  display: grid;
  place-items: center;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.25);
}

.user-name-text {
  font-size: 13.5px;
  font-weight: 800;
  color: #0f172a;
}

.arrow-down-ic {
  font-size: 12px;
  color: #64748b;
  transition: transform 180ms ease;
}

.user-avatar-trigger:hover .arrow-down-ic {
  color: #4f46e5;
  transform: translateY(1px);
}

@media (max-width: 600px) {
  .app-header {
    padding: 0 12px;
    justify-content: flex-end;
    gap: 8px;
  }

  .header-left,
  .review-pending-pill,
  .user-name-text {
    display: none;
  }

  .header-right {
    gap: 8px;
  }

  .user-avatar-trigger {
    padding: 3px;
  }

  .avatar-circle {
    width: 32px;
    height: 32px;
  }
}
</style>

<style>
/* 全局浮层: 用户下拉菜单高质感 Popover 样式 */
.el-dropdown-menu.user-dropdown-popper,
.user-dropdown-popper .el-dropdown-menu {
  border-radius: 14px !important;
  border: 1.5px solid #e2e8f0 !important;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12) !important;
  padding: 6px !important;
  background: #ffffff !important;
}

.user-dropdown-popper .el-dropdown-menu__item {
  border-radius: 10px !important;
  font-size: 13.5px !important;
  font-weight: 700 !important;
  padding: 9px 14px !important;
  color: #334155 !important;
  gap: 8px !important;
  transition: all 150ms ease !important;
}

.user-dropdown-popper .el-dropdown-menu__item:hover {
  background: #f8fafc !important;
  color: #4f46e5 !important;
}

.user-dropdown-popper .el-dropdown-menu__item .el-icon {
  font-size: 15px !important;
  color: #64748b !important;
}

.user-dropdown-popper .el-dropdown-menu__item:hover .el-icon {
  color: #4f46e5 !important;
}

.user-dropdown-popper .el-dropdown-menu__item--divided {
  border-top: 1px solid #f1f5f9 !important;
  margin-top: 4px !important;
  padding-top: 9px !important;
  color: #dc2626 !important;
}

.user-dropdown-popper .el-dropdown-menu__item--divided:hover {
  background: #fef2f2 !important;
  color: #dc2626 !important;
}

.user-dropdown-popper .el-dropdown-menu__item--divided:hover .el-icon {
  color: #dc2626 !important;
}
</style>
