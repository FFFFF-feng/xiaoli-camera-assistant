<script setup lang="ts">
defineProps<{ name: 'camera' | 'sparkles' | 'bookmark' | 'connect' | 'image' | 'arrow' | 'plus' }>();
const paths = {
  camera: 'M14.5 4h-5L7.8 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3.8L14.5 4ZM16 14a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  sparkles: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4M18 4h4',
  bookmark: 'M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1Z',
  connect: 'm9 15 6-6M8 17l-1 1a4.2 4.2 0 0 1-6-6l4-4a4.2 4.2 0 0 1 6 0M16 7l1-1a4.2 4.2 0 0 1 6 6l-4 4a4.2 4.2 0 0 1-6 0',
  image: 'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1ZM3 17l6-6 5 5 3-3 4 4M17 7h.01',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  plus: 'M12 5v14M5 12h14',
};
</script>

<template>
  <svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name]" /></svg>
</template>
