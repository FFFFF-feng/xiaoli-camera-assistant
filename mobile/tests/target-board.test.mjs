import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DEFAULT_TARGET_COLOR,DEFAULT_TARGET_GRID,thirdsGuide,targetLayerPaint,usableTargetBoard,projectedPoints,outlinePath,sourceLayout,silhouetteLayers,detailPath,targetCompositionCopy} from '../src/target-board.mjs';
const board=()=>({aspect:'landscape',reference_photo_id:'photo1',intent:'突出连廊结构',distance_relation:'similar',distance_instruction:'横向取景，检查立柱轮廓',limitations:['新视角需现场核对'],changes:[{problem:'树遮挡主体',adjustment:'将树作为边缘前景',benefit:'连廊更清晰'}],layers:[{label:'建筑',kind:'building',role:'main',depth:1,bbox:[.1,.2,.9,.8],outline:[[0,0],[1,0],[1,1],[0,1]],details:[[[.2,0],[.2,1]]],color:'ochre',identity_features:['横向连廊'],evidence_photo_ids:['photo1'],certainty:'approximate'}]});
test('保留取景文案按场景说明原因，不声称原图更优或虚构特定物体',()=>{
  const source={...board(),layout_mode:'source_preserving',layers:[{...board().layers[0],representation:'scene_structure'}]};
  const copy=targetCompositionCopy(source);
  assert.equal(copy.status,'未模拟新机位');
  assert.equal(copy.heading,'当前取景与现场调整');
  assert.match(copy.reason,/连续场景/);
  assert.match(copy.reason,/真实空间关系/);
  assert.doesNotMatch(copy.reason,/原图更优|路牌|路灯/);
  assert.equal(copy.action,source.distance_instruction);
  assert.match(copy.drawing,/未模拟新机位/);
  assert.equal(copy.changeText,source.changes[0].adjustment);
});
test('普通 schematic 与 crop_projection 继续使用推荐构图示意',()=>{
  for(const layout_mode of [undefined,'schematic','crop_projection']) {
    const copy=targetCompositionCopy({...board(),layout_mode});
    assert.equal(copy.heading,'推荐构图示意');
    assert.equal(copy.changeLabel,'推荐调整');
    assert.match(copy.drawing,/不代表真实新机位效果/);
  }
});
test('贴边与近似恒等变换的原因区分，未知画外内容保持未知',()=>{
  const source={...board(),layout_mode:'source_preserving'};
  assert.match(targetCompositionCopy(source).reason,/变化很小/);
  source.layers[0].source_bbox=[0,.1,.4,.8];
  assert.match(targetCompositionCopy(source).reason,/画外形体未知/);
});
test('淡彩默认开启，主体浅填色且不改变几何或原始资料',()=>{
  const layer=board().layers[0],before=JSON.stringify(layer);
  assert.equal(DEFAULT_TARGET_COLOR,true);
  const paint=targetLayerPaint(layer);
  assert.equal(paint.fill,'#e7c38d');assert.equal(paint.fillOpacity,.82);
  assert.equal(paint.stroke,'#415970');assert.equal(JSON.stringify(layer),before);
  layer.kind='flower';layer.color='slate';assert.equal(targetLayerPaint(layer).fill,'#ead9ae');
});
test('环境只改变线色，不能给开放线条补填充块；关闭淡彩恢复原线稿',()=>{
  const layer={...board().layers[0],role:'foreground',representation:'context_lines',kind:'tree'};
  const green=targetLayerPaint(layer);
  assert.equal(green.fill,'none');assert.equal(green.fillOpacity,0);assert.equal(green.stroke,'#4f7b56');
  layer.kind='building';assert.equal(targetLayerPaint(layer).stroke,'#967241');
  const plain=targetLayerPaint(layer,false);
  assert.equal(plain.fill,'none');assert.equal(plain.stroke,'#71859a');
  assert.deepEqual(targetLayerPaint(board().layers[0],false),{fill:'#fff',fillOpacity:1,stroke:'#415970'});
});
test('三分线默认显示，横竖画幅均精确等分，四交点不会随主体移动',()=>{
  assert.equal(DEFAULT_TARGET_GRID,true);
  for(const [w,h] of [[720,540],[720,960],[720,720],[720,480]]) {
    const guide=thirdsGuide(w,h);
    assert.equal(guide.lines.length,4);assert.equal(guide.points.length,4);
    assert.deepEqual(guide.lines,[[w/3,0,w/3,h],[w*2/3,0,w*2/3,h],[0,h/3,w,h/3],[0,h*2/3,w,h*2/3]]);
    assert.deepEqual(guide.points,[[w/3,h/3],[w*2/3,h/3],[w/3,h*2/3],[w*2/3,h*2/3]]);
  }
  for(const dims of [[0,100],[100,-1],[NaN,100],[100,Infinity]])assert.throws(()=>thirdsGuide(...dims),RangeError);
});
test('推荐画面由目标几何绘制，不依赖照片裁片；同一细节随目标框移动',()=>{
  const value=board();assert.equal(usableTargetBoard(value),value);
  assert.equal(projectedPoints(value.layers[0],[[0,0],[1,1]],100,100),'10.00,20.00 90.00,80.00');
  value.layers[0].bbox=[.48,.1,.52,.9];assert.equal(usableTargetBoard(value),value);
  value.layers[0].kind='light';assert.equal(usableTargetBoard(value),value);
});
test('轮廓拒绝非零面积自交和折返；允许首尾闭合与曲线风格',()=>{
  for(const outline of [ [[0,0],[1,1],[0,1],[1,.4],[.8,0]], [[0,0],[1,0],[.5,0],[1,1],[0,1]] ]) {
    const value=board();value.layers[0].outline=outline;assert.equal(usableTargetBoard(value),null);
  }
  const value=board();value.layers[0].outline.push([0,0]);value.layers[0].outline_style='curved';
  assert.equal(usableTargetBoard(value),value);
  value.layers[0].outline_style='<script>';assert.equal(usableTargetBoard(value),null);
});
test('曲线只用于明确标注的外形，硬边保留直线；曲线控制点不越出目标框',()=>{
  const layer=board().layers[0];
  assert.equal(outlinePath(layer,100,100),'M10.00,20.00L90.00,20.00L90.00,80.00L10.00,80.00Z');
  layer.outline_style='curved';
  const path=outlinePath(layer,100,100);assert.match(path,/Q/);assert.ok(path.endsWith('Z'));
  const coords=[...path.matchAll(/([\d.]+),([\d.]+)/g)].map(m=>[+m[1],+m[2]]);
  assert.ok(coords.every(([x,y])=>x>=10&&x<=90&&y>=20&&y<=80));
  layer.outline.push([0,0]);assert.equal(outlinePath(layer,100,100),path);
});
test('拒绝注入、越界、退化轮廓、未知图号和不含主体的推荐分镜',()=>{
  for(const mutate of [b=>b.layers[0].outline[0]=['<svg>',0],b=>b.layers[0].bbox[2]=Infinity,
    b=>b.layers[0].outline=[[0,0],[.5,.5],[1,1]],b=>b.layers[0].evidence_photo_ids=['photo9'],
    b=>b.layers[0].role='background',b=>b.changes=[]]){
    const value=board();mutate(value);assert.equal(usableTargetBoard(value),null);
  }
});

