<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { Analysis, TargetBoard, FramingPlan } from '../types';
import TargetComposition from './TargetComposition.vue';
import PhotoFeedback from './PhotoFeedback.vue';
import SceneSurvey from './SceneSurvey.vue';
import ReportHeading from './ReportHeading.vue';
import FieldActionCard from './FieldActionCard.vue';
import { fieldActionCard } from '../field-actions.mjs';
import { targetCompositionCopy, usableTargetBoard } from '../target-board.mjs';
import { usableFramingPlan } from '../composition-sketch.mjs';
import { compositionStatus } from '../composition-status.mjs';
const props = withDefaults(defineProps<{ result: Analysis['result']; preview: string;photos?:{id:string;url:string}[] }>(),{photos:()=>[]});
const selectedPhoto=ref('');
const view = ref<'sketch' | 'photo'>('sketch');
const selected = ref(0);
const showGrid = ref(true);
const showSubjects = ref(true);
const selectedCrop = ref<number | null>(null);
watch(()=>props.preview,()=>{selected.value=0;selectedPhoto.value='';selectedCrop.value=null;view.value='sketch';});
const proposals = computed(() => props.result.composition?.proposals || []);
const current = computed(() => proposals.value[selected.value] || proposals.value[0]);
const board = computed(() => usableTargetBoard(current.value?.storyboard) as TargetBoard | null);
const presentation = computed(() => compositionStatus(props.result.composition, current.value, !!board.value));
const diagnosticNames={recognition:'物体识别',contours:'主体轮廓',intent:'构图意图',layout:'布局计算'};
const diagnosticStatus={complete:'完成',failed:'未完成',skipped:'未执行'};
const boardReference = computed(() => props.photos.find(p=>p.id===board.value?.reference_photo_id)?.url
  || (board.value?.reference_photo_id==='photo1'?props.preview:''));
const compareId=computed(()=>selectedPhoto.value || board.value?.reference_photo_id || 'photo1');
const comparePreview=computed(()=>props.photos.find(p=>p.id===compareId.value)?.url || props.preview);
const survey=computed(()=>props.result.scene?.scene_survey);
const framing = computed(() => usableFramingPlan(current.value?.framing_plan) as FramingPlan | null);
const operations = computed(() => fieldActionCard(current.value, board.value, framing.value));
const framingCopy = computed(() => board.value?.layout_mode === 'source_preserving'
  ? targetCompositionCopy(board.value) : null);
