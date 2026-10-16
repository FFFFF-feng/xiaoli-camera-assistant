<script setup lang="ts">
import type { SceneSurvey } from '../types';
defineProps<{survey:SceneSurvey}>();
</script>
<template>
  <section class="scene-survey" aria-label="同一场景的多图分析">
    <div class="survey-heading"><h3>先读懂这个场景</h3><span>{{ survey.views.length }} 张参考</span></div>
    <p>{{ survey.summary }}</p>
    <p v-if="survey.status!=='consistent'" class="survey-warning">{{ survey.status==='mixed' ? '这些照片可能不是同一场景，不能直接合成构图。' : '部分视角的关联还不确定，请结合现场核对。' }}</p>
    <div class="survey-preferred"><strong>建议从第 {{ survey.preferred_photo_id.slice(5) }} 张的取景开始</strong><p>{{ survey.selection_reason }}</p></div>
    <dl><div><dt>相对距离</dt><dd>{{ survey.relative_distance }}</dd></div><div v-if="survey.subject_options.length"><dt>可用主体</dt><dd>{{ survey.subject_options.join('；') }}</dd></div><div v-if="survey.foreground_options.length"><dt>前景与装饰</dt><dd>{{ survey.foreground_options.join('；') }}</dd></div></dl>
    <details><summary>每张参考图提供了什么</summary><p v-for="view in survey.views" :key="view.image_id"><strong>第 {{ view.image_id.slice(5) }} 张：</strong>{{ view.contribution }} {{ view.viewpoint_hint }}</p></details>
    <p v-for="note in survey.limitations" :key="note" class="survey-limit">{{ note }}</p>
  </section>
</template>
<style scoped>
.scene-survey{padding:18px 0 24px;margin-bottom:24px;border-bottom:1px solid #dfe6ee}.survey-heading{display:flex;justify-content:space-between;align-items:baseline}.survey-heading h3{font-family:"Songti SC","SimSun",serif;font-size:23px;font-weight:400;color:#344f6a;margin:0}.survey-heading>span{font-size:11px;color:#8092a5}.scene-survey p{font-size:13px;line-height:1.9;color:#566f87}.survey-preferred{padding:12px 16px;background:#eef4f9;margin:15px 0}.survey-preferred strong{font-size:13px;font-weight:500;color:#365c83}.survey-preferred p{margin:5px 0}.scene-survey dl>div{display:grid;grid-template-columns:75px 1fr;gap:12px;margin:12px 0}.scene-survey dt{font-size:11px;color:#8294a6;padding-top:3px}.scene-survey dd{margin:0;font-size:13px;line-height:1.9;color:#526c85}.scene-survey details{font-size:12px;color:#6b8197;margin-top:18px}.scene-survey .survey-limit{font-size:11px;color:#8998a8}.scene-survey .survey-warning{color:#966536}
</style>