const linked=()=>{
  const b=board();b.render_basis='source_geometry';b.layout_mode='schematic';b.source_photo_aspect=1.5;
  Object.assign(b.layers[0],{source_object_id:'object1',source_bbox:[.2,.3,.8,.7],mobility:'fixed'});
  return b;
};
const withContext=()=>{
  const b=linked();
  b.layers.push({...b.layers[0],source_object_id:'object2',role:'background',depth:0,
    representation:'context_lines',outline:[],contours:[],details:[[[0,.2],[1,.2]]],
    source_details:[[[.1,.3],[.9,.4]]],source_bbox:[0,0,1,1]});
  return b;
};
test('环境线条不填充遮挡主体，原始布局使用未裁去的原图路径',()=>{
  const b=withContext();assert.equal(usableTargetBoard(b),b);
  const context=b.layers[1];
  assert.deepEqual(silhouetteLayers(context),[]);
  assert.equal(outlinePath(context,100,100),'');
  assert.equal(sourceLayout(b).layers[1].details,context.source_details);
  assert.equal(sourceLayout(b).layers[1].bbox[2],1);
  context.outline_style='curved';
  assert.ok(!detailPath(context,[[0,0],[.5,.6],[1,1]],100,100).includes('Q'));
});
test('不能用环境线条冒充主体、空线条或无依据的原始对照',()=>{
  for(const mutate of [l=>l.role='main',l=>l.details=[],l=>delete l.source_details,
    l=>l.source_details=[[[0,0],[Infinity,1]]],l=>l.outline=[[0,0],[1,0],[1,1]],
    l=>l.contours=[[[0,0],[1,0],[1,1]]],l=>l.representation='unknown']) {
    const b=withContext();mutate(b.layers[1]);assert.equal(usableTargetBoard(b),null);
  }
});
const continuous=()=>{
  const b=linked();
  b.layout_mode='source_preserving';
  Object.assign(b.layers[0],{representation:'scene_structure',outline:[],contours:[],outline_style:'curved',
    details:[[[0,.8],[.3,.2],[.7,.3],[1,.6]],[[0,.9],[1,.9]],[[0,.1],[.3,.2]],[[.7,.3],[1,.1]]],
    source_details:[[[0,.75],[.3,.1],[.7,.25],[1,.5]],[[0,.85],[1,.85]],
      [[0,.05],[.3,.15]],[[.7,.25],[1,.05]]]});
  return b;
};
test('连续场景保留main身份，开放主结构不填充、不柔化、不被转为闭合主体',()=>{
  const b=continuous(),layer=b.layers[0];
  assert.equal(usableTargetBoard(b),b);
  assert.equal(layer.role,'main');assert.deepEqual(silhouetteLayers(layer),[]);
  assert.equal(targetLayerPaint(layer).fill,'none');assert.equal(targetLayerPaint(layer,false).fillOpacity,0);
  const path=detailPath(layer,layer.details[0],100,100);
  assert.ok(!/[QZ]/.test(path));assert.match(path,/^M10.00,68.00L/);
  const original=sourceLayout(b);
  assert.equal(original.layers[0].details,layer.source_details);
  assert.deepEqual(original.layers[0].bbox,layer.source_bbox);
});
test('连续主场景必须有独立来源路径与source_geometry，仍拒绝空线条或假闭合轮廓',()=>{
  for(const mutate of [b=>delete b.render_basis,b=>b.render_basis='legacy',b=>b.layers[0].representation='context_lines',b=>b.layers[0].details=[],
    b=>delete b.layers[0].source_details,b=>b.layers[0].source_details=[],
    b=>b.layers[0].outline=[[0,0],[1,0],[1,1]],b=>b.layers[0].contours=[[[0,0],[1,0],[1,1]]],
    b=>b.layers[0].source_details=[[[0,0],[1,Infinity]]]]) {
    const b=continuous();mutate(b);assert.equal(usableTargetBoard(b),null);
  }
  const old=linked();assert.equal(usableTargetBoard(old),old,'旧封闭轮廓保持兼容');
});
test('连续场景与后端一致：至少四条开放线、双轴覆盖各0.5且必须固定',()=>{
  const good=continuous();
  assert.equal(usableTargetBoard(good),good);
  for(const mutate of [
    b=>b.layers[0].details=b.layers[0].details.slice(0,3),
    b=>b.layers[0].details=[[[0,.1],[.4,.2]],[[0,.8],[.4,.9]],[[.1,.2],[.2,.3]],[[.3,.4],[.4,.5]]],
    b=>b.layers[0].details=[[[.1,.2],[.45,.3]],[[.1,.5],[.45,.6]],[[.2,.3],[.3,.4]],[[.3,.4],[.4,.5]]],
    b=>b.layers[0].mobility='movable',
    b=>b.layers[0].mobility='unknown',
    b=>delete b.layers[0].mobility,
    b=>b.layers[0].source_details=b.layers[0].source_details.slice(0,3),
    b=>b.layers[0].source_details=[[[.1,.2],[.45,.3]],[[.1,.5],[.45,.6]],[[.2,.3],[.3,.4]],[[.3,.4],[.4,.5]]],
  ]) {
    const b=continuous();mutate(b);assert.equal(usableTargetBoard(b),null);
  }
  const boundary=continuous();
  boundary.layers[0].details=[[[0,0],[.5,0]],[[0,.5],[.5,.5]],[[0,.5],[0,1]],[[.5,.5],[.5,1]]];
  boundary.layers[0].source_details=boundary.layers[0].details;
  assert.equal(usableTargetBoard(boundary),boundary,'恰好0.5的覆盖是有效边界');
});
test('原始布局和目标布局共用轮廓，但分别使用原图位置和目标位置',()=>{
  const b=linked(),snapshot=JSON.stringify(b),source=sourceLayout(b);
  assert.equal(usableTargetBoard(b),b);assert.equal(source.aspect,1.5);
  assert.deepEqual(source.layers[0].bbox,[.2,.3,.8,.7]);
  assert.equal(source.layers[0].outline,b.layers[0].outline);
  assert.equal(source.layers[0].details,b.layers[0].details);
  assert.equal(projectedPoints(source.layers[0],[[0,0],[1,1]],100,100),'20.00,30.00 80.00,70.00');
  assert.equal(JSON.stringify(b),snapshot);
  assert.equal(sourceLayout(board()),null);
});
test('新版线稿必须具有可信的引用格式与原图位置，不能用缺失数据的历史图冒充',()=>{
  for(const mutate of [b=>delete b.source_photo_aspect,b=>b.source_photo_aspect=Infinity,
    b=>b.layers[0].source_bbox=[0,0,0,1],b=>b.layers[0].source_bbox=['0',0,1,1],
    b=>b.layers[0].source_object_id='object9',b=>delete b.layers[0].mobility,
    b=>b.layers.push({...b.layers[0]}),b=>b.layout_mode='fake']){
    const b=linked();mutate(b);assert.equal(usableTargetBoard(b),null);assert.equal(sourceLayout(b),null);
  }
});

