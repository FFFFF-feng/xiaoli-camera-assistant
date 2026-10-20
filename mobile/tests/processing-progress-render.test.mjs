import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';

test('等待页按环节显示进度与动态，等待提示不伪造成剩余时间',async()=>{
  const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),configFile:false,
    plugins:[vue()],server:{middlewareMode:true,watch:null},appType:'custom',logLevel:'silent'});
  try {
    const {default:Component}=await server.ssrLoadModule('/src/components/ProcessingProgress.vue');
    const render=props=>renderToString(createSSRApp(Component,props));
    let html=await render({percent:53,message:'拍摄建议已校验，正在继续整理构图画面…',
      history:['已收到照片','正在检索资料'],waiting:true});
    assert.match(html,/<progress[^>]*value="53"[^>]*max="100"/);
    assert.match(html,/role="status" aria-live="polite" aria-atomic="true"/);
    assert.match(html,/查看处理动态/);assert.match(html,/仍在处理中/);
    assert.doesNotMatch(html,/<details[^>]*\sopen[=>\s]/);
    assert.doesNotMatch(html,/剩余\s*\d+\s*秒|已用时|接收.*字符/);
    html=await render({percent:NaN,message:'等待服务',receiving:true});
    assert.match(html,/<progress[^>]*value="0"/);assert.match(html,/陆续返回/);
    html=await render({percent:120,message:'完成'});assert.match(html,/<progress[^>]*value="100"/);
  } finally {await server.close();}
});

test('拍摄页和建议页使用同一等待组件，保留真实器材与知识工作台绑定',()=>{
  const app=readFileSync(new URL('../src/App.vue',import.meta.url),'utf8');
  assert.equal((app.match(/<ProcessingProgress\b/g)||[]).length,2);
  assert.match(app,/advanceAnalysisProgress\(progress.value/);
  assert.match(app,/completedComposition\(event.value,pendingPhotos.value/);
  assert.match(app,/referenceLensSettings/);assert.match(app,/localWorkbenchUrl/);
  assert.doesNotMatch(app,/progressMessage|receivedChars|phaseTimings|statusStartedAt/);
});
