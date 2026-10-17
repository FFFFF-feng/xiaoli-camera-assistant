<script setup lang="ts">
import shoot from '../../../assets/mascot/shoot.webp';
import advice from '../../../assets/mascot/advice.webp';
import history from '../../../assets/mascot/history.webp';
import connect from '../../../assets/mascot/connect.webp';

withDefaults(defineProps<{ pose: 'shoot' | 'advice' | 'history' | 'connect'; priority?: boolean }>(), { priority: false });
const illustrations = {
  shoot: { src: shoot, alt: '小栗双手举起相机，认真取景拍摄' },
  advice: { src: advice, alt: '小栗拿着构图板，指着三分网格讲解拍摄建议' },
  history: { src: history, alt: '小栗坐在木凳上翻看相册，回顾拍摄灵感' },
  connect: { src: connect, alt: '小栗拿着手机操作笔记本电脑，确认无线连接' },
};
</script>

<template>
  <figure class="mascot-art" :class="`mascot-art--${pose}`">
    <img :src="illustrations[pose].src" :alt="illustrations[pose].alt" width="1024" height="1536" decoding="async" :loading="priority ? 'eager' : 'lazy'" :fetchpriority="priority ? 'high' : 'auto'" />
  </figure>
</template>

<style scoped>
.mascot-art { display: block; position: relative; min-width: 0; margin: 0; }
.mascot-art > img { display: block; width: 100%; max-width: none; height: 100%; margin: 0; border-radius: 0; background: transparent; object-fit: contain; object-position: center; mix-blend-mode: normal; filter: none; mask-image: none; }
</style>
