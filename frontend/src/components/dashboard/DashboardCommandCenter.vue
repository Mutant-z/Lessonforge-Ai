<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { 
  MagicStick, 
  Paperclip, 
  ArrowRight, 
  Bell, 
  CircleCheck,
  VideoPlay
} from '@element-plus/icons-vue';

const props = defineProps<{
  pendingItems: Array<{
    id: string;
    title: string;
    type: string;
    tag: string;
    desc: string;
    target: string;
  }>;
  recentCourse?: {
    id: string;
    title: string;
  } | null;
  startingIntake: boolean;
}>();

const emit = defineEmits<{
  (e: 'submitIntake', prompt: string, files: File[]): void;
}>();

const router = useRouter();
const promptInput = ref('');
const attachedFiles = ref<File[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);

function triggerFileInput() {
  fileInputRef.value?.click();
}

function handleFileSelected(event: Event) {
  const target = event.target as HTMLInputElement;
  if (target.files && target.files.length) {
    attachedFiles.value = [...attachedFiles.value, ...Array.from(target.files)];
  }
}

function removeFile(index: number) {
  attachedFiles.value.splice(index, 1);
}

function applyExampleChip(text: string) {
  promptInput.value = text;
}

function handleSubmit() {
  if (!promptInput.value.trim() || props.startingIntake) return;
  emit('submitIntake', promptInput.value.trim(), attachedFiles.value);
}
</script>

<template>
  <div class="command-center-row">
    <!-- Left: AI Command Composer (70% Width) -->
    <div class="composer-card">
      <div class="composer-header">
        <div class="composer-title-wrap">
          <div class="composer-icon"><el-icon><MagicStick /></el-icon></div>
          <div>
            <h3 class="composer-heading">想制作什么微课？</h3>
            <p class="composer-sub">描述教学主题、授课对象、课程时长与重点，AI 将自动构建全套教学资源。</p>
          </div>
        </div>

        <button 
          v-if="recentCourse" 
          type="button" 
          class="resume-course-btn"
          @click="router.push(`/courses/${recentCourse.id}/workspace`)"
        >
          <el-icon><VideoPlay /></el-icon>
          <span>继续编辑：{{ recentCourse.title.length > 12 ? recentCourse.title.slice(0, 12) + '...' : recentCourse.title }}</span>
        </button>
      </div>

      <!-- Main Input Box -->
      <div class="composer-input-area">
        <textarea 
          v-model="promptInput"
          class="composer-textarea"
          rows="3"
          placeholder="例如：为高一学生制作一节 15 分钟的《牛顿第二定律：加速度与合外力关系》微课，包含实验引导与考点精讲..."
          @keydown.enter.prevent="handleSubmit"
        ></textarea>

        <!-- Attached Files Pill List (If Any) -->
        <div v-if="attachedFiles.length" class="attached-files-row">
          <span 
            v-for="(file, idx) in attachedFiles" 
            :key="idx" 
            class="file-pill"
          >
            <el-icon><Paperclip /></el-icon>
            <span class="file-name">{{ file.name }}</span>
            <button type="button" class="remove-file-btn" @click="removeFile(idx)">×</button>
          </span>
        </div>

        <div class="composer-actions-bar">
          <div class="composer-tools">
            <input 
              ref="fileInputRef" 
              type="file" 
              multiple 
              accept=".pdf,.doc,.docx,.ppt,.pptx,.txt,.png,.jpg" 
              style="display: none;" 
              @change="handleFileSelected" 
            />
            <button type="button" class="tool-btn" @click="triggerFileInput">
              <el-icon><Paperclip /></el-icon>
              <span>+ 添加材料 (PDF / Word / PPT)</span>
            </button>
          </div>

          <button 
            type="button" 
            class="composer-submit-btn"
            :disabled="!promptInput.trim() || startingIntake"
            @click="handleSubmit"
          >
            <span>AI 极速生成</span>
            <el-icon><ArrowRight /></el-icon>
          </button>
        </div>
      </div>

      <!-- Prompt Chips Row -->
      <div class="example-chips-row">
        <span class="chips-label">快捷示例：</span>
        <button type="button" class="chip-item" @click="applyExampleChip('高一物理《牛顿第二定律：加速度与合外力关系》，15分钟互动课')">
          牛顿第二定律
        </button>
        <button type="button" class="chip-item" @click="applyExampleChip('初中数学《勾股定理及其实际应用》，探究式教学')">
          勾股定理
        </button>
        <button type="button" class="chip-item" @click="applyExampleChip('高中化学《氧化还原反应核心规律与配平技巧》')">
          氧化还原反应
        </button>
      </div>
    </div>

    <!-- Right: Action Center / Pending Tasks (30% Width) -->
    <div class="action-center-card">
      <div class="action-header">
        <div class="action-header-left">
          <div class="action-icon warning"><el-icon><Bell /></el-icon></div>
          <div class="action-title-wrap">
            <h4 class="action-heading">今日待处理</h4>
            <span class="action-sub">需要教师核对与确认事项</span>
          </div>
        </div>

        <span v-if="pendingItems.length" class="pending-badge warning">{{ pendingItems.length }} 项</span>
        <span v-else class="pending-badge success">已清空</span>
      </div>

      <!-- Empty Actions -->
      <div v-if="!pendingItems.length" class="empty-actions-state">
        <el-icon class="done-check-ic"><CircleCheck /></el-icon>
        <span>当前所有微课蓝图与任务已处理完毕</span>
      </div>

      <!-- Pending List -->
      <div v-else class="pending-items-list">
        <div 
          v-for="item in pendingItems.slice(0, 2)" 
          :key="item.id" 
          class="pending-card-item"
          @click="router.push(item.target)"
        >
          <div class="pending-item-main">
            <div class="pending-tag-row">
              <span class="type-pill" :class="item.type">{{ item.tag }}</span>
            </div>
            <h5 class="pending-item-title" :title="item.title">{{ item.title }}</h5>
            <p class="pending-item-desc">{{ item.desc }}</p>
          </div>

          <button type="button" class="pending-action-btn">
            <span>立即处理</span>
            <el-icon><ArrowRight /></el-icon>
          </button>
        </div>

        <button 
          v-if="pendingItems.length > 2" 
          type="button" 
          class="view-more-pending-btn"
          @click="router.push(pendingItems[0].target)"
        >
          查看全部 {{ pendingItems.length }} 项待处理 →
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.command-center-row {
  display: flex;
  gap: 16px;
  flex-shrink: 0;
}

