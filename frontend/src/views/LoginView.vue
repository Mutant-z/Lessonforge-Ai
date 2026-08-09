<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '../stores/auth';
import { errorMessage } from '../api/client';
import AmbientBackground from '../components/visual/AmbientBackground.vue';
import AuthBrandPanel from '../components/auth/AuthBrandPanel.vue';
import AuthFormCard from '../components/auth/AuthFormCard.vue';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const mode = ref<'login' | 'register'>(route.query.mode === 'register' ? 'register' : 'login');
const error = ref('');
const busy = ref(false);

function destination() {
  const value = typeof route.query.redirect === 'string' ? route.query.redirect : '/';
  return value.startsWith('/') && !value.startsWith('//') ? value : '/';
}

async function handleFormSubmit(payload: { username: string; password: string; email: string; rememberMe?: boolean }) {
  busy.value = true;
  error.value = '';
  try {
    if (mode.value === 'login') {
      await auth.login(payload.username, payload.password, payload.rememberMe ?? true);
    } else {
      await auth.register(payload.username, payload.password, payload.email);
    }
    router.push(destination());
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}

function toggleMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login';
}
</script>

<template>
  <div class="login-page-shell">
    <AmbientBackground theme="dark" />

    <div class="login-content-wrapper animate-fade-in">
      <div class="brand-side">
        <AuthBrandPanel />
      </div>

      <div class="form-side">
        <AuthFormCard 
          :mode="mode" 
          :busy="busy" 
          :error="error" 
          @submit="handleFormSubmit" 
          @toggleMode="toggleMode" 
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page-shell {
  height: 100vh;
  width: 100vw;
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px 40px;
  box-sizing: border-box;
}

.login-content-wrapper {
  width: 100%;
  max-width: 1200px;
  max-height: calc(100vh - 40px);
  display: grid;
  grid-template-columns: 56% 44%;
  align-items: center;
  position: relative;
  z-index: 10;
  height: 100%;
}

@media (max-width: 1024px) {
  .login-content-wrapper {
    grid-template-columns: 1fr;
    gap: 20px;
    height: auto;
  }
  .brand-side {
    display: none;
  }
  .form-side {
    display: flex;
    justify-content: center;
  }
}

.brand-side {
  height: 100%;
}

.form-side {
  display: flex;
  justify-content: flex-end;
  align-items: center;
}
</style>
