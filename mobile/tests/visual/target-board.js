import {createApp,h} from 'vue';
import TargetComposition from '../../src/components/TargetComposition.vue';
import {usableTargetBoard} from '../../src/target-board.mjs';
import {completedComposition} from '../../src/completed-composition.mjs';

const caseId=new URLSearchParams(location.search).get('case')||'dog';
const json=async path=>{
  const response=await fetch(path);
  if(!response.ok)throw new Error(`${path} 未加载`);
  return response.json();
};
const [contract,dogResult]=await Promise.all([json('/fixtures/contract.json'),json('/fixtures/dog-result.json')]);

const fixture=id=>contract.valid.find(item=>item.id===id)?.board;
const dog=completedComposition(dogResult.result.composition,['photo1'])?.proposals?.[0]?.storyboard||null;
const holeBoard=fixture('silhouette_hole');
const continuousBoard=fixture('continuous');
const contourBoard=structuredClone(holeBoard);
Object.assign(contourBoard.layers[0],{
  holes:[],details:[[[.2,.2],[.8,.2]]],
  contours:[[[0,0],[.42,0],[.42,1],[0,1]],[[.58,0],[1,0],[1,1],[.58,1]]],
});

function meta(title,tags,note) {
  return h('header',{class:'fixture-meta'},[
    h('strong',title),...tags.map(tag=>h('span',tag)),h('p',{class:'fixture-note'},note),
  ]);
}
function boardFixture({id,title,tags,note,board,reference='',timing=''}) {
  const valid=usableTargetBoard(board);
  return h('section',{class:'fixture','data-fixture-id':id},[
    meta(title,tags,note),
    valid?h(TargetComposition,{board:valid,reference}):h('p',{class:'fixture-note'},'前端可信校验拒绝该样例，未绘制占位主体。'),
    timing?h('p',{class:'timing'},timing):null,
  ]);
}
function failureFixture() {
  return h('section',{class:'fixture','data-fixture-id':'cup-failure'},[
    meta('杯子 · 失败回放',['真实失败结果','不生成占位主体'],'真实 06 结果没有通过主体轮廓阶段；此处只保留原图与失败说明，不补画杯把、杯底或占位轮廓。'),
    h('div',{class:'failure'},[
      h('img',{src:'/fixtures/coffee.jpg',alt:'杯子现场照片，仅用于说明失败与未补造区域'}),
      h('div',[
        h('h2','推荐线稿未完成'),
        h('p',contract.failure_advice.notes[0]),
        h('p','未绘制主体轮廓，避免把整片画面填成并不存在的完整杯子。'),
      ]),
    ]),
  ]);
}
const timing=`<b>总用时</b> 73.1 秒（递增墙钟；页面加载后持续计时）。<b>固定事件时刻</b>：画面 37.33 秒、参数 67.20 秒、构图 73.12 秒、最终 73.12 秒。事件时刻不是阶段耗时；并行环节不能相加。`;
const markup={
  dog:()=>boardFixture({id:'dog',title:'狗 · 真实完整结果','tags':['真实结果回放','Worker 配色','ready/final 同源'],note:'由已保存的真实 02 结果经 completedComposition 与前端可信校验回放；本次不发送分析请求。',board:dog,reference:'/fixtures/dog.jpg',timing}),
  holes:()=>boardFixture({id:'holes',title:'孔隙 · 冻结契约','tags':['合成协议样例','evenodd','真实空隙'],note:'外环内的三角形孔保持透明；路径数量和闭合数与契约 fixture 一致。合成坐标不是照片效果证据。',board:holeBoard}),
  contours:()=>boardFixture({id:'contours',title:'多轮廓 · 冻结契约派生','tags':['合成协议样例','两个实心分部','不跨空隙填色'],note:'两个独立分部共享同一包围盒但分别成形，中间空隙不被连成大色块。',board:contourBoard}),
  continuous:()=>boardFixture({id:'continuous',title:'连续场景 · 冻结契约','tags':['合成协议样例','开放结构','不闭合'],note:'至少四条真实开放线覆盖双轴；路径不闭合、不填色，固定属性为 fixed。后端真实连续场景仍未验收。',board:continuousBoard}),
  'cup-failure':failureFixture,
};
createApp({render:()=>markup[caseId]?.()||h('p','未知样例')}).mount('#app');
document.body.dataset.fixture=caseId;
