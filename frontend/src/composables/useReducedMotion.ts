import { ref, onMounted, onBeforeUnmount } from 'vue';

export function useReducedMotion() {
  const prefersReducedMotion = ref(false);

  let mediaQuery: MediaQueryList | null = null;

  function updateMotionPreference() {
    if (mediaQuery) {
      prefersReducedMotion.value = mediaQuery.matches;
    }
  }

  onMounted(() => {
    if (typeof window !== 'undefined' && window.matchMedia) {
      mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
      prefersReducedMotion.value = mediaQuery.matches;
      mediaQuery.addEventListener('change', updateMotionPreference);
    }
  });

  onBeforeUnmount(() => {
    if (mediaQuery) {
      mediaQuery.removeEventListener('change', updateMotionPreference);
    }
  });

  return {
    prefersReducedMotion
  };
}
