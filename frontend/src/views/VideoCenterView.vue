<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { 
  ArrowRight, 
  CircleCheck, 
  Clock, 
  CollectionTag, 
  Cpu, 
  Edit, 
  Film, 
  Loading, 
  RefreshRight, 
  Search, 
  VideoCamera, 
  VideoPlay, 
  Warning 
} from '@element-plus/icons-vue';
import { errorMessage } from '../api/client';
import { videoProjectsApi } from '../api/videoProjects';
import type { VideoProjectStatus, VideoProjectSummary } from '../types';

const router = useRouter();
const items = ref<VideoProjectSummary[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref('');
const search = ref('');
const status = ref<VideoProjectStatus | ''>('');
const page = ref(1);
const pageSize = 20;
let refreshTimer: number | undefined;
let searchTimer: number | undefined;

const statusOptions: Array<{ value: VideoProjectStatus | ''; label: string }> = [
  { value: '', label: '全部状态' },
  { value: 'ready', label: '可生成' },
  { value: 'generating', label: '生成中' },
  { value: 'queued', label: '排队中' },
  { value: 'partial', label: '部分完成' },
  { value: 'review', label: '待确认' },
  { value: 'completed', label: '已完成' },
  { value: 'not_ready', label: '未就绪' },
  { value: 'failed', label: '生成失败' },
  { value: 'cancelled', label: '已取消' },
];

const statusLabel: Record<VideoProjectStatus, string> = Object.fromEntries(
  statusOptions.filter(item => item.value).map(item => [item.value, item.label])
) as Record<VideoProjectStatus, string>;

const counts = computed(() => ({
  total: total.value,
  active: items.value.filter(item => ['queued', 'generating'].includes(item.status)).length,
  ready: items.value.filter(item => item.status === 'ready').length,
  attention: items.value.filter(item => ['failed', 'not_ready'].includes(item.status)).length,
}));

function formatDuration(seconds: number) {
  if (!seconds) return '—';
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return minutes ? `${minutes}分${rest ? `${rest}秒` : ''}` : `${rest}秒`;
}

function actionLabel(item: VideoProjectSummary) {
  if (item.status === 'not_ready') return '准备脚本';
  if (item.status === 'ready') return '开始生成';
  if (['queued', 'generating', 'partial'].includes(item.status)) return '查看进度';
  if (item.status === 'failed') return '处理失败';
  return '查看视频';
}

function actionIcon(item: VideoProjectSummary) {
  if (item.status === 'not_ready') return Edit;
  if (item.status === 'ready') return VideoPlay;
  if (['queued', 'generating'].includes(item.status)) return Loading;
  if (item.status === 'failed') return Warning;
  return ArrowRight;
}

function filterByCard(filterType: 'all' | 'active' | 'ready' | 'attention') {
  if (filterType === 'all') {
    status.value = '';
  } else if (filterType === 'active') {
    status.value = 'generating';
  } else if (filterType === 'ready') {
    status.value = 'ready';
  } else if (filterType === 'attention') {
    status.value = 'not_ready';
  }
}

async function load(silent = false) {
  if (!silent) loading.value = true;
  error.value = '';
  try {
    const data = await videoProjectsApi.list({
      search: search.value.trim() || undefined,
      status: status.value || undefined,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    });
    items.value = data.items;
    total.value = data.total;
  } catch (cause) {
    error.value = errorMessage(cause);
  } finally {
    loading.value = false;
  }
}

watch(status, () => { page.value = 1; load(); });
watch(search, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => { page.value = 1; load(); }, 300);
});
watch(page, () => load());

onMounted(() => {
  load();
  refreshTimer = window.setInterval(() => { if (!document.hidden) load(true); }, 15_000);
});
onUnmounted(() => { 
  window.clearInterval(refreshTimer); 
  window.clearTimeout(searchTimer); 
});
</script>

