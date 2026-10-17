<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Analysis, TargetBoard, FramingPlan } from '../types';
import TargetComposition from './TargetComposition.vue';
import SceneSurvey from './SceneSurvey.vue';
import { usableTargetBoard } from '../target-board.mjs';
import { usableFramingPlan } from '../composition-sketch.mjs';
const props = withDefaults(defineProps<{ result: Analysis['result']; preview: string;photos?:{id:string;url:string}[] }>(),{photos:()=>[]});
const selectedPhoto=ref('');
const view = ref<'sketch' | 'photo'>('sketch');
const selected = ref(0);
const showGrid = ref(true);
const showSubjects = ref(true);
const selectedCrop = ref<number | null>(null);
const proposals = computed(() => props.result.composition?.proposals || []);
const current = computed(() => proposals.value[selected.value] || proposals.value[0]);
const board = computed(() => usableTargetBoard(current.value?.storyboard) as TargetBoard | null);
const compareId=computed(()=>selectedPhoto.value || board.value?.reference_photo_id || 'photo1');
const comparePreview=computed(()=>props.photos.find(p=>p.id===compareId.value)?.url || props.preview);
const survey=computed(()=>props.result.scene?.scene_survey);
const framing = computed(() => usableFramingPlan(current.value?.framing_plan) as FramingPlan | null);
const actionNames: Record<string, string> = { crop: '裁切画面', camera_position: '调整机位', focal_length: '调整焦段', reshoot: '重新拍摄' };
const statusNames: Record<string, string> = { grounded: '有知识依据', unverified: '待试拍验证', unavailable: '本次暂不可用', demo: '演示模式' };
const subjects = computed(() => {
  const loc = props.result.localization;
  if (!loc?.real || loc.selection.status !== 'selected') return [];
  return loc.candidates.filter(c => loc.selection.selected_ids.includes(c.object_id) && c.bbox.length === 4 && c.bbox.every(n => Number.isFinite(n) && n >= 0 && n <= 1));
});
const crop = computed(() => selectedCrop.value === null ? null : props.result.composition?.proposals[selectedCrop.value]?.crop_bbox);
const shadePath = computed(() => {
  if (!crop.value) return '';
  const [x1, y1, x2, y2] = crop.value.map(v => v * 1000);
  return `M0,0H1000V1000H0Z M${x1},${y1}V${y2}H${x2}V${y1}Z`;
});
</script>

<template>
  <section class="composition-panel" aria-labelledby="composition-title">
    <SceneSurvey v-if="survey" :survey="survey"/><div class="section-heading"><h2 id="composition-title">推荐构图</h2><span class="result-badge">{{ statusNames[result.composition?.status || 'unavailable'] }}</span></div>
    <p class="composition-intro">把主题、主体和留白，放进同一个取景框。</p>
    <div v-if="proposals.length" class="composition-plan-switch" role="group" aria-label="选择构图方案"><button v-for="(proposal, index) in proposals" :key="index" type="button" :aria-pressed="selected === index" @click="selected = index; selectedCrop = null; selectedPhoto = ''">方案{{ index+1 }} · {{ actionNames[proposal.action_type] || '取景' }}</button></div>
    <div v-if="framing" class="framing-diagnosis"><strong>先看这一点</strong><p>{{ framing.diagnosis }}</p><span>视觉主次：{{ framing.visual_priority }}</span></div>
    <div v-if="preview || board" class="composition-view-switch" role="group" aria-label="构图查看方式"><button type="button" :aria-pressed="view === 'sketch'" @click="view = 'sketch'">推荐画面</button><button v-if="preview" type="button" :aria-pressed="view === 'photo'" @click="view = 'photo'">原图对照</button></div>
    <template v-if="view === 'sketch'">
      <TargetComposition v-if="board" :board="board" />
      <div v-else-if="proposals.length" class="sketch-unavailable"><strong>本次未生成可核对的推荐图</strong><p>可以先按下方步骤试拍，或补充主体细节照片后重新分析。</p></div>
    </template>
    <template v-if="preview && view === 'photo'">
      <div v-if="photos.length>1" class="reference-photo-switch" aria-label="原图参考选择"><button v-for="item in photos" :key="item.id" type="button" :aria-pressed="compareId===item.id" @click="selectedPhoto=item.id; selectedCrop=null">第 {{ item.id.slice(5) }} 张</button></div><div class="composition-image">
        <img :src="comparePreview" alt="现场照片与构图参考线" />
        <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">
          <g v-if="showGrid" stroke="white" stroke-opacity=".6" stroke-width="1.5"><path d="M333.33 0V1000M666.67 0V1000M0 333.33H1000M0 666.67H1000" /></g>
          <g v-if="showSubjects && compareId==='photo1'" fill="none" stroke="#89f5bd" stroke-width="4"><rect v-for="s in subjects" :key="s.object_id" :x="s.bbox[0]*1000" :y="s.bbox[1]*1000" :width="(s.bbox[2]-s.bbox[0])*1000" :height="(s.bbox[3]-s.bbox[1])*1000" /></g>
          <path v-if="crop && compareId==='photo1'" :d="shadePath" fill="black" fill-opacity=".62" fill-rule="evenodd" />
          <rect v-if="crop && compareId==='photo1'" :x="crop[0]*1000" :y="crop[1]*1000" :width="(crop[2]-crop[0])*1000" :height="(crop[3]-crop[1])*1000" fill="none" stroke="#ffdc80" stroke-width="4" />
        </svg>
      </div>
      <div class="composition-controls"><label class="check-row"><input type="checkbox" v-model="showGrid" />三分参考线</label><label v-if="subjects.length" class="check-row"><input type="checkbox" v-model="showSubjects" />主体框</label><button v-if="crop" type="button" class="text-button" @click="selectedCrop = null">查看完整画面</button></div>
      <p class="helper">参考线辅助取景，不修改原照片。{{ subjects.length ? `已定位主体：${subjects.map(s => s.label_display).join('、')}。` : '本次未确认可靠主体框。' }}</p>
    </template>
    <template v-if="result.composition">
      <p v-if="framing" class="helper">推荐图按目标方案重新绘制，位置与比例属于取景设计。实际透视、遮挡与新视角仍需现场试拍核对。</p>
      <dl v-if="framing" class="framing-checklist"><div v-for="(text,label) in { '主体摆位': framing.placement, '画面比例': framing.scale, '方向与留白': framing.negative_space, '边缘保护': framing.edge_check, '背景控制': framing.background_control, '完成标准': framing.success_check }" :key="label"><dt>{{ label }}</dt><dd>{{ text }}</dd></div></dl>
      <article v-if="current" class="composition-proposal">
        <span class="proposal-type">{{ actionNames[current.action_type] || '构图建议' }}</span><h3>{{ current.goal }}</h3>
        <ol class="composition-steps"><li v-for="action in current.actions" :key="action">{{ action }}</li></ol>
        <button v-if="current.crop_bbox && preview" class="secondary" type="button" :aria-pressed="selectedCrop === selected" @click="view = 'photo'; selectedPhoto = 'photo1'; selectedCrop = selectedCrop === selected ? null : selected">{{ selectedCrop === selected ? '关闭裁切参考' : '在原图上看裁切参考' }}</button>
        <details><summary>为什么这样拍 · 适用条件</summary><p v-for="text in [...current.reasons, ...current.conditions, ...current.tradeoffs, ...current.limitations]" :key="text">{{ text }}</p></details>
      </article>
      <p v-if="!result.composition.proposals.length" class="helper">{{ result.composition.status === 'demo' ? '当前规则演示提供参数与操作起点。配置真实图像模型后，小栗才能针对画面给出构图建议。' : '本次没有通过校验的构图方案。可以补充主体与希望保留的画面，再试一次。' }}</p>
      <details v-if="result.composition.observations.length" class="composition-evidence"><summary>看看小栗观察到了什么</summary><p v-for="text in result.composition.observations" :key="text">{{ text }}</p></details>
      <div v-if="result.composition.uncertainties.length" class="notice demo"><p v-for="text in result.composition.uncertainties" :key="text">{{ text }}</p></div>
      <p v-for="text in result.composition.notes" :key="text" class="helper">{{ text }}</p>
    </template>
    <p v-else class="helper">服务尚未开启构图分析；拍摄参数与操作建议仍可使用。</p>
  </section>
