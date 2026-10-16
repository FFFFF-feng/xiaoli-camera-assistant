<script setup lang="ts">
import { computed,ref } from 'vue';
import type { TargetBoard } from '../types';
import { projectedPoints } from '../target-board.mjs';
import { frameAspect } from '../composition-sketch.mjs';
const props=defineProps<{board:TargetBoard}>();
const sheet=ref<SVGSVGElement>();
const grid=ref(true),labels=ref(true),color=ref(true),saved=ref('');
const width=720;
const height=computed(()=>width/frameAspect(props.board.aspect));
const layers=computed(()=>props.board.layers.map((layer,index)=>({...layer,index})).sort((a,b)=>a.depth-b.depth));
const markedLayers=computed(()=>layers.value.filter(layer=>layer.kind!=='background'));
const palette={slate:'#e2e6eb',blue:'#dce9f4',ochre:'#f2dfc6',sage:'#dce8dc',rose:'#f0dddd'};
const distanceNames={closer:'适当靠近',farther:'适当退后',similar:'保持相近距离',unknown:'距离需现场判断'};
const main=computed(()=>props.board.layers.find(layer=>layer.role==='main')!);
const size=computed(()=>({w:Math.round((main.value.bbox[2]!-main.value.bbox[0]!)*100),h:Math.round((main.value.bbox[3]!-main.value.bbox[1]!)*100)}));
const portrait=computed(()=>({layer:{...main.value,bbox:[0,0,1,1]},w:(main.value.bbox[2]!-main.value.bbox[0]!)*width,h:(main.value.bbox[3]!-main.value.bbox[1]!)*height.value}));
function save() {
  if(!sheet.value)return;
  const copy=sheet.value.cloneNode(true) as SVGSVGElement;
  copy.setAttribute('xmlns','http://www.w3.org/2000/svg');copy.setAttribute('width',String(width));copy.setAttribute('height',String(height.value));
  const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download='小栗-推荐构图.svg';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);saved.value='推荐构图已保存';
}
</script>
<template>
  <div class="target-composition">
    <div class="target-heading"><h3>{{ board.intent }}</h3><span>推荐构图示意</span></div>
    <figure class="target-sheet">
      <svg ref="sheet" :viewBox="`-18 -18 ${width+36} ${height+36}`" role="img" :aria-label="`推荐构图：${board.intent}。按方案重绘的目标画面，不是原照片滤镜。`" font-family="sans-serif">
        <title>{{ board.intent }}</title><desc>根据分析建议重新设计的目标布局。新视角、遮挡与空间关系需现场试拍核对。</desc>
        <rect x="-18" y="-18" :width="width+36" :height="height+36" fill="#fafcfd"/>
        <rect :width="width" :height="height" fill="#fff" stroke="#a5b4c5" stroke-width="1"/>
        <g v-for="layer in layers" :key="layer.index" stroke="#415970" stroke-linecap="round" stroke-linejoin="round">
          <polygon :points="projectedPoints(layer,layer.outline,width,height)" :fill="color ? palette[layer.color] : '#f8fafc'" :stroke="layer.kind==='background' ? 'none' : undefined" :stroke-dasharray="layer.certainty==='approximate' ? '6 4' : undefined" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
          <polyline v-for="(path,index) in layer.details" :key="index" :points="projectedPoints(layer,path,width,height)" fill="none" stroke-width="1.1" vector-effect="non-scaling-stroke"/>
        </g>
        <g v-if="grid" stroke="#7c98b4" stroke-width=".8" opacity=".65" stroke-dasharray="5 7"><path :d="`M${width/3} 0V${height}M${width*2/3} 0V${height}M0 ${height/3}H${width}M0 ${height*2/3}H${width}`"/></g>
        <g v-if="labels" font-size="16" text-anchor="middle">
          <g v-for="layer in markedLayers" :key="layer.index"><circle :cx="layer.bbox[0]!*width+14" :cy="layer.bbox[1]!*height+14" r="12" :fill="layer.role==='main' ? '#315b9c' : '#8094a6'"/><text :x="layer.bbox[0]!*width+14" :y="layer.bbox[1]!*height+20" fill="white">{{ layer.index+1 }}</text></g>
        </g>
      </svg>
      <div class="target-controls"><label><input v-model="grid" type="checkbox"/>九宫格</label><label><input v-model="labels" type="checkbox"/>景物标记</label><label><input v-model="color" type="checkbox"/>浅色</label><button type="button" @click="save">保存推荐图</button></div>
      <figcaption>以第 {{ board.reference_photo_id.slice(5) }} 张为参考重新设计；主体目标占比：宽 {{ size.w }}% · 高 {{ size.h }}%。</figcaption>
    </figure>
    <p v-if="board.narration" class="target-narration">{{ board.narration }}</p>
    <details class="subject-study"><summary>看清主体的轮廓与结构 · {{ main.label }}</summary>
      <svg :viewBox="`-8 -8 ${portrait.w+16} ${portrait.h+16}`" role="img" :aria-label="`${main.label}的推荐形象与结构线条`" stroke="#415970" stroke-linecap="round" stroke-linejoin="round">
        <polygon :points="projectedPoints(portrait.layer,main.outline,portrait.w,portrait.h)" :fill="color ? palette[main.color] : '#f8fafc'" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
        <polyline v-for="(path,index) in main.details" :key="index" :points="projectedPoints(portrait.layer,path,portrait.w,portrait.h)" fill="none" stroke-width="1.1" vector-effect="non-scaling-stroke"/>
      </svg><p>{{ main.identity_features.join('、') }}。新机位下的形态仍需现场核对。</p>
    </details>
    <div class="target-legend"><p v-for="(layer,index) in board.layers" :key="index"><b>{{ layer.kind==='background' ? '背景' : index+1 }}</b><strong>{{ layer.label }}</strong><span>{{ layer.identity_features?.join('、') }}</span><small>{{ layer.certainty==='approximate' ? '视角近似，需试拍' : '特征依据参考照片' }}</small></p></div>
    <div class="target-changes"><h4>比原图改善在哪里</h4><article v-for="(change,index) in board.changes" :key="index"><p><span>原图问题</span>{{ change.problem }}</p><p><span>推荐调整</span>{{ change.adjustment }}</p><p><span>预期改善</span>{{ change.benefit }}</p></article></div>
    <div class="target-distance"><strong>{{ distanceNames[board.distance_relation] }}</strong><p>{{ board.distance_instruction }}</p></div>
    <p v-for="note in board.limitations" :key="note" class="target-limit">{{ note }}</p><span role="status">{{ saved }}</span>
  </div>