const framingChecklist = computed(() => {
  if (!framing.value) return {};
  if (!framingCopy.value) return {
    '主体摆位': framing.value.placement, '画面比例': framing.value.scale,
    '方向与留白': framing.value.negative_space, '边缘保护': framing.value.edge_check,
    '背景控制': framing.value.background_control, '完成标准': framing.value.success_check,
  };
  const copy = framingCopy.value;
  return {
    '取景状态': `${copy.status ? `${copy.status} · ` : ''}${copy.heading}。${copy.reason}`,
    [copy.changeLabel]: copy.action,
    '空间关系': copy.changeText,
    '线绘说明': copy.drawing,
    '边界核对': framing.value.edge_check,
    '环境控制': framing.value.background_control,
  };
});
const actionNames: Record<string, string> = { crop: '裁切画面', camera_position: '调整机位', focal_length: '调整焦段', reshoot: '重新拍摄' };
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
    <p v-if="survey && survey.status !== 'consistent'" class="helper" role="status">参考照片的场景关联需核对，请以原图为准。</p>
    <details v-if="survey" class="report-disclosure"><summary>场景与参考照片</summary><SceneSurvey :survey="survey"/></details>
    <div id="result-composition" class="report-section-anchor"><ReportHeading :title="framingCopy?'原始布局线稿对照':'推荐构图'" title-id="composition-title" eyebrow="01 · 画面方向" :description="framingCopy?'本次没有形成新的取景布局；以下线稿用于核对原取景和现场拍摄重点。':'查看主体的位置、大小和前后层次。'" icon="image" level="h2"><span class="result-badge">{{ framingCopy?'本次未调整取景':presentation.badge }}</span></ReportHeading></div>
    <div v-if="proposals.length" class="composition-plan-switch" role="group" aria-label="选择构图方案"><button v-for="(proposal, index) in proposals" :key="index" type="button" :aria-pressed="selected === index" @click="selected = index; selectedCrop = null; selectedPhoto = ''">方案{{ index+1 }} · {{ actionNames[proposal.action_type] || '取景' }}</button></div>
    <div v-if="preview || board" class="composition-view-switch" role="group" aria-label="构图查看方式"><button type="button" :aria-pressed="view === 'sketch'" @click="view = 'sketch'">{{ framingCopy?'原取景线稿':'推荐构图线稿' }}</button><button v-if="preview" type="button" :aria-pressed="view === 'photo'" @click="view = 'photo'">原图与裁切对照</button></div>
    <PhotoFeedback v-if="preview && view==='photo'" :source="preview" :crop="current?.action_type==='crop'?current.crop_bbox:null"/>
    <template v-if="view === 'sketch' || !preview">
      <TargetComposition v-if="board" :board="board" :reference="boardReference" compact-advice>
        <template #operations><div v-if="operations" id="result-action-plan" class="report-section-anchor"><FieldActionCard :card="operations" /></div></template>
      </TargetComposition>
      <div v-else-if="presentation.failed" class="sketch-unavailable" role="status"><strong>推荐线稿未完成</strong><p>{{ presentation.reason }}{{ presentation.action }}</p><button v-if="preview" class="secondary" type="button" @click="view='photo'">查看原图对照</button><small>重新分析会再次调用模型，不会自动重试。</small></div>
    </template>
    <div v-if="operations && (!board || view==='photo')" id="result-action-plan" class="report-section-anchor"><FieldActionCard :card="operations" /></div>
    <details v-if="result.composition?.diagnostics?.length || result.composition?.notes.length || result.composition?.trace_id" class="photo-inspection report-disclosure"><summary>查看生成环节与说明</summary><p v-for="(item,index) in result.composition?.diagnostics" :key="index">{{ diagnosticNames[item.stage] }}：{{ diagnosticStatus[item.status] }}<small class="diagnostic-code">{{ item.code }}</small></p><p v-if="current?.storyboard&&!board">画面展示：绘图数据检查未通过。</p><p v-if="result.composition?.trace_id" class="diagnostic-code">排查编号：{{ result.composition.trace_id }}</p><p v-for="note in result.composition?.notes" :key="note">{{ note }}</p></details>
    <details v-if="preview && view === 'photo'" class="photo-inspection" :open="selectedCrop!==null"><summary>检查原图主体与裁切边界</summary>
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
    </details>
    <template v-if="result.composition">
      <details v-if="current" class="advice-details report-disclosure"><summary>建议详情与适用条件</summary>
        <p v-if="framing?.visual_priority" class="helper">视觉主次：{{ framing.visual_priority }}</p>
        <button v-if="current.crop_bbox && preview" class="secondary" type="button" :aria-pressed="selectedCrop === selected" @click="view = 'photo'; selectedPhoto = 'photo1'; selectedCrop = selectedCrop === selected ? null : selected">{{ selectedCrop === selected ? '关闭裁切参考' : '在原图上看裁切参考' }}</button>
        <template v-for="(items,title) in { '拍摄理由': current.reasons, '适用条件': current.conditions, '需要取舍': current.tradeoffs, '方案限制': current.limitations }" :key="title"><section v-if="items.length" class="proposal-explanation"><h4>{{ title }}</h4><ul><li v-for="text in items" :key="text">{{ text }}</li></ul></section></template>
      <details v-if="framing" class="framing-details report-disclosure"><summary>取景检查清单<small>摆位、比例、留白与边缘</small></summary><dl class="framing-checklist"><div v-for="(text,label) in framingChecklist" :key="label"><dt>{{ label }}</dt><dd>{{ text }}</dd></div></dl><p class="helper">{{ framingCopy?framingCopy.drawing:'推荐线稿表达目标构图；原图用于核对物体特征。实际透视、遮挡与新视角仍需现场试拍验证。' }}</p></details>
      <details v-if="result.composition.uncertainties.length || result.composition.observations.length" class="composition-evidence report-disclosure"><summary>观察与现场核对</summary><p v-for="text in result.composition.observations" :key="text">{{ text }}</p><ul><li v-for="text in result.composition.uncertainties" :key="text">{{ text }}</li></ul></details>
      </details>
      <p v-if="!result.composition.proposals.length" class="helper">{{ result.composition.status === 'demo' ? '当前规则演示提供参数与操作起点。配置真实图像模型后，小栗才能针对画面给出构图建议。' : '本次没有通过校验的构图方案。可以补充主体与希望保留的画面，再试一次。' }}</p>
    </template>
    <p v-else class="helper">服务尚未开启构图分析；拍摄参数与操作建议仍可使用。</p>
  </section>
</template>

