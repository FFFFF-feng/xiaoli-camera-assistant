import { test } from 'node:test';
import assert from 'node:assert/strict';
import { usableSketch, usableFramingPlan, cameraMove, openSpace, sketchSpaceSide,
  sketchRenderMode, traceRequests, sketchLayout, layoutCaption } from '../src/composition-sketch.mjs';

const drawing = () => ({ aspect: 'portrait', caption: '树冠完整入画', camera_action: 'farther',
  camera_instruction: '后退一点，检查树冠四周余量', horizon_y: null,
  elements: [{ kind: 'tree', label: '树木', role: 'main', bbox: [.2, .12, .7, .9] }] });

test('原图取材区域与建议摆位分开校验，不接受坏坐标或空白特征', () => {
  const value=drawing();
  Object.assign(value.elements[0],{source_bbox:[.05,.05,.9,.95],identity_features:['树冠外沿','分叉树干']});
  assert.equal(usableSketch(value),value);
  value.elements[0].source_bbox=[0,0,'1',1]; assert.equal(usableSketch(value),null);
  value.elements[0].source_bbox=null; value.elements[0].identity_features=[' '];
  assert.equal(usableSketch(value),null);
});

test('检查单需完整的可读文字，坏数据回退到原方案', () => {
  const plan=Object.fromEntries(['diagnosis','visual_priority','placement','scale','negative_space',
    'edge_check','background_control','success_check'].map(k=>[k,'保留树冠完整轮廓']));
  assert.equal(usableFramingPlan(plan),plan);
  assert.equal(usableFramingPlan({...plan,edge_check:' '}),null);
  assert.equal(usableFramingPlan({...plan,scale:{html:'bad'}}),null);
  assert.equal(usableFramingPlan(null),null);
});

test('旧记录没有图时保留文字入口，合法示意可显示', () => {
  assert.equal(usableSketch(undefined), null);
  assert.equal(usableSketch(null), null);
  const value = drawing(); assert.equal(usableSketch(value), value);
});

test('拒绝越界、非数值和不完整主体的绘图数据', () => {
  for (const bbox of [[0, 0, Infinity, 1], [0, 0, '1', 1], [0, 0, 2, 1], [.5, 0, .3, 1], [0, 0, 1]]) {
    const value = drawing(); value.elements[0].bbox = bbox;
    assert.equal(usableSketch(value), null);
  }
  const value = drawing(); value.elements[0].role = 'context';
  assert.equal(usableSketch(value), null);
});

test('只允许固定线稿类型，机位箭头符合动作方向', () => {
  const value = drawing(); value.elements[0].kind = '<svg onload=alert(1)>';
  assert.equal(usableSketch(value), null);
  assert.ok(cameraMove('left').x < cameraMove('left').startX);
  assert.ok(cameraMove('right').x > cameraMove('right').startX);
  assert.ok(cameraMove('closer').y < cameraMove('closer').startY);
  assert.ok(cameraMove('farther').y > cameraMove('farther').startY);
  assert.ok(cameraMove('lower').y > cameraMove('lower').startY);
});

test('主题、旁白和物种形象可保留，未知图形数据不会进入绘制', () => {
  const value = drawing();
  Object.assign(value, { theme: '树下的片刻', mood: '宁静', narration: '用天空衬托完整的树冠。', space_note: '右侧保留天空' });
  Object.assign(value.elements[0], { appearance: 'broadleaf', facing: 'front', description: '完整树冠' });
  assert.equal(usableSketch(value), value);
  value.elements[0].appearance = 'arbitrary-svg';
  assert.equal(usableSketch(value), null);
  value.elements[0].appearance = 'pine'; value.narration = { html: 'bad' };
  assert.equal(usableSketch(value), null);
});

