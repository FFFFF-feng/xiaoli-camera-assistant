import {createApp,h} from 'vue';
import CompositionView from '../../src/components/CompositionView.vue';
import '../../src/style.css';
import '../../src/report.css';
const base='/.catalog-release-color-review-20261020';
const forest=new URLSearchParams(location.search).get('case')==='forest';
const response=await fetch(`${base}/${forest?'forest-result.json':'result.json'}`);
if(!response.ok)throw new Error('请先准备本地离线视觉验收素材，不请求模型。');
const result=await response.json();
createApp({render:()=>h('main',{style:'max-width:1180px;margin:24px auto;padding:0 20px'},[
  h('p',{class:'helper'},forest?'本地同图检查 · 人工指定连续场景，结构线来自原图像素 · 非云模型成功记录':
    '本地离线视觉检查 · 人工标出四朵花，轮廓与颜色来自原图像素 · 非云模型成功记录'),
  h(CompositionView,{result,preview:`${base}/${forest?'forest.jpg':'reference.jpg'}`,style:'max-width:none;margin-top:28px'}),
])}).mount('#app');
