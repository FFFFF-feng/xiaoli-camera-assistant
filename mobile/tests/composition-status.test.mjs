import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parse} from '@vue/compiler-sfc';
import {baseParse} from '@vue/compiler-dom';
import {compositionStatus} from '../src/composition-status.mjs';

test('检索有依据不代表线稿成功；优先呈现轮廓失败，不把下游意图缺失当成另一独立故障',()=>{
  const advice={status:'grounded',proposals:[{}],diagnostics:[
    {stage:'recognition',status:'complete',code:'objects_validated'},
    {stage:'contours',status:'failed',code:'no_usable_geometry'},
    {stage:'intent',status:'skipped',code:'source_geometry_unavailable'},
  ]};
  const status=compositionStatus(advice,{},false);
  assert.equal(status.badge,'仅文字方案');
  assert.equal(status.reason,'主体轮廓提取未完成。');
  assert.equal(status.failed,true);
});
test('旧版只有备注时仍归类轮廓失败，但不向默认提示塞入整段备注',()=>{
  const notes=['引用摄影知识。','未能从照片中分离出完整的主要主体轮廓；背景相近可能影响提取。'];
  const status=compositionStatus({status:'grounded',proposals:[{}],notes},{},false);
  assert.equal(status.reason,'主体轮廓提取未完成。');
  assert.ok(!status.reason.includes('背景相近'));
});
test('服务失败与前端绘图校验失败分别显示，不冒充手机性能问题',()=>{
  const service=compositionStatus({diagnostics:[{stage:'recognition',status:'failed',code:'recognition_service_failed'}]},null,false);
  assert.match(service.reason,/服务未完成/);
  const display=compositionStatus({status:'grounded'},{storyboard:{}},false);
  assert.match(display.reason,/显示校验/);
});
test('成功、待试拍、演示和未开启状态不显示失败说明',()=>{
  assert.equal(compositionStatus({status:'grounded'},{},true).badge,'线稿已生成');
  assert.equal(compositionStatus({status:'unverified'},{},true).badge,'待试拍验证');
  assert.equal(compositionStatus({status:'demo'},null,false).failed,false);
  assert.equal(compositionStatus(null,null,false).failed,false);
});
test('未知失败不猜测具体原因，也不触发再次分析',()=>{
  const status=compositionStatus({status:'unavailable',proposals:[],notes:[]},null,false);
  assert.equal(status.reason,'这次未生成可展示的线稿。');
  assert.equal(status.badge,'构图未完成');
});

function template(file){
  const text=readFileSync(new URL(file,import.meta.url),'utf8');
  return baseParse(parse(text).descriptor.template.content);
}
function visit(node,ancestors,check){
  check(node,ancestors);
  for(const child of node.children||[])visit(child,[...ancestors,node],check);
}
const closedDetails=node=>node.tag==='details'&&!node.props.some(p=>p.name==='open'||p.arg?.content==='open');

test('构图原始备注只在默认收起的详情内，失败卡只呈现一句原因和可执行入口',()=>{
  let notes=0;
  visit(template('../src/components/CompositionView.vue'),[],(node,parents)=>{
    if(node.props?.some(p=>p.name==='for'&&p.exp?.content==='note in result.composition?.notes')){
      notes++;assert.ok(parents.some(closedDetails));
    }
  });
  assert.equal(notes,1);
});
test('参数理由与校验说明留在折叠区，试拍调整不与依据混成一长列',()=>{
  let reasons=0;
  visit(template('../src/App.vue'),[],(node,parents)=>{
    if(node.props?.some(p=>p.name==='for'&&p.exp?.content.includes('result.recommendation.reasons'))){
      reasons++;assert.ok(parents.some(closedDetails));
    }
  });
  assert.equal(reasons,1);
});
test('现场操作卡保持可见，三分线教学仍默认收起',()=>{
  let comparison=0,guide=0;
  visit(template('../src/components/TargetComposition.vue'),[],(node,parents)=>{
    if(node.props?.some(p=>p.name==='class'&&p.value?.content.includes('target-changes'))){
      comparison++;assert.equal(node.tag,'section');
      assert.ok(node.props.some(p=>p.name==='data-field-actions'));
    }
    if(node.props?.some(p=>p.name==='if'&&p.exp?.content==='grid')&&node.tag==='p'){
      guide++;assert.ok(parents.some(closedDetails));
    }
  });
  assert.equal(comparison,1);assert.equal(guide,1);
});
