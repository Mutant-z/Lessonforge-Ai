import { ref, onMounted, onBeforeUnmount, type Ref } from 'vue';

export function useAutoScroll(containerRef: Ref<HTMLElement | null>) {
  const isAutoScrollActive = ref(true);
  const unreadCount = ref(0);

  function handleScroll() {
    if (!containerRef.value) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.value;
    const distanceToBottom = scrollHeight - (scrollTop + clientHeight);

    // If user scrolled up by more than 40px, pause auto-scroll
    if (distanceToBottom > 40) {
      if (isAutoScrollActive.value) {
        isAutoScrollActive.value = false;
      }
    } else {
      // User is at bottom
      isAutoScrollActive.value = true;
      unreadCount.value = 0;
    }
  }

  function scrollToBottom(smooth = true) {
    if (!containerRef.value) return;
    containerRef.value.scrollTo({
      top: containerRef.value.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    });
    isAutoScrollActive.value = true;
    unreadCount.value = 0;
  }

  function notifyNewContent() {
    if (isAutoScrollActive.value) {
      scrollToBottom();
    } else {
      unreadCount.value++;
    }
  }

  onMounted(() => {
    if (containerRef.value) {
      containerRef.value.addEventListener('scroll', handleScroll, { passive: true });
    }
  });

  onBeforeUnmount(() => {
    if (containerRef.value) {
      containerRef.value.removeEventListener('scroll', handleScroll);
    }
  });

  return {
    isAutoScrollActive,
    unreadCount,
    scrollToBottom,
    notifyNewContent
  };
}
