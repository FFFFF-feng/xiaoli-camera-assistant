<script setup lang="ts">
import {computed,ref,watch,onBeforeUnmount} from 'vue';
import {photoFrame} from '../photo-feedback.mjs';

const props=defineProps<{source:string;crop?:number[]|null}>();
const natural=ref({width:0,height:0});
const failed=ref(false),grid=ref(false),useCrop=ref(true);
let image:HTMLImageElement|undefined;
let revision=0;
watch(()=>[props.source,props.crop],()=>{
  const current=++revision;
  if(image){image.onload=null;image.onerror=null;}
  failed.value=false;natural.value={width:0,height:0};useCrop.value=true;
  if(!props.source)return;
  image=new Image();
  image.onload=()=>{if(current===revision)natural.value={width:image!.naturalWidth,height:image!.naturalHeight};};
  image.onerror=()=>{if(current===revision)failed.value=true;};
  image.src=props.source;
},{immediate:true});
onBeforeUnmount(()=>{revision++;if(image){image.onload=null;image.onerror=null;}});
const frame=computed(()=>photoFrame(natural.value.width,natural.value.height,useCrop.value?props.crop:null));
const hasCrop=computed(()=>photoFrame(natural.value.width,natural.value.height,props.crop)?.cropped);
</script>

<template>
  <figure class="photo-feedback">
    <div class="photo-feedback-heading"><h3>{{ hasCrop?'原图裁切预览':'现场画面参考' }}</h3><span>保留真实外形与细节</span></div>
    <svg v-if="frame" :viewBox="`${frame.x} ${frame.y} ${frame.width} ${frame.height}`"
      :style="{aspectRatio:`${frame.width}/${frame.height}`}" role="img"
      :aria-label="frame.cropped?'基于原始照片的裁切预览，未重绘物体':'完整原始照片；不是改变机位后的效果预测'">
      <image :href="source" :width="natural.width" :height="natural.height"/>
      <g v-if="grid" stroke="white" stroke-opacity=".8" stroke-width="1" vector-effect="non-scaling-stroke" fill="none">
        <path v-for="n in [1,2]" :key="n" :d="`M${frame.x+frame.width*n/3} ${frame.y}v${frame.height}M${frame.x} ${frame.y+frame.height*n/3}h${frame.width}`" vector-effect="non-scaling-stroke"/>
      </g>
    </svg>
    <p v-else role="status">{{ failed?'原图暂时无法读取，请重新选择照片。':'正在读取原图…' }}</p>
    <div class="photo-feedback-controls"><label><input v-model="grid" type="checkbox"/>三分参考线</label><label v-if="hasCrop"><input v-model="useCrop" type="checkbox"/>应用建议裁切</label></div>
    <figcaption v-if="hasCrop">直接使用原图裁切，不重新生成物体；仅预览画面范围变化，不代表画质、透视或光线已经改善。</figcaption>
    <figcaption v-else>这是原始现场画面，保留物体样貌。换机位后的遮挡、透视和背景无法仅凭这张照片准确还原，请按下方步骤试拍。</figcaption>
  </figure>
</template>

<style scoped>
.photo-feedback{margin:22px 0}.photo-feedback-heading{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:14px;flex-wrap:wrap}.photo-feedback h3{font-size:19px;line-height:1.7;color:#304962;margin:0;font-weight:500}.photo-feedback-heading>span{font-size:12px;color:#71849b}.photo-feedback svg{display:block;width:100%;max-height:560px;background:#f3f6f9;border:1px solid #e0e7ee}.photo-feedback-controls{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0}.photo-feedback label{display:flex;align-items:center;gap:5px;font-size:12px;color:#58718a}.photo-feedback input{accent-color:#315b9c}.photo-feedback figcaption,.photo-feedback>p{font-size:12px;color:#71849b;line-height:1.9;word-break:normal;overflow-wrap:break-word}
</style>
