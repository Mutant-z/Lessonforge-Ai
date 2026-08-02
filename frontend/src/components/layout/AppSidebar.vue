<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { useCourseStore } from '../../stores/courses';
import { useTaskCenterStore } from '../../stores/taskCenter';
import { 
  DataBoard, 
  Plus, 
  Cpu, 
  Setting, 
  Fold, 
  Expand 
} from '@element-plus/icons-vue';
import StatusBadge from '../feedback/StatusBadge.vue';

const auth = useAuthStore();
const courses = useCourseStore();
const taskCenter = useTaskCenterStore();
const router = useRouter();
const route = useRoute();

const isCollapsed = ref(localStorage.getItem('lf_sidebar_collapsed') === 'true');

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value;
  localStorage.setItem('lf_sidebar_collapsed', String(isCollapsed.value));
}

function navigate(path: string) {
  if (route.path === path) return;
  if (auth.user) {
    router.push(path);
  } else {
    router.push({ path: '/login', query: { redirect: path } });
  }
}
</script>

<template>
  <aside class="app-sidebar" :class="{ collapsed: isCollapsed }">
    <!-- Brand Header -->
    <div class="sidebar-brand" @click="navigate('/')">
      <div class="brand-logo">LF</div>
      <div v-if="!isCollapsed" class="brand-meta">
        <span class="brand-name">课启智造</span>
        <span class="brand-sub">LessonForge AI</span>
      </div>
      <el-button
        v-if="!isCollapsed"
        class="collapse-toggle-btn"
        link
        :icon="Fold"
        @click.stop="toggleCollapse"
      />
    </div>

    <!-- Create Course Primary Action -->
    <div class="sidebar-action-row">
      <el-tooltip :disabled="!isCollapsed" content="新建微课项目" placement="right">
        <button class="new-course-btn" @click="navigate('/courses/new')">
          <el-icon><Plus /></el-icon>
          <span v-if="!isCollapsed">新建微课项目</span>
        </button>
      </el-tooltip>
    </div>

    <!-- Core Nav Section -->
    <div class="nav-section">
      <div v-if="!isCollapsed" class="nav-section-title">核心功能</div>
      
      <el-tooltip :disabled="!isCollapsed" content="工作台总览" placement="right">
        <button 
          class="nav-item" 
          :class="{ active: route.path === '/' }"
          @click="navigate('/')"
        >
          <el-icon><DataBoard /></el-icon>
          <span v-if="!isCollapsed">教师工作台</span>
        </button>
      </el-tooltip>

      <el-tooltip :disabled="!isCollapsed" content="Agent 任务中心" placement="right">
        <button 
          class="nav-item" 
          :class="{ active: taskCenter.isDrawerOpen }"
          @click="taskCenter.toggleDrawer()"
        >
          <el-icon><Cpu /></el-icon>
          <span v-if="!isCollapsed">Agent 任务中心</span>
          <span v-if="!isCollapsed && taskCenter.runningCount > 0" class="nav-badge">{{ taskCenter.runningCount }}</span>
        </button>
      </el-tooltip>

      <el-tooltip :disabled="!isCollapsed" content="模型与系统偏好" placement="right">
        <button 
          class="nav-item" 
          :class="{ active: route.path === '/settings' }"
          @click="navigate('/settings')"
        >
          <el-icon><Setting /></el-icon>
          <span v-if="!isCollapsed">模型与偏好</span>
        </button>
      </el-tooltip>
    </div>

    <!-- Course Projects Section -->
    <div v-if="auth.user" class="nav-section course-section">
      <div v-if="!isCollapsed" class="nav-section-title">
        <span>我的微课项目</span>
        <span class="course-count-tag">{{ courses.items.length }}</span>
      </div>
      
      <div v-if="!isCollapsed" class="course-list-scroll">
        <button
          v-for="course in courses.items"
          :key="course.id"
          class="course-list-item"
          :class="{ selected: route.params.id === course.id }"
          @click="navigate(`/courses/${course.id}/project`)"
        >
          <div class="course-item-main">
            <span class="course-item-title">{{ course.title }}</span>
            <span class="course-item-info">{{ course.subject }} · {{ course.duration_minutes }}分钟</span>
          </div>
          <StatusBadge :status="course.status" size="small" />
        </button>
      </div>
    </div>

    <!-- Sidebar Footer with Connection & Version info -->
    <div class="sidebar-footer">
      <el-button
        v-if="isCollapsed"
        class="expand-bottom-toggle-btn"
        link
        :icon="Expand"
        @click="toggleCollapse"
      />
      <div v-else class="footer-meta-block">
        <div class="model-status-indicator">
          <span class="status-dot green"></span>
          <span>大模型就绪 (DeepSeek/GPT-4o)</span>
        </div>
        <span class="version-text">LessonForge AI v1.2 · 多 Agent 平台</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  position: sticky;
  top: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  transition: width var(--motion-normal) var(--ease-out-smooth);
  z-index: 30;
  padding: 22px 16px;
}

.app-sidebar.collapsed {
  width: var(--sidebar-collapsed-width);
  padding: 22px 10px;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border-light);
}

.brand-logo {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-card);
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #fff;
  font-weight: 900;
  font-size: 19px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  box-shadow: var(--shadow-sm);
}

.brand-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.brand-name {
  font-size: 17.5px;
  font-weight: 900;
  color: var(--text-primary);
}

.brand-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.collapse-toggle-btn {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 16px;
}

.sidebar-action-row {
  margin: 18px 0;
}

.new-course-btn {
  width: 100%;
  padding: 13px;
  border: 0;
  border-radius: var(--radius-control);
  background: var(--color-primary);
  color: #fff;
  font-weight: 700;
  font-size: 15px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: background var(--motion-fast);
  box-shadow: var(--shadow-glow-primary);
}

.new-course-btn:hover {
  background: var(--color-primary-hover);
}

.nav-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 18px;
}

.nav-section-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--text-muted);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-bottom: 12px;
  padding: 0 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.course-count-tag {
  font-size: 12px;
  font-weight: 700;
  background: var(--surface-tertiary);
  color: var(--text-secondary);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border: 0;
  background: transparent;
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--motion-fast);
  position: relative;
}

.nav-item:hover {
  background: var(--bg-subtle);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 700;
}

.nav-badge {
  margin-left: auto;
  font-size: 12px;
  font-weight: 800;
  background: var(--color-primary);
  color: #ffffff;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}

.course-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.course-list-scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.course-list-item {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid var(--border-default);
  background: var(--bg-surface);
  border-radius: var(--radius-control);
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all var(--motion-fast);
}

.course-list-item:hover {
  border-color: var(--border-active);
  background: var(--bg-page);
  transform: translateX(2px);
}

.course-list-item.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.course-item-title {
  font-size: 14.5px;
  font-weight: 800;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.course-item-info {
  font-size: 13px;
  color: var(--text-muted);
}

.sidebar-footer {
  padding-top: 14px;
  border-top: 1px solid var(--border-light);
}

.footer-meta-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.model-status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 600;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot.green {
  background: var(--accent-mint);
  box-shadow: 0 0 8px var(--accent-mint);
}

.version-text {
  font-size: 12px;
  color: var(--text-muted);
}

</style>
