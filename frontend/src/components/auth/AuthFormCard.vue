<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { User, Lock, Message, Back } from '@element-plus/icons-vue';

const props = defineProps<{
  mode: 'login' | 'register';
  busy: boolean;
  error: string;
}>();

const emit = defineEmits<{
  (e: 'submit', data: { username: string; password: string; email: string; rememberMe: boolean }): void;
  (e: 'toggleMode'): void;
}>();

const router = useRouter();
const username = ref('');
const password = ref('');
const email = ref('');
const rememberMe = ref(true);

function handleSubmit() {
  emit('submit', {
    username: username.value,
    password: password.value,
    email: email.value,
    rememberMe: rememberMe.value
  });
}
</script>

<template>
  <div class="auth-form-floating-card card-hover">
    <div class="card-top-nav">
      <el-button link class="back-btn" :icon="Back" @click="router.push('/')">
        返回首页
      </el-button>
      <div class="brand-mini-tag">
        <span class="mini-logo">LF</span>
        <span>LessonForge AI</span>
      </div>
    </div>

    <div class="form-header">
      <span class="mode-capsule">{{ mode === 'login' ? '教师验证登录' : '体验账号注册' }}</span>
      <h2 class="form-title">{{ mode === 'login' ? '欢迎回到 LessonForge AI' : '开启 AI 智能备课之旅' }}</h2>
      <p class="form-subtext">基于多 Agent 统一蓝图，快速打造整套教学微课资源包。</p>
    </div>

    <form class="auth-form" @submit.prevent="handleSubmit">
      <div class="field-group">
        <label for="input-username">用户名</label>
        <el-input 
          id="input-username"
          v-model="username" 
          placeholder="请输入用户名" 
          size="large" 
          :prefix-icon="User"
          required 
          minlength="3" 
        />
      </div>

      <div v-if="mode === 'register'" class="field-group">
        <label for="input-email">电子邮箱 (可选)</label>
        <el-input 
          id="input-email"
          v-model="email" 
          type="email" 
          placeholder="teacher@school.edu.cn" 
          size="large" 
          :prefix-icon="Message"
        />
      </div>

      <div class="field-group">
        <label for="input-password">密码</label>
        <el-input 
          id="input-password"
          v-model="password" 
          type="password" 
          placeholder="请输入密码" 
          size="large" 
          :prefix-icon="Lock"
          show-password 
          required 
          minlength="6" 
        />
      </div>

      <div v-if="mode === 'login'" class="form-options-row">
        <el-checkbox v-model="rememberMe" label="记住登录状态" />
        <span class="forgot-hint">忘记密码联系管理员</span>
      </div>

      <el-alert v-if="error" type="error" :title="error" show-icon class="error-alert" />

      <el-button 
        type="primary" 
        size="large" 
        class="submit-btn" 
        native-type="submit" 
        :loading="busy"
      >
        {{ busy ? '正在验证...' : mode === 'login' ? '登录并进入工作台' : '免费注册并体验' }}
      </el-button>

      <div class="mode-switch-footer">
        <button type="button" class="switch-btn" @click="emit('toggleMode')">
          {{ mode === 'login' ? '首次使用 LessonForge AI？点击创建新账号' : '已有教师账号？点击直接登录' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.auth-form-floating-card {
  width: 100%;
  max-width: 440px;
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-panel);
  padding: 30px 32px;
  box-shadow: var(--shadow-floating);
  position: relative;
  z-index: 10;
  box-sizing: border-box;
}

.card-top-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.back-btn {
  color: var(--text-muted);
  font-size: 13.5px;
  font-weight: 600;
}

.back-btn:hover {
  color: var(--color-primary);
}

.brand-mini-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 800;
  color: var(--text-secondary);
}

.mini-logo {
  width: 22px;
  height: 22px;
  border-radius: var(--radius-xs);
  background: var(--color-primary);
  color: #ffffff;
  font-size: 11.5px;
  display: grid;
  place-items: center;
}

.form-header {
  margin-bottom: 20px;
}

.mode-capsule {
  font-size: 12px;
  font-weight: 800;
  color: var(--color-primary);
  background: var(--surface-emphasis);
  padding: 3px 10px;
  border-radius: var(--radius-pill);
}

.form-title {
  font-size: 25px;
  font-weight: 900;
  color: var(--text-primary);
  line-height: 1.25;
  margin: 10px 0 6px;
}

.form-subtext {
  font-size: 13.5px;
  color: var(--text-muted);
  margin: 0;
  line-height: 1.5;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field-group label {
  display: block;
  font-size: 13px;
  font-weight: 800;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.form-options-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
}

.forgot-hint {
  color: var(--text-muted);
}

.submit-btn {
  width: 100%;
  margin-top: 4px;
  height: 46px !important;
  font-size: 15.5px !important;
  border-radius: var(--radius-control) !important;
  box-shadow: var(--shadow-glow-primary) !important;
}

.error-alert {
  border-radius: var(--radius-control);
}

.mode-switch-footer {
  text-align: center;
  margin-top: 4px;
}

.switch-btn {
  background: transparent;
  border: 0;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--motion-fast);
  font-weight: 600;
}

.switch-btn:hover {
  color: var(--color-primary);
  text-decoration: underline;
}
</style>