/* Composer Card (Left 70%) */
.composer-card {
  flex: 7;
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 12px 18px;
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.composer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.composer-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.composer-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, var(--color-primary-soft) 0%, var(--accent-violet-soft) 100%);
  color: var(--color-primary);
  display: grid;
  place-items: center;
  font-size: 17px;
  flex-shrink: 0;
  box-shadow: var(--shadow-xs);
}

.composer-heading {
  margin: 0;
  font-size: 17px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
}

.composer-sub {
  margin: 1px 0 0;
  font-size: 12.5px;
  color: var(--text-muted);
}

.resume-course-btn {
  border: 1px solid var(--color-primary-border);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: var(--radius-pill);
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--motion-fast);
}

.resume-course-btn:hover {
  background: var(--color-primary);
  color: #ffffff;
}

/* Textarea Input Container */
.composer-input-area {
  background: var(--surface-secondary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-control);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all var(--motion-fast);
}

.composer-input-area:focus-within {
  background: var(--surface-primary);
  border-color: var(--color-primary);
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.08);
}

.composer-textarea {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  resize: none;
  min-height: 52px;
  max-height: 80px;
  line-height: 1.45;
}

.attached-files-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.file-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
}

.file-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remove-file-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 13px;
  padding: 0 2px;
}
.remove-file-btn:hover { color: var(--danger); }

.composer-actions-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 4px;
  border-top: 1px solid var(--border-light);
}

.tool-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 3px 6px;
  border-radius: var(--radius-sm);
  transition: all var(--motion-fast);
}

.tool-btn:hover {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.composer-submit-btn {
  border: none;
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--accent-violet) 100%);
  color: #ffffff;
  padding: 6px 16px;
  border-radius: var(--radius-control);
  font-size: 13.5px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  box-shadow: var(--shadow-glow-primary);
  transition: all var(--motion-fast);
}

.composer-submit-btn:hover:not(:disabled) {
  opacity: 0.94;
  transform: translateY(-1px);
}

.composer-submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

/* Prompt Chips Row */
.example-chips-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.chips-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
}

.chip-item {
  border: 1px solid var(--border-default);
  background: var(--surface-secondary);
  color: var(--text-secondary);
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.chip-item:hover {
  border-color: var(--color-primary-border);
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

/* Action Center Card (Right 30%) */
.action-center-card {
  flex: 3;
  background: var(--surface-primary);
  border: 1.5px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 12px 16px;
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.action-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.action-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-icon.warning {
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
  display: grid;
  place-items: center;
  font-size: 16px;
}

.action-heading {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
}

.action-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.pending-badge.warning {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--accent-amber-soft);
  color: var(--accent-amber);
  border: 1px solid rgba(217, 119, 6, 0.2);
}

.pending-badge.success {
  font-size: 11px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--accent-mint-soft);
  color: var(--accent-mint);
}

.empty-actions-state {
  padding: 16px 12px;
  background: var(--surface-secondary);
  border: 1.5px dashed var(--border-default);
  border-radius: var(--radius-control);
  color: var(--text-muted);
  font-size: 12.5px;
  font-weight: 600;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  text-align: center;
}

.done-check-ic {
  font-size: 20px;
  color: var(--accent-mint);
}

.pending-items-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pending-card-item {
  background: var(--surface-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-control);
  padding: 8px 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  transition: all var(--motion-fast);
}

.pending-card-item:hover {
  background: var(--surface-primary);
  border-color: var(--color-primary-border);
  transform: translateX(2px);
  box-shadow: var(--shadow-xs);
}

.pending-item-main {
  flex: 1;
  min-width: 0;
}

.pending-tag-row {
  margin-bottom: 2px;
}

.type-pill {
  font-size: 11px;
  font-weight: 800;
  padding: 1px 6px;
  border-radius: var(--radius-pill);
}
.type-pill.blueprint { background: var(--accent-amber-soft); color: var(--accent-amber); }
.type-pill.draft { background: var(--surface-tertiary); color: var(--text-secondary); }
.type-pill.failed { background: var(--color-danger-soft); color: var(--danger); }

.pending-item-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 800;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pending-item-desc {
  margin: 1px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pending-action-btn {
  border: none;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--motion-fast);
}

.pending-card-item:hover .pending-action-btn {
  background: var(--color-primary);
  color: #ffffff;
}

.view-more-pending-btn {
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  text-align: center;
  padding: 2px;
}

@media (max-width: 1024px) {
  .command-center-row {
    flex-direction: column;
  }
}
</style>
