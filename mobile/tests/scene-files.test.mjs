import {test} from 'node:test';
import assert from 'node:assert/strict';
import {selectSceneFiles} from '../src/scene-files.mjs';
const file=(name,size=100,type='image/jpeg')=>({name,size,type,lastModified:1});
test('多图选择去重并允许补充，主图不会被重复项挤掉',()=>{
  const a=file('a.jpg'),b=file('b.jpg');
  assert.deepEqual(selectSceneFiles([a],[a,b]),[b]);
  assert.deepEqual(selectSceneFiles([a],[a]),[]);
});
test('一次选择含坏文件、超张数或超总量时整批拒绝，保留原有场景',()=>{
  const existing=[file('a.jpg')];
  assert.throws(()=>selectSceneFiles(existing,[file('b.jpg'),file('x.heic',100,'image/heic')]),/JPEG/);
  assert.throws(()=>selectSceneFiles(existing,[file('b.jpg'),file('c.jpg')],2),/最多/);
  assert.throws(()=>selectSceneFiles(existing,[file('big.jpg',2*1024*1024)],6,15,1),/合计/);
  assert.equal(existing.length,1);
});