<template>
  <div class="video-center-page">
    <div class="video-center-container">
      
      <!-- Top Console Header -->
      <header class="studio-header">
        <div class="header-left">
          <div class="eyebrow-line">
            <span class="eyebrow-badge">
              <el-icon><Film /></el-icon>
              <span>VIDEO GENERATION STUDIO</span>
            </span>
            <span class="eyebrow-sub">课启智造 · 视频生成中心</span>
          </div>
          <h1 class="page-title">按项目管理课程视频</h1>
          <p class="page-subtitle">
            选择微课项目后，AI 视频 Agent 将读取最新的教学蓝图、分镜脚本与项目记忆，进行视频全流程生成与分镜调优。
          </p>
        </div>

        <div class="header-right">
          <button 
            type="button" 
            class="btn-refresh" 
            :disabled="loading" 
            @click="load()"
          >
            <el-icon :class="{ 'is-loading': loading }"><RefreshRight /></el-icon>
            <span>刷新状态</span>
          </button>
        </div>
      </header>

      <!-- Interactive Metric Bento Cards -->
      <section class="metric-bento-grid">
        <div 
          class="metric-card" 
          :class="{ active: status === '' }"
          @click="filterByCard('all')"
        >
          <div class="card-icon-wrap total">
            <el-icon><Film /></el-icon>
          </div>
          <div class="card-metric-info">
            <div class="card-value">{{ counts.total }}</div>
            <div class="card-label">全部微课项目</div>
          </div>
          <span class="card-hint">收录项目总览</span>
        </div>

        <div 
          class="metric-card" 
          :class="{ active: ['generating', 'queued'].includes(status || ''), highlighted: counts.active > 0 }"
          @click="filterByCard('active')"
        >
          <div class="card-icon-wrap active-gen">
            <el-icon :class="{ 'is-loading': counts.active > 0 }"><VideoPlay /></el-icon>
          </div>
          <div class="card-metric-info">
            <div class="card-value">{{ counts.active }}</div>
            <div class="card-label">当前页生成中</div>
          </div>
          <span class="card-hint">分镜渲染 / 排队中</span>
        </div>

        <div 
          class="metric-card" 
          :class="{ active: status === 'ready' }"
          @click="filterByCard('ready')"
        >
          <div class="card-icon-wrap ready">
            <el-icon><CircleCheck /></el-icon>
          </div>
          <div class="card-metric-info">
            <div class="card-value">{{ counts.ready }}</div>
            <div class="card-label">当前页可生成</div>
          </div>
          <span class="card-hint">脚本就绪可启动</span>
        </div>

        <div 
          class="metric-card" 
          :class="{ active: status === 'not_ready', attention: counts.attention > 0 }"
          @click="filterByCard('attention')"
        >
          <div class="card-icon-wrap attention">
            <el-icon><Warning /></el-icon>
          </div>
          <div class="card-metric-info">
            <div class="card-value">{{ counts.attention }}</div>
            <div class="card-label">当前页需处理</div>
          </div>
          <span class="card-hint">脚本待完善 / 需干预</span>
        </div>
      </section>

      <!-- Filter & Search Toolbar -->
      <section class="toolbar-section">
        <div class="search-input-wrap">
          <el-icon class="search-icon"><Search /></el-icon>
          <input 
            v-model="search" 
            type="text" 
            placeholder="搜索项目名称、学科、年级..." 
            class="search-input"
          />
          <button v-if="search" class="clear-search-btn" @click="search = ''">✕</button>
        </div>

        <div class="filter-controls">
          <!-- Quick Status Tabs -->
          <div class="quick-status-tabs">
            <button 
              type="button" 
              class="tab-btn" 
              :class="{ active: status === '' }" 
              @click="status = ''"
            >
              全部
            </button>
            <button 
              type="button" 
              class="tab-btn" 
              :class="{ active: status === 'ready' }" 
              @click="status = 'ready'"
            >
              可生成
            </button>
            <button 
              type="button" 
              class="tab-btn" 
              :class="{ active: status === 'generating' }" 
              @click="status = 'generating'"
            >
              生成中
            </button>
            <button 
              type="button" 
              class="tab-btn" 
              :class="{ active: status === 'partial' }" 
              @click="status = 'partial'"
            >
              部分完成
            </button>
            <button 
              type="button" 
              class="tab-btn" 
              :class="{ active: status === 'completed' }" 
              @click="status = 'completed'"
            >
              已完成
            </button>
          </div>

          <!-- Detailed Status Select Dropdown -->
          <el-select 
            v-model="status" 
            class="status-dropdown" 
            placeholder="全部状态"
            aria-label="视频状态筛选"
          >
            <el-option 
              v-for="option in statusOptions" 
              :key="option.value" 
              :label="option.label" 
              :value="option.value" 
            />
          </el-select>
        </div>
      </section>

      <!-- Main Content Area: Error, Loading, Empty, or Project Cards -->
      <el-alert 
        v-if="error" 
        type="error" 
        :title="error" 
        show-icon 
        :closable="false"
        class="mb-4"
      >
        <template #default>
          <button class="retry-btn-link" @click="load()">重新加载</button>
        </template>
      </el-alert>

      <!-- Skeleton Loading State -->
      <div v-else-if="loading && !items.length" class="skeleton-list">
        <div v-for="i in 3" :key="i" class="skeleton-card">
          <el-skeleton animated>
            <template #template>
              <div class="skeleton-row">
                <el-skeleton-item variant="image" style="width: 52px; height: 52px; border-radius: 12px;" />
                <div style="flex: 1; padding-left: 16px;">
                  <el-skeleton-item variant="h3" style="width: 40%; height: 22px; margin-bottom: 8px;" />
                  <el-skeleton-item variant="text" style="width: 25%; height: 14px; margin-bottom: 12px;" />
                  <div style="display: flex; gap: 16px;">
                    <el-skeleton-item variant="text" style="width: 80px; height: 16px;" />
                    <el-skeleton-item variant="text" style="width: 80px; height: 16px;" />
                    <el-skeleton-item variant="text" style="width: 80px; height: 16px;" />
                  </div>
                </div>
                <el-skeleton-item variant="button" style="width: 100px; height: 38px; border-radius: 999px;" />
              </div>
            </template>
          </el-skeleton>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="!items.length" class="empty-state-box">
        <div class="empty-icon-circle">
          <el-icon><VideoCamera /></el-icon>
        </div>
        <h3>没有找到符合条件的项目</h3>
        <p>可以尝试更换搜索关键词，或者清除状态筛选条件。</p>
        <button 
          v-if="search || status" 
          type="button" 
          class="btn-reset-filter" 
          @click="search = ''; status = '';"
        >
          清除所有筛选
        </button>
      </div>

      <!-- Projects List -->
      <div v-else class="project-cards-list">
        <article 
          v-for="(item, index) in items" 
          :key="item.course.id" 
          class="project-card"
          @click="router.push(`/videos/${item.course.id}`)"
        >
          <!-- Left Visual Index / Thumbnail Indicator -->
          <div class="card-visual-col">
            <div class="card-index-pill">
              {{ String((page - 1) * pageSize + index + 1).padStart(2, '0') }}
            </div>
            <div class="card-type-icon">
              <el-icon><VideoCamera /></el-icon>
            </div>
          </div>

          <!-- Main Info Area -->
          <div class="card-content-col">
            <!-- Header Row: Title, Status Badge, Meta Tags -->
            <div class="card-header-row">
              <div class="title-and-status">
                <h2 class="course-title">{{ item.course.title }}</h2>
                <span class="status-chip" :class="item.status">
                  <span class="status-dot"></span>
                  {{ statusLabel[item.status] || item.status }}
                </span>
              </div>
              <div class="course-meta-tags">
                <span class="meta-tag">{{ item.course.subject }}</span>
                <span class="meta-dot">·</span>
                <span class="meta-tag">{{ item.course.grade_level }}</span>
                <span class="meta-dot">·</span>
                <span class="meta-tag duration"><el-icon><Clock /></el-icon> {{ item.course.duration_minutes }} 分钟</span>
              </div>
            </div>

            <!-- Deliverable & Version Metrics Strip -->
            <div class="deliverables-ribbon">
              <div class="ribbon-item">
                <span class="ribbon-label"><el-icon><Film /></el-icon> 视频脚本</span>
                <span class="ribbon-value" :class="{ empty: !item.script }">
                  {{ item.script ? `V${item.script.version}` : '未生成' }}
                </span>
              </div>
              <div class="ribbon-divider"></div>

              <div class="ribbon-item">
                <span class="ribbon-label"><el-icon><VideoCamera /></el-icon> 视频版本</span>
                <span class="ribbon-value" :class="{ empty: !item.video }">
                  {{ item.video ? `V${item.video.version}` : '—' }}
                </span>
              </div>
              <div class="ribbon-divider"></div>

              <div class="ribbon-item">
                <span class="ribbon-label"><el-icon><Cpu /></el-icon> 分镜片段</span>
                <span class="ribbon-value">
                  {{ item.scene_count ? `${item.ready_scene_count}/${item.scene_count}` : '—' }}
                </span>
              </div>
              <div class="ribbon-divider"></div>

              <div class="ribbon-item">
                <span class="ribbon-label"><el-icon><Clock /></el-icon> 成片时长</span>
                <span class="ribbon-value time">
                  {{ formatDuration(item.duration_seconds) }}
                </span>
              </div>
              <div class="ribbon-divider"></div>

              <div class="ribbon-item">
                <span class="ribbon-label"><el-icon><CollectionTag /></el-icon> 项目记忆</span>
                <span class="ribbon-value memory">
                  V{{ item.memory_revision }}
                </span>
              </div>
            </div>

            <!-- Live Progress Bar (Generating / Queued) -->
            <div 
              v-if="['queued', 'generating'].includes(item.status)" 
              class="active-progress-row"
            >
              <div class="progress-track">
                <div 
                  class="progress-fill" 
                  :style="{ width: `${Math.max(item.progress, 6)}%` }"
                ></div>
              </div>
              <div class="progress-meta">
                <span class="progress-text">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>{{ item.status === 'queued' ? '排队准备生成中...' : 'Agent 正在进行多镜头渲染与音轨合成...' }}</span>
                </span>
                <span class="progress-pct">{{ item.progress }}%</span>
              </div>
            </div>
          </div>

          <!-- Right Action CTA -->
          <div class="card-action-col">
            <button 
              type="button" 
              class="btn-card-action" 
              :class="item.status"
              @click.stop="router.push(`/videos/${item.course.id}`)"
            >
              <span>{{ actionLabel(item) }}</span>
              <el-icon><component :is="actionIcon(item)" /></el-icon>
            </button>
          </div>
        </article>
      </div>

      <!-- Pagination -->
      <div v-if="total > pageSize" class="pagination-wrap">
        <el-pagination 
          v-model:current-page="page" 
          :page-size="pageSize" 
          :total="total" 
          background
          layout="prev, pager, next, total" 
        />
      </div>

    </div>
  </div>
