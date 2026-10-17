<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref,watch} from 'vue';
import type {Analysis,PreviewApi} from '../types';
import {previewPlan,safePreviewImage,localReference} from '../composition-preview.mjs';
type Proposal=NonNullable<Analysis['result']['composition']>['proposals'][number];
const props=defineProps<{proposal:Proposal;source:string;referencePhotoId:string;api:PreviewApi}>();
const configuration=ref<{available:boolean;provider:string;model:string;configuration_id:string;message:string}>();
const consent=ref(false),busy=ref(false),generated=ref(''),error=ref(''),elapsed=ref(0);
let controller:AbortController|undefined;
let clock:ReturnType<typeof setInterval>|undefined;
let revision=0;
const plan=computed(()=>previewPlan(props.proposal,props.referencePhotoId));
function reset(){revision++;controller?.abort();consent.value=false;generated.value='';error.value='';}
watch(()=>[props.source,props.proposal,props.referencePhotoId],reset);
onBeforeUnmount(()=>{reset();if(clock)clearInterval(clock);});
onMounted(async()=>{
  try {configuration.value=await props.api('/api/v1/composition-preview/config');}
  catch {error.value='未能读取预演配置，请确认已连接新版服务。';}
});
async function generate(){
  if(busy.value||!configuration.value?.available||!consent.value||!props.source||!plan.value)return;
  busy.value=true;error.value='';generated.value='';elapsed.value=0;
  controller=new AbortController();const active=controller;
  const currentRevision=revision;
  const timeout=setTimeout(()=>active.abort(),330000);
  clock=setInterval(()=>{elapsed.value++;},1000);
  try {
    if(!localReference(props.source,location.origin))throw new Error('仅可使用本次上传的本地参考图。');
    const reference=await fetch(props.source,{signal:active.signal,credentials:'omit'});
    if(!reference.ok)throw new Error('参考图无法读取，请重新选择原图。');
    const blob=await reference.blob();
    const form=new FormData();
    form.append('file',blob,'reference-image');form.append('plan',JSON.stringify(plan.value));
    form.append('consent','true');form.append('configuration_id',configuration.value.configuration_id);
    form.append('request_id',crypto.randomUUID());
    const result=await props.api('/api/v1/composition-preview',{method:'POST',body:form,signal:active.signal});
    if(active.signal.aborted||currentRevision!==revision)return;
    const image=safePreviewImage(result.image_data_url);
    if(!image||result.ai_generated!==true||result.semantic_verified!==false
      ||result.reference_photo_id!==props.referencePhotoId)throw new Error('预演结果不完整，未展示图片。');
    generated.value=image;
  } catch(e) {
    if(currentRevision!==revision)return;
    error.value=active.signal.aborted?'已停止等待。服务可能仍在生成或已计费；不会自动重发。'
      :e instanceof Error?e.message:'生成未完成，原图仍可使用。';
  } finally {
    clearTimeout(timeout);if(clock)clearInterval(clock);clock=undefined;busy.value=false;
  }
}
</script>

<template>
  <section class="image-preview" aria-label="AI构图预演">
    <div class="image-preview-heading"><h3>AI 构图预演</h3><span>参考原图编辑 · 非实拍</span></div>
    <p>按当前方案编辑参考图，尽量保留物体外形、纹理和关键细节。生成仍可能失真，不替代现场试拍。</p>
    <p v-if="configuration&&!configuration.available" class="preview-status">{{ configuration.message }}</p>
    <template v-if="configuration?.available">
      <p class="preview-provider">编辑服务：{{ configuration.provider }} / {{ configuration.model }}；参考图：第 {{ referencePhotoId.slice(5) }} 张。</p>
      <p v-if="!source" class="preview-status">当前没有这张参考图。历史记录不保存原图，请重新上传后生成。</p>
      <label class="preview-consent"><input v-model="consent" type="checkbox" :disabled="busy"/>我同意将这张参考图发送给上述编辑服务，并知晓可能产生额外费用。</label>
      <div class="preview-actions"><button type="button" :disabled="busy||!consent||!source||!plan" @click="generate">{{ busy?`正在生成 · ${elapsed} 秒`:generated?'重新生成（可能再次计费）':'生成构图预演' }}</button><button v-if="busy" type="button" class="preview-cancel" @click="controller?.abort()">停止等待</button></div>
    </template>
    <p v-if="error" role="alert" class="preview-error">{{ error }}</p>
    <div v-if="generated" class="preview-comparison">
      <figure><figcaption>原始参考图</figcaption><img :src="source" alt="本次构图预演使用的原始参考图"/></figure>
      <figure class="preview-generated"><figcaption>AI 生成预演 · 未验证真实性</figcaption><img :src="generated" alt="AI生成的构图预演，物体细节与新视角可能不准确"/></figure>
    </div>
    <p v-if="generated" class="preview-status">请对照主体数量、五官/标志性结构、纹理和背景。若发生变形或新增物体，不采用该图；原图与文字建议不受影响。预演图不保存到历史。</p>
  </section>
</template>

<style scoped>
.image-preview{margin:24px 0;padding:20px 0;border-top:1px solid #dfe7ef;border-bottom:1px solid #dfe7ef}.image-preview-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}.image-preview h3{font-size:18px;color:#304962;font-weight:500;margin:0}.image-preview-heading span{font-size:11px;color:#71849b}.image-preview p{font-size:12px;color:#58718a;line-height:1.9;word-break:normal;overflow-wrap:break-word}.preview-status{color:#71849b!important}.preview-consent{display:flex;align-items:flex-start;gap:8px;font-size:12px;line-height:1.9;color:#435d76}.preview-consent input{flex:none;margin-top:5px;accent-color:#315b9c}.preview-actions{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:16px}.preview-actions button{border:1px solid #315b9c;background:#315b9c;color:white;border-radius:4px;padding:10px 16px;font-size:13px;cursor:pointer}.preview-actions button:disabled{opacity:.5;cursor:not-allowed}.preview-actions .preview-cancel{background:white;color:#58718a;border-color:#bdcbd8}.preview-actions button:focus-visible{outline:2px solid #315b9c;outline-offset:3px}.preview-error{color:#9d3d32!important}.preview-comparison{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}.preview-comparison figure{margin:0;min-width:0}.preview-comparison figcaption{font-size:12px;color:#435d76;line-height:1.8;margin-bottom:8px}.preview-comparison img{width:100%;height:300px;object-fit:contain;background:#f3f6f9;border:1px solid #dfe7ef;box-sizing:border-box}.preview-generated figcaption{font-weight:600;color:#315b9c}@media(max-width:600px){.preview-comparison{grid-template-columns:1fr}.preview-comparison img{height:auto;max-height:420px}}
</style>