test('独立花朵轮廓共用同一目标坐标，不能填成连接各花朵的大色块',()=>{
  const b=linked(),layer=b.layers[0];
  layer.contours=[[[0,0],[.35,0],[.35,1],[0,1]],[[.65,0],[1,0],[1,1],[.65,1]]];
  layer.details=Array.from({length:96},()=>[[.1,.2],[.2,.3]]);
  assert.equal(usableTargetBoard(b),b);
  const shapes=silhouetteLayers(layer);
  assert.equal(shapes.length,2);
  assert.equal(shapes[0].bbox,layer.bbox);
  assert.equal(shapes[1].bbox,layer.bbox);
  assert.notEqual(outlinePath(shapes[0],100,100),outlinePath(shapes[1],100,100));
  layer.details.push([[0,0],[1,1]]);assert.equal(usableTargetBoard(b),null);
  layer.details=[];layer.contours[0]=[[0,0],[1,1],[0,1],[1,0]];assert.equal(usableTargetBoard(b),null);
});

test('花瓣结构柔化保留开放端点，建筑硬线与真实闭合结构分别处理',()=>{
  const layer=board().layers[0];
  const path=[[.1,.2],[.5,.8],[.9,.2]];
  assert.equal(detailPath(layer,path,100,100),'M18.00,32.00L50.00,68.00L82.00,32.00');
  layer.outline_style='curved';
  const rounded=detailPath(layer,path,100,100);
  assert.match(rounded,/^M18.00,32.00/);assert.ok(rounded.endsWith('L82.00,32.00'));
  assert.match(rounded,/Q/);assert.ok(!rounded.includes('Z'));
  assert.ok(detailPath(layer,[...path,path[0]],100,100).endsWith('Z'));
  const coords=[...rounded.matchAll(/([\d.]+),([\d.]+)/g)].map(m=>[+m[1],+m[2]]);
  assert.ok(coords.every(([x,y])=>x>=18&&x<=82&&y>=32&&y<=68));
});
test('真实主体孔隙作为同一复合路径保留，原始对照共用孔隙而非另填色块',()=>{
  const b=linked(),layer=b.layers[0];
  layer.holes=[[[.2,.2],[.4,.2],[.3,.6]]];
  assert.equal(usableTargetBoard(b),b);
  const path=outlinePath(layer,100,100);
  assert.equal((path.match(/M/g)||[]).length,2);assert.equal((path.match(/Z/g)||[]).length,2);
  assert.equal(sourceLayout(b).layers[0].holes,layer.holes);
  assert.equal(silhouetteLayers(layer).length,1);
  layer.contours=[[[0,0],[.45,0],[.45,1],[0,1]],[[.55,0],[1,0],[1,1],[.55,1]]];
  assert.equal(usableTargetBoard(b),null,'后端禁止孔隙与多轮廓同时非空');
  assert.deepEqual(silhouetteLayers(layer),[],'即使误传无效组合也不能渲染成填色岛');
  delete layer.holes;
  assert.equal(usableTargetBoard(b),b);
  const parts=silhouetteLayers(layer);
  assert.equal(parts.length,2);
  assert.equal((outlinePath(parts[0],100,100).match(/M/g)||[]).length,1);
  assert.equal((outlinePath(parts[1],100,100).match(/M/g)||[]).length,1);
});
test('主体孔拒绝自交、外露、跨边界、重叠及过量路径，旧记录无需补孔字段',()=>{
  const good=[[.2,.2],[.4,.2],[.3,.6]];
  for(const holes of [null,[[[0,0],[.4,.2],[.3,.6]]],[[[.2,.2],[.4,.6],[.2,.6],[.4,.2]]],
    [[[.2,.2],[1.1,.2],[.3,.6]]],[good,good],Array.from({length:13},()=>good)]){
    const b=linked();b.layers[0].holes=holes;assert.equal(usableTargetBoard(b),null);
  }
  const b=continuous();b.layers[0].holes=[good];assert.equal(usableTargetBoard(b),null);
  assert.equal(usableTargetBoard(linked())?.layers[0].holes,undefined);
});

test('冻结契约样例逐项对齐：三个有效、四个无效且失败建议不生成占位主体',()=>{
  const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url),'utf8'));
  assert.deepEqual(fixture.valid.map(item=>item.id),['legacy','silhouette_hole','continuous']);
  assert.deepEqual(fixture.invalid.map(item=>item.id),['context_main','outside_hole','closed_scene','missing_source']);
  for(const item of fixture.valid)assert.equal(usableTargetBoard(item.board),item.board,item.id);
  for(const item of fixture.invalid)assert.equal(usableTargetBoard(item.board),null,item.id);
  assert.equal(usableTargetBoard(fixture.failure_advice),null);
});

test('近似恒等变换与旧记录兼容，可选目标框拒绝越界或伪造来源',()=>{
  const b=linked();b.layout_mode='source_preserving';b.target_frame=[0,0,1,1];
  assert.equal(usableTargetBoard(b),b);
  delete b.target_frame;assert.equal(usableTargetBoard(b),b);
  for(const target_frame of [[0,0,2,1],[.5,0,.4,1],['0',0,1,1],[]])
    assert.equal(usableTargetBoard({...b,target_frame}),null);
  assert.equal(usableTargetBoard({...b,render_basis:'legacy'}),null);
});