</template>

<style scoped>
.reference-photo-switch{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.reference-photo-switch button{background:white;border:1px solid var(--border);padding:7px 12px;border-radius:4px;color:var(--muted);font-size:12px}.reference-photo-switch button[aria-pressed=true]{color:var(--green);border-color:var(--green)}
.framing-diagnosis { padding: 16px 18px; margin: 18px 0; background: var(--wash); border-left: 2px solid #c79973; }.framing-diagnosis strong { font-size: 12px; color: #8b6650; font-weight: 500; }.framing-diagnosis p { font-size: 14px; line-height: 1.9; margin: 7px 0; color: var(--ink); }.framing-diagnosis span { font-size: 12px; line-height: 1.8; color: var(--muted); }.framing-checklist { margin: 22px 0; }.framing-checklist > div { display: grid; grid-template-columns: 80px minmax(0,1fr); gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--border); }.framing-checklist dt { font-size: 12px; color: var(--muted); padding-top: 2px; }.framing-checklist dd { font-size: 13px; font-weight: 400; line-height: 1.9; margin: 0; color: var(--ink); }
.composition-intro { margin: 8px 0 16px; color: var(--muted); font-size: 13px; }.composition-plan-switch, .composition-view-switch { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }.composition-plan-switch button { max-width: 100%; text-align: left; color: var(--muted); background: white; border: 1px solid var(--border); border-radius: 5px; font-size: 12px; padding: 9px 13px; }.composition-plan-switch button[aria-pressed="true"] { background: var(--green); border-color: var(--green); color: white; }.composition-view-switch { border-bottom: 1px solid var(--border); gap: 20px; }.composition-view-switch button { background: transparent; border: 0; border-bottom: 2px solid transparent; padding: 10px 0; color: var(--muted); font-size: 13px; }.composition-view-switch button[aria-pressed="true"] { color: var(--green); border-color: var(--green); font-weight: 600; }.sketch-unavailable { background: var(--wash); padding: 20px; border-radius: 10px; margin: 16px 0; }.sketch-unavailable strong { font-size: 14px; }.sketch-unavailable p { font-size: 12px; color: var(--muted); line-height: 1.8; }.composition-steps { padding-left: 22px; }.composition-steps li { padding-left: 4px; margin: 7px 0; }.composition-steps li::marker { color: var(--green); font-weight: 600; }.composition-evidence { font-size: 12px; color: var(--muted); line-height: 1.8; margin: 18px 0; }.composition-evidence p { font-size: 12px; }.composition-view-switch button:focus-visible, .composition-plan-switch button:focus-visible { outline: 2px solid var(--coral); outline-offset: 3px; }
</style>
