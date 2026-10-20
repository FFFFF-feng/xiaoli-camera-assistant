import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parse} from '@vue/compiler-sfc';
import {baseParse} from '@vue/compiler-dom';
import {compositionDifference} from '../src/composition-difference.mjs';
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url),'utf8'));
const board=()=>structuredClone(fixture.valid.find(item=>item.id==='silhouette_hole').board);

test('前后差值从实际轮廓位置计算，不能把请求放大幅度当已实现幅度',()=>{
  const value=board();Object.assign(value.layers[0],{source_bbox:[.3,.3,.5,.5],bbox:[.2,.2,.6,.6]});
  const before=structuredClone(value),change=compositionDifference(value);
  assert.ok(Math.abs(change.sourceWidth-20)<1e-10);
  assert.ok(Math.abs(change.targetWidth-40)<1e-10);
  assert.match(change.summary,/20% → 40%/);assert.equal(change.small,false);
  assert.deepEqual(value,before);
});

test('微小变化与保留原取景如实显示，坏数据不生成比较',()=>{
  const value=board();value.layers[0].bbox=[...value.layers[0].source_bbox];
  assert.equal(compositionDifference(value).small,true);
  const continuous=structuredClone(fixture.valid.find(item=>item.id==='continuous').board);
  continuous.layout_mode='source_preserving';
  assert.match(compositionDifference(continuous).summary,/保留原取景/);
  assert.equal(compositionDifference({}),null);
});

test('正式报告不再挂载 AI 构图预演，保留后端接口但不会自动请求配置',()=>{
  const text=readFileSync(new URL('../src/components/CompositionView.vue',import.meta.url),'utf8');
  assert.doesNotMatch(text,/CompositionPreview|editReference/);
  const ast=baseParse(parse(text).descriptor.template.content);
  assert.ok(ast.children.length);
});

test('主图和对照保留原图多色，不再以单一主色覆盖整个花簇或多色物体',()=>{
  const target=readFileSync(new URL('../src/components/TargetComposition.vue',import.meta.url),'utf8');
  const compare=readFileSync(new URL('../src/components/CompositionCompare.vue',import.meta.url),'utf8');
  assert.match(target,/hasSceneColor\?'none':targetLayerPaint/);
  assert.match(compare,/matchingColor\?'none':targetLayerPaint/);
  assert.doesNotMatch(target,/max-height:\s*520px/);
  assert.match(compare,/grid-template-columns:minmax\(0,1fr\)/);
});
