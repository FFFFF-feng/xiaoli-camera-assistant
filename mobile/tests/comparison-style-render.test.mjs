import test,{after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createServer} from 'vite';
import {createSSRApp,h} from 'vue';
import {renderToString} from '@vue/server-renderer';

const root=fileURLToPath(new URL('..',import.meta.url));
const server=await createServer({root,server:{middlewareMode:true},appType:'custom'});
after(()=>server.close());
const TargetComposition=(await server.ssrLoadModule('/src/components/TargetComposition.vue')).default;
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url),'utf8'));
const render=(board,reference='')=>renderToString(createSSRApp(()=>h(TargetComposition,{board,reference})));

test('默认真实Vue分支渲染原始布局与推荐构图双图，不被原照取景框替换',async()=>{
  const board=structuredClone(fixture.valid.find(row=>row.id==='silhouette_hole').board);
  const html=await render(board);
  assert.match(html,/data-comparison-frame="source"/);
  assert.match(html,/data-comparison-frame="target"/);
  assert.match(html,/同一组已提取轮廓/);
  assert.match(html,/同一组轮廓，比较取景与主体占比/);
  assert.doesNotMatch(html,/本地紧凑裁切|原照与取景提示|source-framing/);
});

test('保留原取景显示原图与现场提示，不将近似原图重描为推荐对照',async()=>{
  const board=structuredClone(fixture.valid.find(row=>row.id==='continuous').board);
  board.layout_mode='source_preserving';
  const html=await render(board,'data:image/png;base64,TEST');
  assert.match(html,/data-source-photo-guide/);
  assert.match(html,/未模拟新机位/);
  assert.match(html,/data-field-actions/);
  assert.doesNotMatch(html,/data-comparison-frame|data-scene-extension/);
});