</template>

<style scoped>
.video-center-page {
  min-height: 100%;
  box-sizing: border-box;
  background-color: var(--bg-page, #f5f7fa);
  padding: 28px 32px 48px;
  color: var(--text-primary, #0f172a);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

.video-center-container {
  max-width: 1440px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 1. Header Console */
.studio-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-default, #e2e8f0);
}

.eyebrow-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.eyebrow-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 800;
  color: var(--primary-600, #4f46e5);
  background: var(--primary-50, #eef2ff);
  border: 1px solid var(--color-primary-border, #c7d2fe);
  padding: 3px 10px;
  border-radius: var(--radius-pill, 999px);
  letter-spacing: 0.06em;
}

.eyebrow-sub {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted, #64748b);
}

.page-title {
  margin: 0 0 6px;
  font-size: 26px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
  letter-spacing: -0.02em;
}

.page-subtitle {
  margin: 0;
  font-size: 13.5px;
  color: var(--text-secondary, #475569);
  line-height: 1.55;
  max-width: 820px;
}

.btn-refresh {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 18px;
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-control, 12px);
  color: var(--text-secondary, #334155);
  font-size: 13.5px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
  transition: all var(--motion-fast, 150ms) ease;
}

.btn-refresh:hover:not(:disabled) {
  border-color: var(--color-primary-border, #c7d2fe);
  color: var(--primary-600, #4f46e5);
  background: var(--primary-50, #eef2ff);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm, 0 4px 14px rgba(15, 23, 42, 0.05));
}

.btn-refresh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 2. Bento Stat Cards */
.metric-bento-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.metric-card {
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  position: relative;
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
  cursor: pointer;
  transition: all var(--motion-normal, 240ms) var(--ease-out-smooth, ease);
}

.metric-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-primary-border, #c7d2fe);
  box-shadow: var(--shadow-md, 0 10px 28px rgba(15, 23, 42, 0.08));
}

.metric-card.active {
  border-color: var(--primary-500, #6366f1);
  background: linear-gradient(180deg, #ffffff 0%, #f8faff 100%);
  box-shadow: 0 0 0 1px var(--primary-500, #6366f1), var(--shadow-sm, 0 4px 14px rgba(79, 70, 229, 0.08));
}

.metric-card.highlighted {
  border-color: var(--primary-300, #a5b4fc);
  background: linear-gradient(180deg, #ffffff 0%, var(--primary-50, #eef2ff) 100%);
}

.card-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 20px;
  margin-bottom: 14px;
}

.card-icon-wrap.total {
  background: #f1f5f9;
  color: #475569;
}

.card-icon-wrap.active-gen {
  background: #eef2ff;
  color: #4f46e5;
}

.card-icon-wrap.ready {
  background: #ecfdf5;
  color: #059669;
}

.card-icon-wrap.attention {
  background: #fffbeb;
  color: #d97706;
}

.card-value {
  font-size: 32px;
  font-weight: 900;
  line-height: 1;
  color: var(--text-primary, #0f172a);
  font-variant-numeric: tabular-nums;
  margin-bottom: 4px;
}

.card-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary, #334155);
}

.card-hint {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--text-muted, #64748b);
}

/* 3. Toolbar Section */
.toolbar-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.search-input-wrap {
  flex: 1;
  min-width: 280px;
  max-width: 480px;
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 14px;
  color: var(--text-muted, #94a3b8);
  font-size: 16px;
  pointer-events: none;
}

.search-input {
  width: 100%;
  height: 42px;
  padding: 0 36px 0 40px;
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-control, 12px);
  font-size: 13.5px;
  color: var(--text-primary, #0f172a);
  outline: none;
  transition: all var(--motion-fast, 150ms) ease;
}

.search-input:focus {
  border-color: var(--primary-500, #6366f1);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

.clear-search-btn {
  position: absolute;
  right: 12px;
  border: 0;
  background: #e2e8f0;
  color: #64748b;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  font-size: 10px;
  display: grid;
  place-items: center;
  cursor: pointer;
}

.filter-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.quick-status-tabs {
  display: flex;
  background: #e2e8f0;
  padding: 3px;
  border-radius: var(--radius-control, 12px);
  gap: 2px;
}

.tab-btn {
  border: 0;
  background: transparent;
  padding: 6px 14px;
  border-radius: 9px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-secondary, #475569);
  cursor: pointer;
  transition: all var(--motion-fast, 150ms) ease;
  white-space: nowrap;
}

.tab-btn:hover {
  color: var(--text-primary, #0f172a);
}

.tab-btn.active {
  background: #ffffff;
  color: var(--primary-600, #4f46e5);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.status-dropdown {
  width: 150px;
}

:deep(.status-dropdown .el-input__wrapper),
:deep(.status-dropdown .el-select__wrapper) {
  border-radius: var(--radius-control, 12px) !important;
  box-shadow: 0 0 0 1.5px var(--border-default, #e2e8f0) inset !important;
  height: 42px !important;
}

:deep(.status-dropdown .el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 2px var(--primary-500, #6366f1) inset !important;
}

/* 4. Project Cards List */
.project-cards-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.project-card {
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  padding: 16px 20px;
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  box-shadow: var(--shadow-xs, 0 1px 3px rgba(15, 23, 42, 0.05));
  cursor: pointer;
  transition: all var(--motion-fast, 150ms) var(--ease-out-smooth, ease);
}

.project-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-primary-border, #c7d2fe);
  box-shadow: var(--shadow-md, 0 10px 28px rgba(15, 23, 42, 0.08));
}

/* Visual Column */
.card-visual-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.card-index-pill {
  width: 44px;
  height: 24px;
  background: var(--primary-50, #eef2ff);
  color: var(--primary-600, #4f46e5);
  font-size: 13px;
  font-weight: 900;
  border-radius: 6px;
  display: grid;
  place-items: center;
  font-variant-numeric: tabular-nums;
  border: 1px solid var(--color-primary-border, #c7d2fe);
}

.card-type-icon {
  font-size: 16px;
  color: var(--text-muted, #94a3b8);
  display: grid;
  place-items: center;
}

/* Content Column */
.card-content-col {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.title-and-status {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.course-title {
  margin: 0;
  font-size: 16.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.course-meta-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-muted, #64748b);
}

.meta-tag {
  font-weight: 600;
}

.meta-tag.duration {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.meta-dot {
  color: #cbd5e1;
}

/* Status Chip */
.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 800;
  padding: 2.5px 9px;
  border-radius: var(--radius-pill, 999px);
  white-space: nowrap;
  line-height: 1.2;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: currentColor;
}

.status-chip.ready {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}

.status-chip.generating,
.status-chip.queued {
  background: #eef2ff;
  color: #4f46e5;
  border: 1px solid #c7d2fe;
}

.status-chip.generating .status-dot {
  animation: pulse-glow 1.5s infinite ease-in-out;
}

.status-chip.partial,
.status-chip.review {
  background: #f0f9ff;
  color: #0284c7;
  border: 1px solid #bae6fd;
}

.status-chip.completed {
  background: #f5f3ff;
  color: #7c3aed;
  border: 1px solid #ddd6fe;
}

.status-chip.failed {
  background: #fef2f2;
  color: #dc2626;
  border: 1px solid #fecaca;
}

.status-chip.not_ready,
.status-chip.cancelled {
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #e2e8f0;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.3); }
}

/* Deliverables Ribbon */
.deliverables-ribbon {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 8px 14px;
  overflow-x: auto;
}

.ribbon-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  white-space: nowrap;
}

.ribbon-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
}

.ribbon-value {
  font-size: 12.5px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
  font-variant-numeric: tabular-nums;
}

.ribbon-value.empty {
  color: #94a3b8;
  font-weight: 600;
}

.ribbon-value.time {
  color: #0284c7;
}

.ribbon-value.memory {
  color: #7c3aed;
}

.ribbon-divider {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
  flex-shrink: 0;
}

/* Active Progress Strip */
.active-progress-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
}

.progress-track {
  width: 100%;
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4f46e5 0%, #7c3aed 50%, #06b6d4 100%);
  border-radius: 999px;
  transition: width 0.3s ease;
  position: relative;
  background-size: 200% 100%;
  animation: shimmer-gradient 2s infinite linear;
}

@keyframes shimmer-gradient {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}

.progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
}

.progress-text {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--primary-600, #4f46e5);
  font-weight: 700;
}

.progress-pct {
  font-weight: 800;
  color: var(--primary-700, #4338ca);
  font-variant-numeric: tabular-nums;
}

/* Right Action Column */
.card-action-col {
  padding-left: 8px;
}

.btn-card-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-radius: var(--radius-pill, 999px);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  border: 1px solid transparent;
  white-space: nowrap;
  transition: all var(--motion-fast, 150ms) ease;
}

/* Ready / Action Button Styling */
.btn-card-action.ready {
  background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25);
}

.btn-card-action.ready:hover {
  background: linear-gradient(135deg, #4338ca 0%, #4f46e5 100%);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.35);
}

.btn-card-action.generating,
.btn-card-action.queued,
.btn-card-action.partial {
  background: var(--primary-50, #eef2ff);
  color: var(--primary-600, #4f46e5);
  border-color: var(--color-primary-border, #c7d2fe);
}

.btn-card-action.generating:hover,
.btn-card-action.queued:hover,
.btn-card-action.partial:hover {
  background: var(--primary-100, #e0e7ff);
  color: var(--primary-700, #4338ca);
  transform: translateY(-1px);
}

.btn-card-action.completed,
.btn-card-action.review {
  background: #f5f3ff;
  color: #7c3aed;
  border-color: #ddd6fe;
}

.btn-card-action.completed:hover,
.btn-card-action.review:hover {
  background: #ede9fe;
}

.btn-card-action.not_ready {
  background: #f8fafc;
  color: #475569;
  border-color: #cbd5e1;
}

.btn-card-action.not_ready:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.btn-card-action.failed {
  background: #fef2f2;
  color: #dc2626;
  border-color: #fecaca;
}

/* Empty & Skeleton States */
.empty-state-box {
  min-height: 320px;
  background: #ffffff;
  border: 1.5px dashed var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
}

.empty-icon-circle {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--primary-50, #eef2ff);
  color: var(--primary-600, #4f46e5);
  font-size: 26px;
  display: grid;
  place-items: center;
  margin-bottom: 16px;
}

.empty-state-box h3 {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary, #0f172a);
}

.empty-state-box p {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--text-muted, #64748b);
}

.btn-reset-filter {
  padding: 8px 18px;
  background: var(--surface-primary, #ffffff);
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-pill, 999px);
  color: var(--primary-600, #4f46e5);
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-reset-filter:hover {
  background: var(--primary-50, #eef2ff);
  border-color: var(--color-primary-border, #c7d2fe);
}

.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-card {
  background: #ffffff;
  border: 1.5px solid var(--border-default, #e2e8f0);
  border-radius: var(--radius-card, 16px);
  padding: 18px 20px;
}

.skeleton-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.retry-btn-link {
  margin-left: 8px;
  border: 0;
  background: transparent;
  color: #dc2626;
  font-weight: 700;
  text-decoration: underline;
  cursor: pointer;
}

.pagination-wrap {
  display: flex;
  justify-content: center;
  margin-top: 8px;
}

/* Responsive adjustments */
@media (max-width: 1024px) {
  .metric-bento-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .project-card {
    grid-template-columns: 48px minmax(0, 1fr);
  }
  .card-action-col {
    grid-column: 1 / -1;
    display: flex;
    justify-content: flex-end;
    padding-top: 8px;
    border-top: 1px solid #f1f5f9;
  }
}

@media (max-width: 768px) {
  .video-center-page {
    padding: 18px 16px 32px;
  }
  .studio-header {
    flex-direction: column;
    align-items: stretch;
  }
  .header-right {
    display: flex;
    justify-content: flex-end;
  }
  .metric-bento-grid {
    grid-template-columns: 1fr;
  }
  .toolbar-section {
    flex-direction: column;
    align-items: stretch;
  }
  .search-input-wrap {
    max-width: 100%;
  }
  .filter-controls {
    flex-direction: column;
    align-items: stretch;
  }
  .quick-status-tabs {
    overflow-x: auto;
  }
  .status-dropdown {
    width: 100%;
  }
  .deliverables-ribbon {
    flex-wrap: wrap;
    gap: 10px;
  }
  .ribbon-divider {
    display: none;
  }
}
</style>

