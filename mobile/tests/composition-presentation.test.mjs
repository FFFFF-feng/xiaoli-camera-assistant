import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fieldActions,sourceFrameGuide} from '../src/composition-presentation.mjs';
import {createServer} from 'vite';
import {createSSRApp,h} from 'vue';
import {renderToString} from 'vue/server-renderer';
import {readFileSync} from 'node:fs';

const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url),'utf8'));
const samples=JSON.parse(readFileSync(new URL('./fixtures/composition-presentation.json',import.meta.url),'utf8'));
const board=()=>({...structuredClone(fixture.valid.find(f=>f.id==='silhouette_hole').board),
  layout_mode:'source_preserving',target_frame:[0,0,1,1]});

test('动作卡复用原建议，箭头与相机移动一致，主体余量来自原图',()=>{
  const b=board();b.layers[0].source_bbox=[0,.1,.5,.9];
  const card=fieldActions(b,['向左移动，适当后退','降低机位'],{success_check:'检查主体完整'});
  assert.equal(card.check,'检查主体完整');
  assert.equal(card.problem,b.changes.map(c=>c.problem).join('；'));
  const guide=sourceFrameGuide(b,card.actions);
  assert.equal(guide.margins[0].percent,0);assert.equal(guide.margins[0].near,true);
  assert.equal(guide.margins[0].contact,false);
  const left=guide.directions.find(d=>d.label==='左移'),back=guide.directions.find(d=>d.label==='后退');
  assert.ok(left.x2<left.x1);assert.ok(back.y2>back.y1);
  assert.ok(guide.directions.some(d=>d.label==='降低机位'));
  assert.deepEqual(sourceFrameGuide(b,['不要左移，也无需后退']).directions,[]);
  assert.deepEqual(sourceFrameGuide(b,[]).directions,[],'不从主体平移推断机位方向');
});

test('真实 Vue 渲染区分原图取景、推荐示意和缺图回退，保持 AI 预演默认关闭',async()=>{
  const server=await createServer({server:{middlewareMode:true},appType:'custom'});
  try {
    const {default:Target}=await server.ssrLoadModule('/src/components/TargetComposition.vue');
    const render=props=>renderToString(createSSRApp({render:()=>h(Target,props)}));
    assert.deepEqual(samples.map(s=>s.board.layout_mode),['source_preserving','schematic','source_preserving','source_preserving']);
    for(const sample of samples) {
      const rendered=await render(sample);
      assert.match(rendered,/data-field-actions/);
      assert.ok(rendered.includes(sample.actions[0]));
      if(sample.board.layout_mode==='source_preserving') {
        assert.match(rendered,/data-source-photo-guide/);
        assert.doesNotMatch(rendered,/class="target-sheet"|data-scene-extension/);
      }
    }
    const b=board(),actions=['左移一步','后退一点'];
    const html=await render({board:b,reference:'data:image/png;base64,TEST',actions});
    assert.match(html,/data-source-photo-guide/);assert.match(html,/data-target-frame/);
    assert.match(html,/未模拟新机位/);assert.match(html,/data-camera-direction/);
    assert.match(html,/现场操作卡/);assert.match(html,/左移一步/);
    assert.doesNotMatch(html,/class="target-sheet"|推荐构图线稿|data-scene-extension|原图更优/);
    const missing=await render({board:b,actions});
    assert.match(missing,/原图暂不可用/);assert.doesNotMatch(missing,/data-target-frame/);
    b.layout_mode='schematic';
    const schematic=await render({board:b,actions});
    assert.match(schematic,/class="target-sheet"/);assert.match(schematic,/不代表真实新机位效果/);
    assert.match(schematic,/现场操作卡/);assert.doesNotMatch(schematic,/data-source-photo-guide/);
    b.layout_mode='crop_projection';
    assert.match(await render({board:b,actions}),/class="target-sheet"/);
    const {default:View}=await server.ssrLoadModule('/src/components/CompositionView.vue');
    b.layout_mode='source_preserving';
    const result={composition:{status:'unverified',proposals:[{storyboard:b,actions,goal:'保护主体',action_type:'reshoot',
      reasons:[],conditions:[],tradeoffs:[],limitations:[]}],observations:[],uncertainties:[],notes:[]}};
    const view=await renderToString(createSSRApp({render:()=>h(View,{result,preview:'data:image/png;base64,TEST'})}));
    assert.match(view,/当前取景与现场调整/);assert.doesNotMatch(view,/推荐构图线稿/);
    assert.doesNotMatch(view,/AI 生成、未验证真实性/,'未主动请求 AI 预演');
  } finally {await server.close();}
});
