<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { useCourseStore } from '../../stores/courses';
import { 
  DataBoard, 
  Plus, 
  Setting, 
  Fold, 
  Expand 
} from '@element-plus/icons-vue';
import StatusBadge from '../feedback/StatusBadge.vue';

const auth = useAuthStore();
const courses = useCourseStore();
const router = useRouter();
const route = useRoute();

const isCollapsed = ref(localStorage.getItem('lf_sidebar_collapsed') === 'true');
const isCompactViewport = ref(false);
const sidebarCollapsed = computed(() => isCollapsed.value || isCompactViewport.value);
let compactViewportQuery: MediaQueryList | undefined;

function syncCompactViewport(event?: MediaQueryListEvent) {
  isCompactViewport.value = event?.matches ?? compactViewportQuery?.matches ?? false;
}

onMounted(() => {
  compactViewportQuery = window.matchMedia('(max-width: 900px)');
  syncCompactViewport();
  compactViewportQuery.addEventListener('change', syncCompactViewport);
});

onUnmounted(() => {
  compactViewportQuery?.removeEventListener('change', syncCompactViewport);
});

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
  <aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed }">
    <!-- Brand Header -->
    <div class="sidebar-brand">
      <div class="brand-logo-area" @click="navigate('/')">
        <div class="brand-logo">LF</div>
        <div v-if="!sidebarCollapsed" class="brand-meta">
          <span class="brand-name">课启智造</span>
          <span class="brand-sub">LessonForge AI</span>
        </div>
      </div>
      <el-button
        class="collapse-toggle-btn"
        link
        :icon="sidebarCollapsed ? Expand : Fold"
        :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
        @click.stop="toggleCollapse"
      />
    </div>

    <!-- Create Course Primary Action -->
    <div class="sidebar-action-row">
      <el-tooltip :disabled="!sidebarCollapsed" content="新建微课项目" placement="right">
        <button class="new-course-btn" @click="navigate('/courses/new')">
          <el-icon><Plus /></el-icon>
          <span v-if="!sidebarCollapsed">新建微课项目</span>
        </button>
      </el-tooltip>
    </div>

    <!-- Core Nav Section -->
    <div class="nav-section">
      <div v-if="!sidebarCollapsed" class="nav-section-title">核心功能</div>
      
      <el-tooltip :disabled="!sidebarCollapsed" content="工作台总览" placement="right">
        <button 
          class="nav-item" 
          :class="{ active: route.path === '/' }"
          @click="navigate('/')"
        >
          <div class="nav-item-icon"><el-icon><DataBoard /></el-icon></div>
          <span v-if="!sidebarCollapsed" class="nav-item-label">教师工作台</span>
        </button>
      </el-tooltip>

      <el-tooltip :disabled="!sidebarCollapsed" content="模型与系统偏好" placement="right">
        <button 
          class="nav-item" 
          :class="{ active: route.path === '/settings' }"
          @click="navigate('/settings')"
        >
          <div class="nav-item-icon"><el-icon><Setting /></el-icon></div>
          <span v-if="!sidebarCollapsed" class="nav-item-label">模型与偏好</span>
        </button>
      </el-tooltip>
    </div>

    <!-- Course Projects Section -->
    <div v-if="auth.user" class="nav-section course-section">
      <div v-if="!sidebarCollapsed" class="nav-section-title">
        <span>我的微课项目</span>
        <span class="course-count-tag">{{ courses.items.length }}</span>
      </div>
      
      <div v-if="!sidebarCollapsed" class="course-list-scroll">
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

@media (max-width: 900px) {
  .app-sidebar.collapsed {
    width: 64px;
    padding: 14px 8px;
  }

  .app-sidebar.collapsed .sidebar-brand {
    justify-content: center;
  }

  .app-sidebar.collapsed .brand-logo {
    width: 40px;
    height: 40px;
    font-size: 17px;
  }

  .app-sidebar.collapsed .new-course-btn,
  .app-sidebar.collapsed .nav-item {
    justify-content: center;
    padding-inline: 10px;
  }
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border-light);
  transition: all var(--motion-fast);
}

.app-sidebar.collapsed .sidebar-brand {
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding-bottom: 14px;
}

.brand-logo-area {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  min-width: 0;
  flex: 1;
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
  white-space: nowrap;
}

.brand-sub {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.collapse-toggle-btn {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 17px;
  padding: 4px;
  border-radius: var(--radius-control);
  transition: all var(--motion-fast);
}

.collapse-toggle-btn:hover {
  color: var(--color-primary);
  background: var(--bg-subtle);
}

.app-sidebar.collapsed .collapse-toggle-btn {
  margin-left: 0;
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
  font-size: 11.5px;
  font-weight: 800;
  color: #94a3b8;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 10px;
  padding: 0 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.course-count-tag {
  font-size: 11.5px;
  font-weight: 800;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  padding: 2px 8px;
  border-radius: 999px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border: 1.5px solid transparent;
  background: transparent;
  border-radius: 12px;
  color: #475569;
  font-size: 14.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
}

.nav-item-icon {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #64748b;
  display: grid;
  place-items: center;
  font-size: 16px;
  flex-shrink: 0;
  transition: all 180ms ease;
}

.nav-item:hover {
  background: #f8fafc;
  color: #0f172a;
}

.nav-item:hover .nav-item-icon {
  background: #eef2ff;
  border-color: #c7d2fe;
  color: #4f46e5;
}

.nav-item.active {
  background: linear-gradient(135deg, #f5f3ff 0%, #ffffff 100%);
  border-color: #c7d2fe;
  color: #4f46e5;
  font-weight: 800;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08);
}

.nav-item.active .nav-item-icon {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  border: 0;
  color: #ffffff;
  box-shadow: 0 3px 10px rgba(79, 70, 229, 0.3);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: -2px;
  top: 20%;
  height: 60%;
  width: 4px;
  border-radius: 999px;
  background: #4f46e5;
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
  border: 1.5px solid #e2e8f0;
  background: #ffffff;
  border-radius: 14px;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02);
}

.course-list-item:hover {
  border-color: #c7d2fe;
  background: #f8fafc;
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.06);
}

.course-list-item.selected {
  border-color: #4f46e5;
  background: linear-gradient(135deg, #f5f3ff 0%, #ffffff 100%);
  box-shadow: 0 4px 18px rgba(79, 70, 229, 0.12);
}

.course-item-title {
  font-size: 14.5px;
  font-weight: 800;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.35;
}

.course-item-info {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
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