<style scoped>
.composition-panel { min-width: 0; overflow-wrap: break-word; }
.photo-inspection { margin: 18px 0; }
.reference-photo-switch { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.reference-photo-switch button { background: white; border: 1px solid var(--border); padding: 7px 12px; border-radius: 6px; color: var(--muted); font-size: 12px; }
.reference-photo-switch button[aria-pressed=true] { color: var(--green); border-color: var(--green); }
.framing-diagnosis { padding: 20px; margin: 20px 0; background: #f9eee1; border: 1px solid #e8cdb3; border-left: 4px solid var(--coral); border-radius: 12px; }
.framing-diagnosis strong { display: inline-block; padding: 3px 9px; background: #edd5bb; border-radius: 5px; font-size: 12px; color: #774522; font-weight: 700; }
.framing-diagnosis p { font-size: 16px; font-weight: 600; line-height: 1.95; margin: 12px 0 8px; color: var(--ink); }
.framing-diagnosis > span { display: block; padding-top: 10px; border-top: 1px solid #e8d7c4; font-size: 13px; line-height: 1.9; color: #786047; }
.framing-checklist { margin: 12px 0 18px; }
.framing-checklist > div { display: grid; grid-template-columns: 80px minmax(0,1fr); gap: 14px; padding: 14px 0; border-bottom: 1px solid var(--border); }
.framing-checklist dt { font-size: 13px; font-weight: 650; color: #7d573b; padding-top: 2px; }
.framing-checklist dd { font-size: 14px; font-weight: 400; line-height: 1.9; margin: 0; color: var(--ink); }
.composition-plan-switch, .composition-view-switch { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
.composition-plan-switch button { max-width: 100%; text-align: left; color: var(--muted); background: white; border: 1px solid var(--border); border-radius: 7px; font-size: 13px; padding: 10px 14px; }
.composition-plan-switch button[aria-pressed=true] { background: var(--green); border-color: var(--green); color: white; }
.composition-view-switch { border-bottom: 1px solid var(--border); gap: 20px; }
.composition-view-switch button { background: transparent; border: 0; border-bottom: 3px solid transparent; padding: 12px 0; color: var(--muted); font-size: 13px; }
.composition-view-switch button[aria-pressed=true] { color: var(--green); border-color: var(--green); font-weight: 700; }
.sketch-unavailable { background: var(--wash); padding: 20px; border-radius: 12px; margin: 16px 0; }
.sketch-unavailable strong { font-size: 15px; }
.sketch-unavailable p { font-size: 13px; color: var(--muted); line-height: 1.9; }
.sketch-unavailable small { display: block; margin-top: 12px; color: var(--muted); font-size: 12px; }
.diagnostic-code { display: block; overflow-wrap: anywhere; font-size: 12px; color: var(--muted); }
.composition-proposal { margin: 28px 0 20px; padding: 24px; border: 1px solid #e5cbb1; background: #fffbf4; border-radius: 16px; }
.composition-proposal .report-heading { margin-bottom: 20px; }
.proposal-type { display: inline-block; font-size: 11px; font-weight: 650; border-radius: 5px; padding: 3px 8px; color: #855936; background: #f2e6d7; }
.composition-proposal h3 { font-size: 17px; line-height: 1.8; margin: 9px 0 18px; }
.composition-steps { list-style: none; padding: 0; margin: 0 0 20px; counter-reset: shooting-step; }
.composition-steps li { display: grid; grid-template-columns: 30px minmax(0,1fr); gap: 12px; margin: 0; padding: 16px 0; font-size: 14px; line-height: 1.95; border-top: 1px solid #eadfce; counter-increment: shooting-step; }
.composition-steps li::before { content: counter(shooting-step, decimal-leading-zero); display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid #dfc4a5; background: #f5e8d6; border-radius: 50%; color: #93522e; font-size: 12px; font-weight: 700; }
.composition-proposal .report-disclosure { background: #fffdf9; margin-bottom: 0; }
.proposal-explanation { padding: 0 0 15px; }
.proposal-explanation h4 { margin: 0 0 8px; font-size: 13px; font-weight: 700; color: #7a4f32; }
.proposal-explanation ul { padding-left: 20px; margin: 0; }
.proposal-explanation li { font-size: 13px; padding: 3px 0; line-height: 1.9; }
.composition-cautions { margin: 18px 0; padding: 18px; border: 1px solid #e8d5b0; border-radius: 12px; background: #fff7e7; color: #73522b; }
.composition-cautions > strong { font-size: 14px; font-weight: 700; }
.composition-cautions ul { padding-left: 20px; margin: 10px 0 0; }
.composition-cautions li { font-size: 13px; line-height: 1.9; padding: 4px 0; }
.composition-view-switch button:focus-visible, .composition-plan-switch button:focus-visible { outline: 2px solid var(--coral); outline-offset: 3px; }
@media(max-width:600px) {
  .framing-diagnosis { padding: 16px; }
  .framing-diagnosis p { font-size: 15px; }
  .composition-proposal { padding: 18px 15px; }
  .framing-checklist > div { grid-template-columns: minmax(0,1fr); gap: 5px; }
}
</style>
