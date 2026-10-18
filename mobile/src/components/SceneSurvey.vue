<script setup lang="ts">
import type { SceneSurvey } from '../types';
import ReportHeading from './ReportHeading.vue';
defineProps<{survey:SceneSurvey}>();
</script>
<template>
  <section class="scene-survey" aria-label="同一场景的多图分析">
    <ReportHeading title="先读懂这个场景" :description="`${survey.views.length} 张参考 · 场景分析`" icon="image" level="h2" />
    <p>{{ survey.summary }}</p>
    <p v-if="survey.status!=='consistent'" class="survey-warning">{{ survey.status==='mixed' ? '这些照片可能不是同一场景，不能直接合成构图。' : '部分视角的关联还不确定，请结合现场核对。' }}</p>
    <div class="survey-preferred"><strong>建议从第 {{ survey.preferred_photo_id.slice(5) }} 张的取景开始</strong><p>{{ survey.selection_reason }}</p></div>
    <dl><div><dt>相对距离</dt><dd>{{ survey.relative_distance }}</dd></div><div v-if="survey.subject_options.length"><dt>可用主体</dt><dd>{{ survey.subject_options.join('；') }}</dd></div><div v-if="survey.foreground_options.length"><dt>前景与装饰</dt><dd>{{ survey.foreground_options.join('；') }}</dd></div></dl>
    <details class="report-disclosure"><summary>每张参考图提供了什么</summary><p v-for="view in survey.views" :key="view.image_id"><strong>第 {{ view.image_id.slice(5) }} 张：</strong>{{ view.contribution }} {{ view.viewpoint_hint }}</p></details>
    <details v-if="survey.limitations.length" class="report-disclosure"><summary>多图分析的使用说明</summary><p v-for="note in survey.limitations" :key="note">{{ note }}</p></details>
  </section>
</template>
<style scoped>
.scene-survey { padding: 20px; margin: 0 0 28px; border: 1px solid var(--border); background: #faf7f1; border-radius: 14px; overflow-wrap: break-word; }
.scene-survey > p { font-size: 14px; line-height: 1.95; color: var(--ink); }
.survey-preferred { padding: 16px; background: #eff3e9; border: 1px solid #d8e0cb; border-radius: 10px; margin: 18px 0; }
.survey-preferred strong { font-size: 14px; font-weight: 700; color: #4c653a; }
.survey-preferred p { margin: 7px 0 0; font-size: 13px; line-height: 1.9; color: #56674a; }
.scene-survey dl > div { display: grid; grid-template-columns: 80px minmax(0,1fr); gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
.scene-survey dt { font-size: 13px; font-weight: 650; color: #7d573b; padding-top: 2px; }
.scene-survey dd { margin: 0; font-size: 14px; font-weight: 400; line-height: 1.9; color: var(--ink); }
.scene-survey .survey-warning { color: #805c28; border-left: 3px solid #bf9b54; padding: 10px 14px; background: #fff6df; border-radius: 4px; }
@media(max-width:600px) { .scene-survey { padding: 16px; }.scene-survey dl > div { grid-template-columns: minmax(0,1fr); gap: 5px; } }
</style>
