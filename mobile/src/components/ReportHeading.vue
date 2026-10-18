<script setup lang="ts">
import UiIcon from './UiIcon.vue';
withDefaults(defineProps<{
  title: string;
  titleId?: string;
  description?: string;
  eyebrow?: string;
  icon?: 'camera' | 'sparkles' | 'bookmark' | 'connect' | 'image' | 'arrow' | 'plus';
  level?: 'h2' | 'h3' | 'h4';
}>(), { icon: 'sparkles', level: 'h3' });
</script>

<template>
  <div class="report-heading">
    <span class="report-heading-icon"><UiIcon :name="icon" /></span>
    <div class="report-heading-copy">
      <span v-if="eyebrow" class="report-eyebrow">{{ eyebrow }}</span>
      <component :is="level" :id="titleId">{{ title }}</component>
      <p v-if="description">{{ description }}</p>
    </div>
    <slot />
  </div>
</template>
