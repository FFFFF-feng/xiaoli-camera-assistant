import {createApp,h,ref} from 'vue';
import ProcessingProgress from '../../src/components/ProcessingProgress.vue';
import {initialAnalysisProgress,advanceAnalysisProgress} from '../../src/analysis-progress.mjs';
import '../../src/style.css';

const timing=stage=>({type:'timing',stage,status:'complete'});
createApp({setup(){
  const state=ref([timing('upload'),timing('image_preprocessing'),{type:'partial',kind:'scene'},
    timing('parameter_retrieval'),{type:'partial',kind:'parameters'}].reduce(advanceAnalysisProgress,initialAnalysisProgress()));
  const waiting=ref(false),receiving=ref(false);
  return ()=>h('main',{style:'max-width:620px;margin:40px auto;padding:0 20px'},[
    h('h1',{style:'font-size:20px'},'等待页面离线验收'),
    h('p',{class:'helper'},'人工模拟处理事件，不上传照片、不请求模型，不是真实分析记录。'),
    h(ProcessingProgress,{...state.value,waiting:waiting.value,receiving:receiving.value}),
    h('div',{style:'display:flex;flex-wrap:wrap;gap:12px;margin-top:22px'},[
      h('button',{class:'secondary',onClick:()=>{state.value=advanceAnalysisProgress(state.value,
        {type:'progress',stage:'composition_contours',message:'正在提取主体轮廓，保留照片细节…'});}},'查看轮廓阶段'),
      h('button',{class:'secondary','aria-pressed':waiting.value,onClick:()=>{waiting.value=!waiting.value;}},'切换长等待提示'),
      h('button',{class:'secondary','aria-pressed':receiving.value,onClick:()=>{receiving.value=!receiving.value;waiting.value=false;}},'切换接收提示'),
    ]),
  ]);
}}).mount('#app');
