/* Real TargetComposition.vue replay. No business API, session or cloud access. */
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
if(process.argv.includes('--help')){
  console.log('node replay-e2-offline.cjs REPLAY_DIR NEW_OUT_DIR E2_ROOT PLAYWRIGHT_PACKAGE [ORIGIN]');process.exit(0);
}
const [inputArg,outArg,e2Arg,playwrightArg,originArg]=process.argv.slice(2);
const {chromium}=require(playwrightArg||'playwright');
const input=path.resolve(inputArg),out=path.resolve(outArg),e2=path.resolve(e2Arg);
const root=path.resolve(__dirname,'../../..'),origin=originArg||'http://127.0.0.1:5201',fileMode=origin.startsWith('file://');
fs.mkdirSync(out,{recursive:false});
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const proof={kind:'formal_TargetComposition_offline_replay_v1',input,started_at:new Date().toISOString(),
  rows:{},blocked_posts:[],blocked_external:[],page_errors:[],console_errors:[],worker_canvas:{},actual_analysis_posts:0,cloud_requests:0};
const items=['06','07','02'].flatMap(id=>['e2-original','offline-baseline','candidate'].map(flavor=>
  ({id,flavor,result:path.join(input,id,`${flavor}.json`),photo:path.join(input,id,'original.jpg')})));
items.push({id:'02-historical-roi',flavor:'candidate',result:path.join(input,'02-historical-roi/candidate.json'),photo:path.join(input,'02/original.jpg')});
function instrument(canvas){return `window.__workerProof={created:0,success:0,errors:0};
  ${canvas?'window.Worker=undefined;window.OffscreenCanvas=undefined;':`const OriginalWorker=window.Worker;
  window.Worker=class extends OriginalWorker {constructor(...args){super(...args);window.__workerProof.created++;
    this.addEventListener('message',event=>{if(event.data?.error)window.__workerProof.errors++;else window.__workerProof.success++;});}};`}`;}
