import {test} from 'node:test';
import assert from 'node:assert/strict';
import {outlinePath,silhouetteStrokePath,unknownFrameRects,usableTargetBoard} from '../src/target-board.mjs';
import {readFileSync} from 'node:fs';
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url)));
const layer=()=>({bbox:[.2,.1,.8,.9],outline:[[0,0],[1,0],[1,1],[0,1]],holes:[],outline_style:'angular',
  photo_boundary:{version:1,basis:'pixel_mask_v1',work_width:100,work_height:100,clipped_edges:['bottom'],
    visible_paths:[[[1,1],[1,0],[0,0],[0,1]]]}});
test('closed fill and open visible perimeter are distinct, with no invented bottom edge',()=>{
  const p=layer();assert.match(outlinePath(p,100,100),/Z$/);
  const stroke=silhouetteStrokePath(p,100,100);assert.ok(!stroke.includes('Z'));
  assert.equal(stroke,'M80.00,90.00L80.00,10.00L20.00,10.00L20.00,90.00');
});
test('holes remain closed strokes and transparent fill while the outer crop edge stays open',()=>{
  const p=layer();p.holes=[[[.3,.3],[.6,.3],[.5,.6]]];
  assert.equal((outlinePath(p,100,100).match(/Z/g)||[]).length,2);
  assert.equal((silhouetteStrokePath(p,100,100).match(/Z/g)||[]).length,1);
});
test('legacy input remains readable and does not acquire invented boundary metadata',()=>{
  const p=layer();delete p.photo_boundary;
  assert.equal(silhouetteStrokePath(p,100,100),outlinePath(p,100,100));
  assert.ok(!p.photo_boundary);
});
test('unknown field complement is bounded, explicit and absent in source view',()=>{
  const b={observed_frame:[0,.1,1,.9]};
  assert.deepEqual(unknownFrameRects(b),[[0,0,1,.1],[0,.9,1,.09999999999999998]]);
  assert.deepEqual(unknownFrameRects(b,true),[]);
});
test('malformed or excessive boundary metadata is rejected without weakening old fixtures',()=>{
  const b=structuredClone(fixture.valid.find(v=>v.id==='silhouette_hole').board);
  b.layers[0].photo_boundary=layer().photo_boundary;
  assert.ok(usableTargetBoard(b));
  b.layers[0].photo_boundary.clipped_edges=['invented'];assert.equal(usableTargetBoard(b),null);
});
