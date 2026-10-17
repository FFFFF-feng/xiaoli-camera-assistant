import test from 'node:test';
import assert from 'node:assert/strict';
import { extendSceneBackground,sceneContinuationPaths,sceneEdgeDirections } from '../src/scene-extension.mjs';

const image=(width,height,at)=>({width,height,data:Uint8ClampedArray.from(Array.from({length:width*height},(_,p)=>at(p%width,Math.floor(p/width))).flat())});
const tree=path=>({kind:'tree',representation:'context_lines',source_bbox:[0,0,1,1],source_details:[path]});
const t={x:.1,y:.25,width:.8,height:.5};

test('被照片边缘截断的枝条使用真实切线方向，原物体和坐标不改写',()=>{
  const board={layers:[tree([[.25,0],[.3,.1],[.35,.2],[.4,.3]])]},before=structuredClone(board);
  const directions=sceneEdgeDirections(board,100,100);
  const top=directions.find(d=>d.side===0);
  assert.ok(top);
  assert.ok(Math.abs(top.drift+.5)<1e-9);
  assert.ok(Math.abs(top.curve)<1e-9);
  assert.deepEqual(board,before);
  const paths=sceneContinuationPaths([top],{...t,y:.2,height:.8},100,100,100,100);
  assert.equal(paths.length,1);
  assert.ok(paths[0].path.startsWith('M30.00,20.00'));
  // Moving upward must also move left; a clamped vertical strip would keep x=30.
  const last=paths[0].path.split('L').at(-1).split(',').map(Number);
  assert.ok(last[0]<20&&last[1]<0);
});

test('内部线段不续画，建筑仅延伸可靠直边，不把锯齿枝叶当建筑补齐',()=>{
  const straight={...tree([[.6,0],[.55,.1],[.5,.2],[.45,.3]]),kind:'building'};
  const hardEdges=sceneEdgeDirections({layers:[straight]},100,100);
  assert.ok(hardEdges.length>0&&hardEdges.every(d=>d.curve===0));
  const jagged={...tree([[.5,0],[.7,.01],[.3,.02],[.6,.08],[.4,.2]]),kind:'building'};
  assert.equal(sceneEdgeDirections({layers:[jagged]},100,100).length,0);
  assert.equal(sceneEdgeDirections({layers:[tree([[.3,.3],[.4,.4],[.5,.5]])]},100,100).length,0);
});

test('填色沿观察到的斜边方向续接，不把边缘直接拉成矩形',()=>{
  const source=image(60,40,(x,y)=>x>=20+y*.5&&x<30+y*.5?[90,160,115,255]:[220,240,205,255]);
  const result=extendSceneBackground(source,t,120,80);
  const at=(x,y)=>[...result.data.slice((y*120+x)*4,(y*120+x)*4+4)];
  assert.deepEqual(at(36,0),[90,160,115,255]);
  assert.deepEqual(at(52,0),[220,240,205,255]);
});

test('补齐四边和角落，只写入未拍到区域，不覆盖原图或复制主体',()=>{
  const source=image(20,12,()=>[190,220,160,255]),before=source.data.slice();
  const result=extendSceneBackground(source,{x:.2,y:.2,width:.6,height:.6},100,80);
  for(let y=0;y<80;y++)for(let x=0;x<100;x++) {
    const inside=x>=20&&x<80&&y>=16&&y<64;
    assert.equal(result.data[(y*100+x)*4+3],inside?0:255);
  }
  assert.deepEqual(source.data,before);
});

test('画面已满或无可用颜色时不产生延伸层，非法尺寸不进行计算',()=>{
  const source=image(8,8,()=>[120,180,100,255]);
  assert.equal(extendSceneBackground(source,{x:0,y:0,width:1,height:1},20,20),null);
  assert.equal(extendSceneBackground(image(8,8,()=>[0,0,0,0]),t,20,20),null);
  assert.throws(()=>extendSceneBackground(source,t,1000,1000),RangeError);
  assert.throws(()=>extendSceneBackground(source,{...t,width:0},20,20),RangeError);
});

test('极大缺口只作短程轮廓推测，路径长度有界，不尝试无限续画',()=>{
  const directions=sceneEdgeDirections({layers:[tree([[.25,0],[.3,.1],[.35,.2],[.4,.3]])]},100,100);
  const paths=sceneContinuationPaths(directions,{x:.4,y:.4,width:.00001,height:.00001},100,100,720,540);
  assert.ok(paths.every(p=>p.path.length<2000));
});
