import {test} from 'node:test';
import assert from 'node:assert/strict';
import {photoFrame} from '../src/photo-feedback.mjs';

test('保真预览使用原图像素坐标，只改变取景范围，不重新拼接或拉伸物体',()=>{
  assert.deepEqual(photoFrame(1600,1000,[.1,.2,.8,.9]),{x:160,y:200,width:1120,height:700,cropped:true});
  assert.deepEqual(photoFrame(1600,1000),{x:0,y:0,width:1600,height:1000,cropped:false});
});
test('历史坏坐标回退完整原图，缺失图像尺寸时不伪造预览',()=>{
  for(const crop of [[0,0,2,1],[0,0,NaN,1],[0,0,0,1],['0',0,1,1],[1,1,0,0]])
    assert.equal(photoFrame(1600,1000,crop).cropped,false);
  for(const [w,h] of [[0,1],[1,0],[NaN,1],[1,Infinity]])assert.equal(photoFrame(w,h),null);
});
