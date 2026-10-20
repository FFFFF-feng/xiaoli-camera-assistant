import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';

test('完整报告只显示一张现场操作卡，细节默认收起且浅彩双图仍在',async()=>{
  const wire=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url)));
  const board=structuredClone(wire.valid.find(item=>item.board.render_basis==='source_geometry'
    &&item.board.layers[0].representation!=='scene_structure').board);
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),configFile:false,
    plugins:[vue()],server:{middlewareMode:true,watch:null},appType:'custom',logLevel:'silent'});
  try {
    const {default:Component}=await server.ssrLoadModule('/src/components/CompositionView.vue');
    const proposal={goal:'突出主体',action_type:'camera_position',actions:['保持边缘完整。','保持边缘完整。',
      '检查光线。','安全试拍。','不要跨越护栏。'],reasons:['主体更突出'],conditions:['只在安全范围内移动'],
      tradeoffs:[],limitations:['需试拍'],storyboard:board};
    const composition={status:'unverified',observations:[],uncertainties:[],notes:[],proposals:[proposal]};
    const render=()=>renderToString(createSSRApp(Component,{preview:'',result:{scene:{},composition}}));
    let html=await render();
    assert.equal((html.match(/id="field-action-title"/g)||[]).length,1);
    assert.equal((html.match(/id="result-action-plan"/g)||[]).length,1);
    for(const label of ['当前问题','推荐动作','预期改善','拍完检查','其余 1 条动作','不要跨越护栏。'])assert.ok(html.includes(label),label);
    assert.match(html,/大幅构图前后对照/);assert.match(html,/物体取色/);
    assert.doesNotMatch(html,/先看这一点|接下来，照着这样拍|data-source-photo|data-target-frame/);
    assert.match(html,/<details[^>]*class="report-disclosure target-extra-details"[^>]*><summary[^>]*>线稿细节与说明/);
    assert.match(html,/<details class="advice-details report-disclosure"[^>]*><summary[^>]*>建议详情与适用条件/);
    assert.doesNotMatch(html,/<details[^>]*(?:target-extra-details|advice-details)[^>]*\sopen(?:[=>\s])/);
    assert.ok(html.indexOf('id="field-action-title"')<html.indexOf('target-extra-details'));
    proposal.storyboard=null;
    html=await render();assert.match(html,/现场操作卡/);assert.match(html,/仅有文字建议/);
    composition.proposals=[];
    html=await render();assert.doesNotMatch(html,/id="field-action-title"/);assert.match(html,/本次没有通过校验的构图方案/);
  } finally {await server.close();}
});
