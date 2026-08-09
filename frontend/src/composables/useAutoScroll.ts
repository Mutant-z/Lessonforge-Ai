import { ref, onMounted, onBeforeUnmount, watch, type Ref } from 'vue';

export function useAutoScroll(containerRef: Ref<HTMLElement | null>) {
  const isAutoScrollActive = ref(true);
  const unreadCount = ref(0);
  let boundContainer: HTMLElement | null = null;
  let frameId: number | null = null;
  let lastUnreadKey = '';

  function handleScroll() {
    if (!containerRef.value) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.value;
    const distanceToBottom = scrollHeight - (scrollTop + clientHeight);

    if (distanceToBottom > 80) {
      if (isAutoScrollActive.value) {
        isAutoScrollActive.value = false;
      }
    } else {
      // User is at bottom
      isAutoScrollActive.value = true;
      unreadCount.value = 0;
      lastUnreadKey = '';
    }
  }

  function scrollToBottom(smooth = true) {
    if (!containerRef.value) return;
    if (frameId !== null) cancelAnimationFrame(frameId);
    frameId = requestAnimationFrame(() => {
      frameId = null;
      containerRef.value?.scrollTo({
        top: containerRef.value.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto'
      });
    });
    isAutoScrollActive.value = true;
    unreadCount.value = 0;
    lastUnreadKey = '';
  }

  function notifyNewContent(smooth = false, unreadKey?: string) {
    if (isAutoScrollActive.value) {
      scrollToBottom(smooth);
    } else if (!unreadKey || unreadKey !== lastUnreadKey) {
      unreadCount.value++;
      lastUnreadKey = unreadKey || '';
    }
  }

  function bindContainer(container: HTMLElement | null) {
    if (boundContainer === container) return;
    boundContainer?.removeEventListener('scroll', handleScroll);
    boundContainer = container;
    boundContainer?.addEventListener('scroll', handleScroll, { passive: true });
  }

  watch(containerRef, bindContainer, { flush: 'post' });

  onMounted(() => {
    bindContainer(containerRef.value);
  });

  onBeforeUnmount(() => {
    bindContainer(null);
    if (frameId !== null) cancelAnimationFrame(frameId);
  });

  return {
    isAutoScrollActive,
    unreadCount,
    scrollToBottom,
    notifyNewContent
  };
}
