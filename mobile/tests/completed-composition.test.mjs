import {test} from 'node:test';
import assert from 'node:assert/strict';
import {completedComposition} from '../src/completed-composition.mjs';

const value=()=>({status:'unverified',observations:[],uncertainties:[],notes:[],
  diagnostics:[{stage:'layout',status:'complete',code:'local_layout_solved'}],
  proposals:[{goal:'保护建筑边缘',actions:['重新取景'],reasons:[],conditions:[],tradeoffs:[],limitations:[],
    storyboard:{aspect:'landscape',reference_photo_id:'photo1',intent:'突出建筑',distance_relation:'similar',
      distance_instruction:'检查边缘',render_basis:'source_geometry',layout_engine:'local_v1',source_photo_aspect:1.25,
      changes:[{problem:'主体偏小',adjustment:'适度靠近',benefit:'主体更清楚'}],limitations:['需现场核对'],
      layers:[{label:'建筑',kind:'building',role:'main',depth:1,bbox:[.1,.2,.9,.8],source_bbox:[.1,.2,.9,.8],
        source_object_id:'object1',mobility:'fixed',outline:[[0,0],[1,0],[1,1],[0,1]],details:[],color:'ochre',
        identity_features:['屋顶'],evidence_photo_ids:['photo1'],certainty:'approximate'}]}}]});

test('完整的本地布局可单独显示，不需要完整参数或写入历史',()=>{
  const source=value(),before=JSON.stringify(source);
  assert.equal(completedComposition(source,['photo1']).proposals[0].storyboard,source.proposals[0].storyboard);
  assert.equal(JSON.stringify(source),before);
});
test('旧版几何、未完成布局和错误参考图不能走提前显示入口',()=>{
  for(const edit of [v=>v.proposals[0].storyboard.layout_engine='legacy',
    v=>v.diagnostics[0].status='failed',v=>v.proposals[0].storyboard.reference_photo_id='photo2',
    v=>v.proposals[0].storyboard.layers[0].bbox=[0,0,2,2],v=>v.proposals[0].storyboard=null]) {
    const source=value();edit(source);assert.equal(completedComposition(source,['photo1']),null);
  }
});
test('参数完成前保持纯部分结果，缺失或不可用数据不能冒充完整图',()=>{
  for(const source of [null,{}, {...value(),status:'unavailable'},{...value(),proposals:[]}])
    assert.equal(completedComposition(source,['photo1']),null);
  assert.equal(completedComposition(value(),[]),null);
});
test('坏的部分图形事件被忽略，不中断仍在等待的最终方案',()=>{
  for(const source of [{...value(),diagnostics:{}},{...value(),diagnostics:[null]},
    {...value(),proposals:[null]}])assert.equal(completedComposition(source,['photo1']),null);
});
