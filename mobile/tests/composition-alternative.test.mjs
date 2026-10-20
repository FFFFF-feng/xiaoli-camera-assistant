import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {compositionComparisonProposals,enlargedCompositionAlternative,LOCAL_COMPARISON_NOTE} from '../src/composition-alternative.mjs';
import {sourceLayout,usableTargetBoard} from '../src/target-board.mjs';
import {sceneColorTransform} from '../src/scene-colors.mjs';
import {frameAspect} from '../src/composition-sketch.mjs';

function sourceProposal() {
  const wire=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url)));
  const board=structuredClone(wire.valid.find(item=>item.board.render_basis==='source_geometry'
    &&item.board.layers[0].representation!=='scene_structure').board);
  board.layout_mode='source_preserving';board.target_frame=[0,0,1,1];
  for(const layer of board.layers.filter(l=>l.role==='main')) {
    layer.bbox=[.25,.25,.55,.65];layer.source_bbox=[.25,.25,.55,.65];layer.photo_boundary=null;
  }
  return {action_type:'reshoot',goal:'保持当前机位',actions:['保持当前取景'],reasons:[],conditions:[],tradeoffs:[],
    limitations:[],knowledge_ids:[],storyboard:board};
}

test('原方案没有变化时默认提供真实轮廓的明显放大备选，原模型方案和数据完整保留',()=>{
  const p=sourceProposal(),before=structuredClone(p);
  const proposals=compositionComparisonProposals([p],'窗边静物，干净通透');
  assert.equal(proposals.length,2);assert.equal(proposals[1],p);
  const alternative=proposals[0],board=alternative.storyboard;
  assert.ok(usableTargetBoard(board));assert.equal(board.layout_mode,'schematic');
  assert.ok(alternative.limitations.includes(LOCAL_COMPARISON_NOTE));
  assert.ok(alternative.actions.some(s=>s.includes('靠近')));
  const a=before.storyboard.layers.find(l=>l.role==='main');
  const b=board.layers.find(l=>l.source_object_id===a.source_object_id);
  const unchangedWidth=(a.source_bbox[2]-a.source_bbox[0])*Math.min(1,board.source_photo_aspect/frameAspect(board.aspect));
  assert.ok(b.bbox[2]-b.bbox[0]>unchangedWidth*1.15);
  assert.deepEqual(b.outline,a.outline);assert.deepEqual(b.details,a.details);
  assert.deepEqual(b.source_bbox,a.source_bbox);assert.deepEqual(p,before);
  assert.ok(sourceLayout(board));assert.ok(sceneColorTransform(board));
});

test('多个主体统一缩放和平移，保持物体比例、彼此间距及全部关键边缘',()=>{
  const p=sourceProposal(),first=p.storyboard.layers.find(l=>l.role==='main');
  first.source_bbox=first.bbox=[.2,.3,.35,.6];
  p.storyboard.layers.push({...structuredClone(first),source_object_id:'object6',bbox:[.5,.35,.65,.65],source_bbox:[.5,.35,.65,.65]});
  const alternative=enlargedCompositionAlternative(p);
  assert.ok(alternative);
  const mains=alternative.storyboard.layers.filter(l=>l.role==='main');
  const scales=mains.map(l=>(l.bbox[2]-l.bbox[0])/(l.source_bbox[2]-l.source_bbox[0]));
  assert.ok(Math.abs(scales[0]-scales[1])<1e-10);
  assert.ok(mains.every(l=>Math.min(...l.bbox.slice(0,2))>=.039999&&Math.max(...l.bbox.slice(2))<=.960001));
});

test('已有明显推荐不重复生成；明确保留、连续场景、贴边、主体太大和缺少可信来源时不假放大',()=>{
  const p=sourceProposal();
  for(const intent of ['保持原构图','不要放大','拍完整环境全景'])assert.equal(enlargedCompositionAlternative(p,intent),null);
  const changed=structuredClone(p);changed.storyboard.layout_mode='schematic';
  assert.equal(enlargedCompositionAlternative(changed),null);
  const large=structuredClone(p);large.storyboard.layers[0].source_bbox=[.02,.02,.98,.98];
  assert.equal(enlargedCompositionAlternative(large),null);
  const clipped=structuredClone(p);clipped.storyboard.layers[0].photo_boundary={version:1,basis:'pixel_mask_v1',
    work_width:100,work_height:100,clipped_edges:['left'],visible_paths:[]};
  assert.equal(enlargedCompositionAlternative(clipped),null);
  const invalid=structuredClone(p);delete invalid.storyboard.layers[0].source_bbox;
  assert.equal(enlargedCompositionAlternative(invalid),null);
  const wire=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url)));
  const structure=wire.valid.find(item=>item.board.layers.some(l=>l.representation==='scene_structure'));
  assert.equal(enlargedCompositionAlternative({...p,storyboard:structure.board}),null);
});

test('环境一起变换并仅保留可见线段，不补画画外区域，也不改变原图取色的来源',()=>{
  const p=sourceProposal(),main=p.storyboard.layers.find(l=>l.role==='main');
  p.storyboard.layers.push({...structuredClone(main),source_object_id:'object5',role:'background',kind:'tree',
    bbox:[0,0,1,1],source_bbox:[0,0,1,1],representation:'context_lines',outline:[],contours:[],holes:[],
    details:[[[0,.4],[.5,.4],[1,.4]]],source_details:[[[0,.4],[.5,.4],[1,.4]]]});
  const board=enlargedCompositionAlternative(p).storyboard;
  const context=board.layers.find(l=>l.source_object_id==='object5');
  assert.equal(context.representation,'context_lines');assert.deepEqual(context.outline,[]);
  assert.deepEqual(context.source_details,p.storyboard.layers.at(-1).source_details);
  assert.ok(context.details.every(path=>path.every(point=>point.every(n=>n>=0&&n<=1))));
  assert.ok(sceneColorTransform(board));
});