async function render(browser,item,viewport,canvas=false){
  const key=`${item.id}-${item.flavor}-${viewport.name}${canvas?'-canvas':''}`;
  const context=await browser.newContext({viewport:{width:viewport.width,height:viewport.height},deviceScaleFactor:1,serviceWorkers:'block'});
  await context.addInitScript(instrument(canvas));
  if(fileMode){
    const contract=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/composition_contract_v1.json'),'utf8'));
    const result=JSON.parse(fs.readFileSync(item.result,'utf8'));
    const fixtureCase=item.id.replace('-historical-roi','');
    const photo=`data:image/jpeg;base64,${fs.readFileSync(item.photo).toString('base64')}`;
    await context.addInitScript(({fixtures,photos})=>{
      globalThis.__OFFLINE_FIXTURES=fixtures;globalThis.__OFFLINE_PHOTOS=photos;
    },{fixtures:{'/fixtures/contract.json':contract,'/fixtures/dog-result.json':result,[`/fixtures/result-${fixtureCase}.json`]:result},
      photos:{'/fixtures/dog.jpg':photo,[`/fixtures/photo-${fixtureCase}.jpg`]:photo}});
  }
  await context.route('**/*',route=>{
    const req=route.request(),url=req.url();
    if(url.startsWith('data:')||url.startsWith('blob:'))return route.continue();
    if(!['GET','HEAD'].includes(req.method())){
      proof.blocked_posts.push({key,url,method:req.method()});return route.abort();
    }
    if(fileMode&&url.startsWith('file://'))return route.continue();
    if(!fileMode&&!url.startsWith(origin+'/')){proof.blocked_external.push({key,url});return route.abort();}
    if(fileMode){proof.blocked_external.push({key,url});return route.abort();}
    const pathname=new URL(url).pathname;
    const fixtures={'/fixtures/contract.json':path.join(root,'tests/fixtures/composition_contract_v1.json'),
      '/fixtures/dog-result.json':item.result,'/fixtures/dog.jpg':item.photo,
      [`/fixtures/result-${item.id.replace('-historical-roi','')}.json`]:item.result,
      [`/fixtures/photo-${item.id.replace('-historical-roi','')}.jpg`]:item.photo};
    if(fixtures[pathname])return route.fulfill({status:200,contentType:pathname.endsWith('.jpg')?'image/jpeg':'application/json',body:fs.readFileSync(fixtures[pathname])});
    if(pathname==='/favicon.ico')return route.fulfill({status:204,body:''});
    if(pathname.startsWith('/api/')||pathname==='/session')return route.abort();
    return route.continue();
  });
  const page=await context.newPage();let probing=false;
  page.on('pageerror',error=>proof.page_errors.push({key,message:String(error)}));
  page.on('console',message=>{if(message.type()==='error'&&!probing)proof.console_errors.push({key,message:message.text()});});
  try{
    const fixtureCase=item.id.replace('-historical-roi','');
    const pageUrl=fileMode?`${origin}?case=${fixtureCase}`:origin+`/tests/visual/target-board.html?case=${fixtureCase}`;
    await page.goto(pageUrl,{waitUntil:'networkidle'});
    await page.locator('.target-composition').waitFor();
    await page.locator('[data-scene-color] image').waitFor({timeout:20000});
    await page.evaluate(()=>document.fonts.ready);
    const data=await page.evaluate(()=>{
      const svg=document.querySelector('.target-sheet svg');
      const paths=[...svg.querySelectorAll('path')].map(p=>({d:p.getAttribute('d'),fill:p.getAttribute('fill'),stroke:p.getAttribute('stroke')}));
      return {overflow:document.documentElement.scrollWidth-innerWidth,paths,
        palette:[...svg.querySelectorAll('[data-representation] path[fill-rule]')].map(p=>p.getAttribute('fill')),
        scene_href:svg.querySelector('[data-scene-color] image')?.getAttribute('href')||'',
        worker:window.__workerProof,unknown_field_rects:svg.querySelectorAll('[data-unknown-photo-field] rect').length,
        cut_note:document.querySelector('[data-photo-boundary-note]')?.textContent||'',
        missing_note:document.querySelector('[data-unrendered-objects]')?.textContent||'',
        svg_bad_numbers:/NaN|Infinity/.test(svg.outerHTML),reference_count:document.querySelectorAll('.target-reference img').length};
    });
    data.geometry_sha256=hash(JSON.stringify(data.paths));delete data.paths;
    data.palette_sha256=hash(JSON.stringify(data.palette));delete data.palette;
    data.scene_color_sha256=hash(data.scene_href);delete data.scene_href;
    await page.locator('.target-composition').screenshot({path:path.join(out,key+'.png')});
    if(fileMode){
      const svg=await page.locator('.target-sheet svg').evaluate(node=>new XMLSerializer().serializeToString(node));
      fs.writeFileSync(path.join(out,key+'.svg'),svg);
    }else{
      const waiting=page.waitForEvent('download');
      await page.getByRole('button',{name:'保存推荐图'}).click();
      const download=await waiting;await download.saveAs(path.join(out,key+'.svg'));
    }
    data.saved_svg_bad_numbers=/NaN|Infinity/.test(fs.readFileSync(path.join(out,key+'.svg'),'utf8'));
    if(viewport.name==='desktop'){
      probing=true;
      const probes=await page.evaluate(async()=>Promise.all(['/api/v1/analyze','/api/v1/composition-preview'].map(async url=>{
        try{await fetch(url,{method:'POST',body:'{}',headers:{'content-type':'application/json'}});return true;}catch{return false;}
      })));
      proof.actual_analysis_posts+=probes.filter(Boolean).length;probing=false;
    }
    proof.rows[key]=data;
    fs.writeFileSync(path.join(out,'replay-checks.json'),JSON.stringify(proof,null,2));
  }finally{await context.close();}
}
const escape=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
function gallery(){
  let body='<h1>E2 原始结果与离线修复候选</h1><p>真实云预算8/8，新增云请求0。保留真实E2截图；其余图由当前正式组件重放，不是新一轮完整云成功。旧算法使用已存分割后几何，原始识别框与mask缺失。历史ROI像素诊断另列。</p>';
  for(const id of ['06','07','02']){
    const old=path.join(e2,'visual-frontend',`${id}-desktop.png`);
    fs.copyFileSync(old,path.join(out,`${id}-E2-captured.png`));
    const original=path.relative(out,path.join(input,id,'original.jpg')).split(path.sep).join('/');
    body+=`<section><h2>${id}</h2><div class="row"><article><h3>真实原图</h3><img src="${escape(original)}"></article><article><h3>实际E2截图（旧版捕获）</h3><a href="${id}-E2-captured.png"><img src="${id}-E2-captured.png"></a></article><article><h3>旧布局算法离线重放</h3><a href="${id}-offline-baseline-desktop.png"><img src="${id}-offline-baseline-desktop.png"></a></article><article><h3>修复候选／正式组件</h3><a href="${id}-candidate-desktop.png"><img src="${id}-candidate-desktop.png"></a><p><a href="${id}-candidate-mobile390.png">390px</a> · <a href="${id}-candidate-desktop.svg">实际导出SVG</a></p></article></div></section>`;
  }
  body+='<section><h2>02 · 10月17日历史识别ROI的独立像素诊断</h2><p>这不是E2原始识别框；只能证明局部候选在这份历史输入上的像素结果，不能补造E2成功或耳眼质量结论。</p><a href="02-historical-roi-candidate-desktop.png"><img class="historical" src="02-historical-roi-candidate-desktop.png"></a></section>';
  fs.writeFileSync(path.join(out,'gallery.html'),'<!doctype html><meta charset="utf-8"><title>E2离线对照</title><style>body{font:15px/1.7 system-ui;margin:24px;background:#f7f8f6;color:#253746}section{margin:32px 0}.row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}article{min-width:0;background:white;padding:12px}img{width:100%;height:auto}h3{font-size:14px}.historical{max-width:780px}@media(max-width:800px){.row{grid-template-columns:1fr 1fr}}@media(max-width:480px){.row{grid-template-columns:1fr}}</style>'+body);
}
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
    args:fileMode?['--allow-file-access-from-files','--disable-web-security']:[]});
  try{
    for(const item of items){
      for(const viewport of [{name:'desktop',width:1440,height:1000},{name:'mobile390',width:390,height:844}])await render(browser,item,viewport);
      if(item.flavor==='candidate'){
        await render(browser,item,{name:'desktop',width:1440,height:1000},true);
        const a=proof.rows[`${item.id}-candidate-desktop`],b=proof.rows[`${item.id}-candidate-desktop-canvas`];
        proof.worker_canvas[item.id]={geometry_equal:a.geometry_sha256===b.geometry_sha256,
          palette_equal:a.palette_sha256===b.palette_sha256,scene_color_equal:a.scene_color_sha256===b.scene_color_sha256,
          worker_success:a.worker.success>0&&a.worker.errors===0,canvas_no_worker:b.worker.created===0};
      }
    }
    gallery();
    proof.ok=proof.actual_analysis_posts===0&&proof.blocked_external.length===0&&proof.page_errors.length===0&&proof.console_errors.length===0
      &&Object.values(proof.rows).every(r=>r.overflow<=0&&!r.svg_bad_numbers&&!r.saved_svg_bad_numbers&&r.reference_count===1)
      &&Object.values(proof.worker_canvas).every(row=>Object.values(row).every(Boolean));
  }finally{proof.finished_at=new Date().toISOString();fs.writeFileSync(path.join(out,'replay-checks.json'),JSON.stringify(proof,null,2));await browser.close();}
  console.log(JSON.stringify({ok:proof.ok,rows:Object.keys(proof.rows).length,worker_canvas:proof.worker_canvas,
    blocked_posts:proof.blocked_posts.length,actual_analysis_posts:proof.actual_analysis_posts,page_errors:proof.page_errors,console_errors:proof.console_errors}));
  if(!proof.ok)process.exitCode=1;
})().catch(error=>{console.error(error);process.exitCode=1;});