test('只在指定侧标记留白，并避开有线稿的环境，不另选更大的方向', () => {
  const main = [{ bbox: [.54,.27,.8,.9] }], context = [{ bbox: [.06,.1,.4,.84] }];
  const space = openSpace(main,'left',context);
  assert.ok(space.w * space.h >= .04);
  assert.equal(space.side,'left');
  assert.ok(space.x+space.w <= .54);
  for (const { bbox: [x1,y1,x2,y2] } of [...main,...context]) {
    assert.ok(space.x+space.w <= x1 || space.x >= x2 || space.y+space.h <= y1 || space.y >= y2);
  }
  assert.equal(openSpace(main,'none').w,0);
  assert.equal(openSpace([{bbox:[.02,.2,.99,.8]}],'right').side,'none');
  assert.equal(openSpace([{bbox:[0,0,1,1]}],'left').w,0);
  assert.equal(sketchSpaceSide({space_note:'左侧留白，但检查右侧边缘'}),'none');
  assert.equal(sketchSpaceSide({space_side:'none',space_note:'右侧留白'}),'none');
  assert.equal(sketchSpaceSide({space_note:'右侧保留运动空间'}),'right');
  for (const side of ['left','right','top','bottom']) {
    const result=openSpace([{bbox:[.2,.3,.8,.7]}],side);
    assert.equal(result.side,side);
  }
});

const tracedSubject = () => ({...drawing(),aspect:'square',photo_aspect:1,render_mode:'subject',
  source_margin:.02,space_side:'right',
  elements:[{kind:'pet',label:'狗',role:'main',source_bbox:[.4,.2,.7,.8],bbox:[.1,.2,.45,.8]}]});
const trace = aspect => ({aspect,ink:'data:image/png;base64,ink',wash:'data:image/png;base64,wash'});

test('新字段校验支持无可定位主体的完整场景，拒绝未知模式和坏原图比例', () => {
  const value={...drawing(),render_mode:'scene',elements:[],photo_aspect:2/3};
  assert.equal(usableSketch(value),value);
  for (const fields of [{render_mode:'split'},{space_side:'biggest'},{source_margin:.06},
    {source_margin:NaN},{photo_aspect:0},{photo_aspect:'1.5'}]) {
    assert.equal(usableSketch({...value,...fields}),null);
  }
  assert.equal(usableSketch({...value,render_mode:'subject'}),null);
});

test('连续场景只提取一张完整原图，并按原始比例叠加原坐标区域', () => {
  const value=tracedSubject();
  value.aspect='landscape'; value.photo_aspect=2/3;
  value.elements[0].kind='building';
  const requests=traceRequests(value);
  assert.deepEqual(requests,[{key:'scene',sourceBox:null}]);
  const result=sketchLayout(value,{scene:trace(.7)});
  assert.equal(result.mode,'scene');
  assert.equal(result.aspect,.7,'实际加载的原图比例优先');
  assert.equal(sketchLayout(value).aspect,2/3,'历史记录使用后端保存的原图比例');
  assert.deepEqual(result.layers[0].drawnBox,value.elements[0].source_bbox);
  assert.equal(result.fullTrace.aspect,.7);
  assert.equal(result.space.side,'none');
  assert.equal(sketchLayout({...value,elements:[]}).placement,null);
  assert.equal(sketchRenderMode({...tracedSubject(),elements:[tracedSubject().elements[0],
    {...tracedSubject().elements[0],label:'另一只狗'}]}),'scene');
  assert.equal(sketchRenderMode(drawing()),'scene','缺取材框不把整图当作主体搬动');
});

test('主体与环境取材交叠时保留整幅结构，完全内含道具不复制', () => {
  const value=tracedSubject();
  value.elements.push({kind:'object',role:'context',label:'桌沿',source_bbox:[.2,.6,.6,.9],bbox:[0,.7,1,1]});
  assert.equal(sketchRenderMode(value),'scene');
  value.elements[1].source_bbox=[.45,.3,.6,.6];
  assert.equal(sketchRenderMode(value),'subject');
  assert.deepEqual(traceRequests(value).map(job=>job.key),[0]);
});

