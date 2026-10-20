<script setup lang="ts">
import { computed, useId } from 'vue';

const props = withDefaults(defineProps<{
  percent: number;
  message: string;
  title?: string;
  history?: string[];
  waiting?: boolean;
  receiving?: boolean;
}>(), { title: '小栗正在分析照片', history: () => [], waiting: false, receiving: false });
const messageId = useId();
const value = computed(() => Number.isFinite(props.percent) ? Math.max(0, Math.min(100, Math.round(props.percent))) : 0);
</script>

<template>
  <section class="processing-progress" :aria-label="title">
    <div class="processing-heading"><strong>{{ title }}</strong><span class="processing-percent" aria-hidden="true">{{ value }}<small>%</small></span></div>
    <progress :value="value" max="100" :aria-label="title" :aria-describedby="messageId" :aria-valuetext="`${value}%`"></progress>
    <p :id="messageId" class="processing-current" role="status" aria-live="polite" aria-atomic="true"><span class="processing-pulse" aria-hidden="true"></span>{{ message }}</p>
    <p class="processing-note">{{ waiting ? '这个步骤需要多一点时间，仍在处理中，请保持页面打开。' : receiving ? '分析结果正在陆续返回，小栗会在检查后展示。' : '进度按处理环节更新，复杂画面会停留稍久。' }}</p>
    <details v-if="history.length > 1" class="processing-updates"><summary>查看处理动态</summary><ol><li v-for="(item, index) in history" :key="index">{{ item }}</li></ol></details>
  </section>
</template>

<style scoped>
.processing-progress{padding:22px;border:1px solid var(--border);border-radius:12px;background:var(--wash);color:var(--ink);text-align:left}
.processing-heading{display:flex;justify-content:space-between;align-items:center;gap:16px}.processing-heading strong{font-size:14px;font-weight:550;line-height:1.7}
.processing-percent{color:var(--green);font-size:30px;font-weight:600;line-height:1.2;font-variant-numeric:tabular-nums}.processing-percent small{margin-left:3px;font-size:14px;font-weight:500}
progress{display:block;appearance:none;-webkit-appearance:none;width:100%;height:8px;margin:16px 0 18px;border:0;border-radius:8px;overflow:hidden;background:var(--border);accent-color:var(--green)}
progress::-webkit-progress-bar{background:var(--border);border-radius:8px}progress::-webkit-progress-value{background:var(--green);border-radius:8px;transition:width .4s ease}progress::-moz-progress-bar{background:var(--green);border-radius:8px}
.processing-current{display:flex;align-items:flex-start;gap:9px;margin:0;font-size:13px;line-height:1.9;color:var(--ink)}.processing-pulse{flex:none;width:7px;height:7px;margin-top:9px;border-radius:50%;background:var(--green);animation:processing-breathe 1.8s ease-in-out infinite}
.processing-note{font-size:11px;line-height:1.8;color:var(--muted);margin:7px 0 0;padding-left:16px}.processing-updates{margin:16px 0 0;padding-top:12px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)}.processing-updates summary{cursor:pointer}.processing-updates ol{margin:10px 0 0;padding-left:18px}.processing-updates li{margin:5px 0;line-height:1.8;overflow-wrap:break-word}
@keyframes processing-breathe{50%{opacity:.35}}
@media(max-width:600px){.processing-progress{padding:18px 16px}.processing-percent{font-size:27px}}
@media(prefers-reduced-motion:reduce){.processing-pulse{animation:none}progress::-webkit-progress-value{transition:none}}
</style>