</template>
<style scoped>
.target-narration{font-family:"Songti SC","SimSun",serif;color:#59718a;font-size:16px;line-height:2;margin:20px 12px}.subject-study{margin:20px 0;padding:12px 0;border-bottom:1px solid #e1e8ef;color:#627e98;font-size:12px}.subject-study summary{cursor:pointer}.subject-study svg{display:block;max-width:320px;width:100%;height:260px;margin:18px auto}.subject-study p{font-size:12px;line-height:1.9;color:#74879b}
.target-heading{display:flex;align-items:baseline;gap:16px;justify-content:space-between;margin:26px 0 16px}.target-heading h3{font-family:"Songti SC","SimSun",serif;font-size:23px;font-weight:400;color:#304962;margin:0;line-height:1.7}.target-heading>span{font-size:11px;color:#71849b;white-space:nowrap}.target-sheet{margin:0;padding:18px;background:#fafcfd;border:1px solid #e0e7ee}.target-sheet svg{display:block;width:100%;max-height:520px}.target-controls{display:flex;flex-wrap:wrap;gap:14px;align-items:center;padding-top:14px;margin-top:12px;border-top:1px solid #e1e8ef}.target-controls label{display:flex;gap:4px;align-items:center;font-size:12px;color:#687f95}.target-controls input{accent-color:#315b9c}.target-controls button{margin-left:auto;border:0;background:transparent;color:#315b9c;font-size:12px;padding:8px 0}.target-sheet figcaption{font-size:12px;color:#71849b;line-height:1.9;margin-top:12px}.target-legend{margin:18px 0}.target-legend p{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;font-size:12px;margin:9px 0;line-height:1.8}.target-legend b{color:#315b9c}.target-legend span,.target-legend small{color:#74879b}.target-changes{border-top:1px solid #dfe7ef;margin-top:24px;padding-top:8px}.target-changes h4{font-size:15px;font-weight:500;color:#355675}.target-changes article{padding:8px 0 14px;border-bottom:1px solid #e4eaf0}.target-changes p{display:grid;grid-template-columns:68px 1fr;gap:12px;font-size:13px;line-height:1.9;margin:7px 0;color:#435d76}.target-changes p span{font-size:11px;color:#7b8da0;padding-top:2px}.target-distance{border-left:2px solid #89a9c9;padding:6px 16px;margin:24px 0}.target-distance strong{font-size:14px;color:#365b80;font-weight:500}.target-distance p{font-size:13px;line-height:1.9;color:#58718a;margin:5px 0}.target-limit{font-size:11px;line-height:1.9;color:#8392a3}.target-composition>[role=status]{font-size:12px;color:#315b9c}button:focus-visible{outline:2px solid #315b9c;outline-offset:3px}@media(max-width:600px){.target-heading{align-items:flex-start;flex-direction:column;gap:3px}.target-sheet{padding:12px 8px}.target-heading h3{font-size:22px}}
</style>
