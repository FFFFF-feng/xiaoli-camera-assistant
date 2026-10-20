import {createApp,h} from 'vue';
import CompositionView from '../../src/components/CompositionView.vue';
import '../../src/style.css';
import '../../src/report.css';

// Deliberately reproduce the reported partial result, not a successful model run.
const composition={status:'grounded',trace_id:'0123456789abcdef0123456789abcdef',
  diagnostics:[{stage:'recognition',status:'complete',code:'objects_validated'},
    {stage:'contours',status:'failed',code:'no_usable_geometry'},
    {stage:'intent',status:'skipped',code:'source_geometry_unavailable'},
    {stage:'layout',status:'skipped',code:'source_geometry_unavailable'}],
  observations:['本地离线排版样例，不是本次用户照片的实际识别结果。'],uncertainties:[],
  notes:['方案引用本次检索的知识条目；检索相关度和模型输出不代表实拍效果已验证。',
    '未能从照片中分离出完整的主要主体轮廓；背景相近、细小主体或遮挡可能影响提取。',
    '模型未提供有效的构图意图；已保留文字建议，未使用原图布局冒充推荐图。'],
  proposals:[{action_type:'camera_position',goal:'整理主体与背景的重叠关系',
    actions:['先确认主要主体，保持关键边缘完整。','比较左右机位，避开背景重叠后再试拍。'],
    reasons:['主体与背景分离后更容易辨认。'],conditions:['以现场可安全移动的范围为准。'],
    tradeoffs:[],limitations:['当前没有可展示的轮廓。'],knowledge_ids:[],storyboard:null}]};
const fixture={scene:{},composition};
createApp({render:()=>h('div',{class:'app-shell'},[
  h('header',{class:'app-header'},[h('strong','小栗 · 拍摄建议')]),
  h('main',{style:'max-width:740px;margin:auto;padding:20px 18px'},[
    h('p',{class:'helper'},'本地离线排版样例 · 不调用模型'),
    h(CompositionView,{result:fixture,preview:''}),
  ]),
])}).mount('#app');
