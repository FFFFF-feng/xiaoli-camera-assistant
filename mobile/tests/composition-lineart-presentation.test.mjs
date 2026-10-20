import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';

test('保留浅彩线稿双图模式，未改变布局时明确提示且不挂载原照空框',async()=>{
  const wire=JSON.parse(readFileSync(new URL('../../tests/fixtures/composition_contract_v1.json',import.meta.url)));
  const board=structuredClone(wire.valid.find(item=>item.board.render_basis==='source_geometry'
    &&item.board.layers[0].representation!=='scene_structure').board);
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),configFile:false,
    plugins:[vue()],server:{middlewareMode:true,watch:null},appType:'custom',logLevel:'silent'});
  try{
    const {default:Component}=await server.ssrLoadModule('/src/components/CompositionView.vue');
    let intent='保持原构图';
    const render=()=>renderToString(createSSRApp(Component,{preview:'',intent,result:{scene:{},composition:{status:'unverified',
      observations:[],uncertainties:[],notes:[],proposals:[{goal:'突出主体',action_type:'reshoot',
        actions:['保持当前机位，不裁剪。'],reasons:[],conditions:[],tradeoffs:[],limitations:[],storyboard:board}]}}}));
    board.layout_mode='source_preserving';board.target_frame=[0,0,1,1];
    let html=await render();
    assert.match(html,/本次未调整取景/);assert.match(html,/原始布局线稿对照/);
    assert.match(html,/大幅构图前后对照/);assert.match(html,/原始布局构图对照/);
    assert.match(html,/保留原取景构图对照/);assert.match(html,/物体取色/);
    assert.doesNotMatch(html,/data-source-photo|data-target-frame|data-crop-preview|更紧凑的裁切对照/);
    board.layout_mode='schematic';delete board.target_frame;
    html=await render();
    assert.match(html,/推荐构图构图对照/);assert.doesNotMatch(html,/本次未调整取景/);
    board.layout_mode='source_preserving';board.target_frame=[0,0,1,1];
    for(const layer of board.layers.filter(l=>l.role==='main')) {
      layer.bbox=[.25,.25,.55,.65];layer.source_bbox=[.25,.25,.55,.65];layer.photo_boundary=null;
    }
    intent='突出主体，干净通透';
    html=await render();
    assert.match(html,/推荐构图构图对照/);assert.match(html,/原始布局构图对照/);
    assert.match(html,/本地取景备选/);assert.match(html,/方案2/);
    assert.doesNotMatch(html,/本次未调整取景/);
  }finally{await server.close();}
});