test('无取材环境不生成占位遮挡，也不挤占主角右侧留白', () => {
  const value=tracedSubject();
  value.elements.push({kind:'object',role:'context',label:'草地',bbox:[.5,0,1,1]});
  const result=sketchLayout(value,{0:trace(.5)});
  assert.deepEqual(traceRequests(value).map(job=>job.key),[0]);
  assert.equal(result.layers.length,1);
  assert.equal(result.items[1].visible,false);
  assert.equal(result.space.x,result.main.drawnBox[2]);
  assert.equal(result.space.w,1-result.main.drawnBox[2]);
  assert.equal(sketchLayout(value).space.side,'none','线稿失败或未加载时不留下误导蓝块');
});

test('绘制顺序固定环境、主角，再由视图统一画标注，模型顺序不能遮盖主体', () => {
  const value=tracedSubject();
  const context={kind:'tree',role:'context',label:'树',source_bbox:[.01,.1,.2,.8],bbox:[0,0,1,1]};
  value.elements.push(context);
  let result=sketchLayout(value,{0:trace(.5),1:trace(.45)});
  assert.deepEqual(result.layers.map(layer=>layer.role),['context','main']);
  value.elements.reverse();
  result=sketchLayout(value,{0:trace(.45),1:trace(.5)});
  assert.deepEqual(result.layers.map(layer=>layer.role),['context','main']);
});

test('实际轮廓比例、标注占比和四边余量来自同一布局，更多边缘后重新计算', () => {
  const value=tracedSubject();
  const job=traceRequests(value)[0], more=traceRequests(value,{extraMargin:true})[0];
  assert.ok(job.sourceBox[0] < value.elements[0].source_bbox[0]);
  assert.ok(more.sourceBox[0] < job.sourceBox[0]);
  for (const aspect of [.5,1,2]) {
    const result=sketchLayout(value,{0:trace(aspect)}), box=result.main.drawnBox;
    assert.ok(Math.abs((box[2]-box[0])*result.aspect/(box[3]-box[1])-aspect)<1e-10);
    assert.equal(result.placement.width,Math.round((box[2]-box[0])*100));
    assert.equal(result.placement.height,Math.round((box[3]-box[1])*100));
    assert.equal(result.placement.left,Math.round(box[0]*100));
    assert.equal(result.placement.right,Math.round((1-box[2])*100));
    assert.ok(layoutCaption(result).includes(`宽约${result.placement.width}%`));
    assert.ok(layoutCaption(result).includes(`高约${result.placement.height}%`));
  }
});

test('旧记录多侧留白不擅自选方向，顶部底部识别与后端一致', () => {
  assert.equal(sketchSpaceSide({space_note:'四周与右侧都留余量'}),'none');
  assert.equal(sketchSpaceSide({space_note:'顶部留出空间'}),'top');
  assert.equal(sketchSpaceSide({space_note:'底部留出空间'}),'bottom');
  assert.equal(sketchSpaceSide({space_note:'画面右留出空间'}),'right');
});

test('任意两块环境或保护余量交叠时整体描摹，额外边缘不复制背景', () => {
  const value=tracedSubject();
  value.elements[0].source_bbox=[.01,.1,.2,.5];
  value.elements.push(...[[.5,.1,.7,.8],[.715,.1,.9,.8]].map(source_bbox=>({
    kind:'object',role:'context',label:'环境',source_bbox,bbox:[.5,.1,.9,.9]})));
  assert.equal(sketchRenderMode(value),'subject');
  assert.equal(sketchRenderMode(value,{extraMargin:true}),'scene');
  assert.deepEqual(traceRequests(value,{extraMargin:true}),[{key:'scene',sourceBox:null}]);
  value.elements[2].source_bbox=[.6,.5,.9,.9];
  assert.equal(sketchRenderMode(value),'scene');
});
