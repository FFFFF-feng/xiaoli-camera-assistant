import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {paintObjectRegion,diagramColor,softContextPixels,backgroundWash,lineartPaint,colorizeScenePixels,OBJECT_COLOR_VERSION} from '../src/scene-colors.mjs';
const pixels=(width,height,at)=>({width,height,data:Uint8ClampedArray.from(Array.from({length:width*height},(_,p)=>at(p%width,Math.floor(p/width))).flat())});
const at=(image,x,y)=>[...image.data.slice((y*image.width+x)*4,(y*image.width+x)*4+4)];

test('只在实际物体掩码内填色，孔洞、分离间隙和外部背景保持透明',()=>{
  const original=pixels(30,24,x=>x<15?[230,25,30,255]:[20,45,220,255]);
  const mask=pixels(30,24,(x,y)=>[0,0,0,x>2&&x<27&&y>2&&y<21&&!(x>10&&x<19&&y>8&&y<15)?255:0]);
  const before=original.data.slice(),out=paintObjectRegion(original,mask.data);
  assert.equal(at(out,0,0)[3],0);assert.equal(at(out,14,11)[3],0);
  assert.equal(at(out,5,5)[3],255);assert.deepEqual(original.data,before);
});

test('同一个物体里的红蓝分区都保留，颜色平滑不跨越强色差边界',()=>{
  const original=pixels(30,20,x=>x<15?[220,25,30,255]:[20,45,215,255]);
  const mask=pixels(30,20,()=>[255,255,255,255]);
  const out=paintObjectRegion(original,mask.data);
  for(const x of [10,14])assert.ok(at(out,x,10)[0]-at(out,x,10)[2]>100);
  for(const x of [15,20])assert.ok(at(out,x,10)[2]-at(out,x,10)[0]>100);
});

test('不同物体独立平滑，黑色外部背景不会污染白色主体或透明孔洞',()=>{
  const original=pixels(20,20,(x,y)=>x>6&&x<14&&y>6&&y<14?[240,238,227,255]:[0,10,0,255]);
  const mask=pixels(20,20,(x,y)=>[255,255,255,x>6&&x<14&&y>6&&y<14?255:0]);
  const out=paintObjectRegion(original,mask.data);
  assert.ok(at(out,7,7)[0]>235);assert.equal(at(out,6,7)[3],0);
});

test('暗色物体适度提亮，环境更淡，但不把深绿重映射成粉色或纯黑',()=>{
  const green=diagramColor([12,35,8]);
  assert.ok(green[1]>green[0]&&green[0]>65);
  const foreground=diagramColor([12,35,8],'foreground');
  const background=diagramColor([12,35,8],'background');
  assert.ok(background[0]>foreground[0]&&foreground[0]>green[0]);
  assert.ok(diagramColor([0,0,0])[0]>85);
  assert.equal(lineartPaint({role:'main'}).stroke,'#4b555b');
  assert.ok(lineartPaint({role:'background'}).opacity<lineartPaint({role:'main'}).opacity);
});

test('环境底色是低透明度连续参考，不再产生全画幅不透明黑绿斑块',()=>{
  const original=pixels(45,45,(x,y)=>[x%3?5:30,y%5?20:80,5,255]);
  const out=softContextPixels(original);
  assert.ok(at(out,20,20)[3]<=31);
  const wash=backgroundWash(original,new Uint8Array(45*45));
  assert.ok(parseInt(wash.slice(1,3),16)>225);
  const empty=softContextPixels(pixels(10,10,()=>[255,0,0,0]));
  assert.ok(empty.data.every(n=>n===0));
});

test('物体填色保持源透明度，不接受无界输入或不匹配掩码',()=>{
  const original=pixels(10,10,()=>[90,100,70,127]),mask=pixels(10,10,()=>[0,0,0,255]);
  assert.equal(at(paintObjectRegion(original,mask.data),5,5)[3],127);
  assert.throws(()=>paintObjectRegion(original,new Uint8Array(2)),RangeError);
  assert.throws(()=>paintObjectRegion({width:721,height:721,data:[]},[]),RangeError);
  assert.throws(()=>softContextPixels(original,.8),RangeError);
});

test('开放连续场景不伪造闭合物体或实体填色，只返回淡环境层',()=>{
  const source=pixels(20,20,()=>[5,20,5,255]);
  const value=colorizeScenePixels(source,{layers:[{role:'main',representation:'scene_structure'}]},()=>({getContext:()=>({})}));
  assert.equal(value.version,OBJECT_COLOR_VERSION);
  assert.ok(value.pixels.data.every(n=>n===0));
  assert.deepEqual(value.fills,[[]]);
  assert.ok(at(value.contextPixels,10,10)[3]<=140);
});

test('正式管线不再调用整图色阶量化或补画背景，单图与对照使用同一物体填色',()=>{
  const code=readFileSync(new URL('../src/scene-colors.mjs',import.meta.url),'utf8');
  const production=code.split('export function colorizeScenePixels')[1].split('export function scenePixelsUrl')[0];
  assert.doesNotMatch(production,/flatSceneColors|illustrationColor|mergeSmallPatches/);
  const target=readFileSync(new URL('../src/components/TargetComposition.vue',import.meta.url),'utf8');
  const compare=readFileSync(new URL('../src/components/CompositionCompare.vue',import.meta.url),'utf8');
  assert.doesNotMatch(target,/sceneRenderer\.extension|referenceOutlineColor|extendBackground/);
  assert.match(target,/OBJECT_COLOR_VERSION/);assert.match(compare,/OBJECT_COLOR_VERSION/);
});
