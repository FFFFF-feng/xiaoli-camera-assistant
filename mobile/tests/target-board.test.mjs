import {test} from 'node:test';
import assert from 'node:assert/strict';
import {usableTargetBoard,projectedPoints} from '../src/target-board.mjs';
const board=()=>({aspect:'landscape',reference_photo_id:'photo1',intent:'突出连廊结构',distance_relation:'similar',distance_instruction:'横向取景，检查立柱轮廓',limitations:['新视角需现场核对'],changes:[{problem:'树遮挡主体',adjustment:'将树作为边缘前景',benefit:'连廊更清晰'}],layers:[{label:'建筑',kind:'building',role:'main',depth:1,bbox:[.1,.2,.9,.8],outline:[[0,0],[1,0],[1,1],[0,1]],details:[[[.2,0],[.2,1]]],color:'ochre',identity_features:['横向连廊'],evidence_photo_ids:['photo1'],certainty:'approximate'}]});
test('推荐画面由目标几何绘制，不依赖照片裁片；同一细节随目标框移动',()=>{
  const value=board();assert.equal(usableTargetBoard(value),value);
  assert.equal(projectedPoints(value.layers[0],[[0,0],[1,1]],100,100),'10.00,20.00 90.00,80.00');
  value.layers[0].bbox=[.48,.1,.52,.9];assert.equal(usableTargetBoard(value),value);
});
test('拒绝注入、越界、退化轮廓、未知图号和不含主体的推荐分镜',()=>{
  for(const mutate of [b=>b.layers[0].outline[0]=['<svg>',0],b=>b.layers[0].bbox[2]=Infinity,
    b=>b.layers[0].outline=[[0,0],[.5,.5],[1,1]],b=>b.layers[0].evidence_photo_ids=['photo9'],
    b=>b.layers[0].role='background',b=>b.changes=[]]){
    const value=board();mutate(value);assert.equal(usableTargetBoard(value),null);
  }
});
