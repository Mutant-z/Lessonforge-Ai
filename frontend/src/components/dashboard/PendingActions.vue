<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useCourseStore } from '../../stores/courses';
import { Bell, ArrowRight, CircleCheck, Warning } from '@element-plus/icons-vue';

const store = useCourseStore();
const router = useRouter();

const pendingItems = computed(() => {
  const list: any[] = [];
  store.items.forEach(course => {
    if (['blueprint_review', 'teacher_review'].includes(course.status)) {
      list.push({
        id: course.id,
        title: course.title,
        type: 'blueprint',
        tag: '待确认蓝图',
        desc: `${course.subject} · 统一课程蓝图等待教师核对评测`,
        target: `/courses/${course.id}/blueprint`
      });
    } else if (course.status === 'draft' || course.status === 'requirement_review') {
      list.push({
        id: course.id,
        title: course.title,
        type: 'draft',
        tag: '草稿待完善',
        desc: `${course.subject} · 尚未启动 Agent 并发资源生成`,
        target: `/courses/${course.id}/workspace`
      });
    } else if (course.status === 'needs_attention' || course.status === 'failed') {
      list.push({
        id: course.id,
        title: course.title,
        type: 'attention',
        tag: '需教师干预',
        desc: `${course.subject} · 部分生成环节需人工核对`,
        target: `/courses/${course.id}/workspace`
      });
    }
  });
  return list;
});
</script>

<template>
  <div class="pending-actions-bento-card">
    <div class="card-header-compact">
      <div class="header-left">
        <div class="icon-wrap amber">
          <el-icon><Bell /></el-icon>
        </div>
        <div class="header-text">
          <h3 class="card-title">待办与核对中心</h3>
          <span class="sub-text">需要教师确认与审核的微课阶段</span>
        </div>
      </div>
      <span v-if="pendingItems.length" class="pending-count">{{ pendingItems.length }} 项待办</span>
      <span v-else class="done-count">已全处理</span>
    </div>

    <div v-if="!pendingItems.length" class="empty-pending-compact">
      <el-icon class="check-done-ic"><CircleCheck /></el-icon>
      <span>所有蓝图与微课任务已确认完毕，暂无待办</span>
    </div>

    <div v-else class="pending-list-scroll">
      <div 
        v-for="item in pendingItems" 
        :key="item.id" 
        class="pending-row card-hover"
        @click="router.push(item.target)"
      >
        <div class="row-main">
          <div class="title-line">
            <span class="type-badge" :class="item.type">{{ item.tag }}</span>
            <h4 class="item-title" :title="item.title">{{ item.title }}</h4>
          </div>
          <p class="item-desc">{{ item.desc }}</p>
        </div>

        <el-button type="primary" size="small" link class="action-link">
          <span>处理</span>
          <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pending-actions-bento-card {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  padding: 16px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-xs);
  transition: border-color var(--motion-fast);
}

.pending-actions-bento-card:hover {
  border-color: var(--border-active);
}

.card-header-compact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.icon-wrap {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-control);
  display: grid;
  place-items: center;
  font-size: 16px;
  flex-shrink: 0;
}

.icon-wrap.amber {
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
}

.header-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
}

.sub-text {
  font-size: 12px;
  color: var(--text-muted);
}

.pending-count {
  font-size: 12px;
  font-weight: 800;
  color: var(--accent-amber);
  background: var(--accent-amber-soft);
  padding: 3px 9px;
  border-radius: var(--radius-pill);
}

.done-count {
  font-size: 12px;
  font-weight: 800;
  color: var(--accent-mint);
  background: var(--accent-mint-soft);
  padding: 3px 9px;
  border-radius: var(--radius-pill);
}

.empty-pending-compact {
  padding: 16px 12px;
  background: var(--surface-secondary);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
}

.check-done-ic {
  font-size: 18px;
  color: var(--accent-mint);
}

.pending-list-scroll {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 2px;
}

.pending-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--surface-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-control);
  cursor: pointer;
  transition: all var(--motion-fast);
}

.pending-row:hover {
  background: var(--surface-primary);
  border-color: var(--color-primary-border);
  transform: translateX(2px);
}

.row-main {
  flex: 1;
  min-width: 0;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
}

.type-badge {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
}

.type-badge.blueprint {
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
}

.type-badge.draft {
  background: var(--surface-tertiary);
  color: var(--text-secondary);
}

.type-badge.attention {
  background: var(--accent-rose-soft);
  color: var(--accent-rose);
}

.item-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 800;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-desc {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.action-link {
  font-weight: 800 !important;
  font-size: 12.5px !important;
  flex-shrink: 0;
  margin-left: 8px;
}
</style>


