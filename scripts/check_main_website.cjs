const fs = require('fs');
const path = require('path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'data/history/main-acceptance-20261014');
const live = path.join(evidence, 'live');
const ui = path.join(evidence, 'ui');
fs.mkdirSync(ui, {recursive:true});
const manifest = JSON.parse(fs.readFileSync(path.join(root,'data/history/main-acceptance-plan-20261014/manifest.json'),'utf8'));
const save = (file, value) => fs.writeFileSync(path.join(ui,file),JSON.stringify(value,null,2));
let activeBrowser, activePage;

(async () => {
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  activeBrowser=browser;
  const context = await browser.newContext({viewport:{width:1365,height:1000}});
  const page = await context.newPage();
  activePage=page;
  const consoleEvents=[];
  async function select(label, value) {
    const combo=page.getByRole('combobox',{name:label,exact:true});
    if(await combo.inputValue()===value)return;
    await page.keyboard.press('Escape');
    await combo.evaluate(el=>el.scrollIntoView({block:'center',behavior:'instant'}));
    await combo.click();
    try{await page.getByRole('option',{name:value,exact:true}).waitFor({state:'attached',timeout:2500});}
    catch(e){await combo.click();await page.getByRole('option',{name:value,exact:true}).waitFor({state:'attached',timeout:5000});}
    const options=await page.getByRole('option').allTextContents();
    const index=options.indexOf(value);
    if(index<0)throw new Error(label+' option not present: '+value);
    await page.keyboard.press('Home');
    for(let i=0;i<index;i++)await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await page.keyboard.press('Tab');
    if(await combo.inputValue()!==value)throw new Error(label+' selection did not match '+value);
  }
  page.on('console',msg=>{if(['error','warning'].includes(msg.type()))consoleEvents.push({type:msg.type(),text:msg.text()});});
  page.on('pageerror',err=>consoleEvents.push({type:'pageerror',text:err.message}));
  await page.goto('http://127.0.0.1:8501/',{waitUntil:'domcontentloaded'});
  await page.getByText('上传现场原图',{exact:true}).waitFor({timeout:40000});
  save('initial.json',{url:page.url(),title:await page.title(),dom:await page.locator('body').ariaSnapshot(),consoleEvents});
  await page.screenshot({path:path.join(ui,'initial.png'),fullPage:true});
  if(process.argv[2]!=='run') {await browser.close();console.log('initial page inspected, zero model calls');return;}
  const selected = process.argv.slice(3);
  for(const item of manifest.cases.filter(x=>!selected.length||selected.includes(x.id))) {
    if(fs.existsSync(path.join(live,item.id+'-calls.json'))) {console.log(item.id+' already attempted; skipped');continue;}
    await page.goto('http://127.0.0.1:8501/',{waitUntil:'domcontentloaded'});
    await page.getByText('上传现场原图',{exact:true}).waitFor({timeout:40000});
    await page.locator('input[type=file]').setInputFiles(path.join(root,item.image));
    await page.getByText('现场图已上传',{exact:true}).waitFor({timeout:30000});
    await page.getByRole('textbox',{name:'你想拍出什么效果？',exact:true}).fill(item.request.intent);
    await page.getByRole('radiogroup',{name:'主体会动吗？',exact:true}).getByText(item.request.subject_motion,{exact:true}).click();
    await page.getByRole('radiogroup',{name:'怎么拍？',exact:true}).getByText(item.request.tripod?'三脚架':'手持',{exact:true}).click();
    await page.getByText('相机与镜头（选填）',{exact:true}).click();
    await select('相机型号','Canon EOS R50');
    await page.getByRole('spinbutton',{name:'当前焦段（mm，可选）',exact:true}).fill(String(item.request.focal_length_mm));
    await page.getByRole('spinbutton',{name:'镜头最大光圈（可选）',exact:true}).fill(String(item.request.max_aperture));
    await page.getByText('拍摄条件补充（选填）',{exact:true}).click();
    const choices = [
      ['当前快门类型',{efcs:'电子前帘',mechanical:'机械快门',electronic:'电子快门'}[item.request.shutter_type]],
      ['当前驱动模式',{single:'单张',continuous:'连拍'}[item.request.drive_mode]],
      ['当前对焦模式',{'AF-S':'单次自动对焦','AF-C':'连续自动对焦',MF:'手动对焦'}[item.request.focus_mode]],
    ];
    for(const [label,value] of choices) {if(value)await select(label,value);}
    save(item.id+'-before.json',{dom:await page.locator('body').ariaSnapshot(),input:item.request});
    await page.screenshot({path:path.join(ui,item.id+'-before.png'),fullPage:true});
    const start=Date.now();
    await page.getByRole('button',{name:'让小栗帮我配参数',exact:true}).click();
    console.log(JSON.stringify({case:item.id,event:'submitted'}));
    let lastLog=0;
    while(!fs.existsSync(path.join(live,item.id+'-summary.json')) && Date.now()-start<650000) {
      const elapsed=Date.now()-start;
      if(elapsed-lastLog>30000) {console.log(JSON.stringify({case:item.id,event:'waiting',seconds:Math.round(elapsed/1000)}));lastLog=elapsed;}
      const errors=await page.locator('[data-testid=stAlert]').allTextContents();
      if(errors.some(x=>/没有完成|格式不符合|配置尚未就绪/.test(x))) {
        save(item.id+'-page-failure.json',{errors,dom:await page.locator('body').ariaSnapshot()});
        throw new Error(item.id+' page rejected or failed; evidence preserved');
      }
      await page.waitForTimeout(1000);
    }
    if(!fs.existsSync(path.join(live,item.id+'-summary.json')))throw new Error(item.id+' page wait exceeded; no resubmission');
    await page.getByText('建议设置 · 待测光和试拍验证',{exact:true}).waitFor({timeout:30000});
    const text=await page.locator('body').innerText();
    const check={case:item.id,url:page.url(),title:await page.title(),elapsed_seconds:(Date.now()-start)/1000,
      dom:await page.locator('body').ariaSnapshot(),body_text:text,
      upload_verified:text.includes('现场图已上传'),result_verified:text.includes('建议设置'),
      environment_position_visible:text.includes('拍摄位置'),
      environment_uncertainty_visible:text.includes('拍摄位置未确认'),
      no_exception_overlay:await page.locator('[data-testid=stException]').count()===0,
      consoleEvents:[...consoleEvents]};
    save(item.id+'-result.json',check);
    await page.getByText('建议设置 · 待测光和试拍验证',{exact:true}).evaluate(el=>el.scrollIntoView({block:'center',behavior:'instant'}));
    await page.screenshot({path:path.join(ui,item.id+'-result.png'),fullPage:true});
    await page.getByText(/^拍摄位置：/).first().evaluate(el=>el.scrollIntoView({block:'center',behavior:'instant'}));
    await page.screenshot({path:path.join(ui,item.id+'-environment.png'),fullPage:false});
    await page.setViewportSize({width:390,height:844});
    await page.getByText('建议设置 · 待测光和试拍验证',{exact:true}).evaluate(el=>el.scrollIntoView({block:'center',behavior:'instant'}));
    await page.screenshot({path:path.join(ui,item.id+'-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1365,height:1000});
    console.log(JSON.stringify({case:item.id,event:'page_verified',seconds:check.elapsed_seconds}));
  }
  save('console.json',consoleEvents);
  await browser.close();
})().catch(async err=>{
  if(activePage){const id=Date.now();save('automation-failure-'+id+'.json',{error:err.message,dom:await activePage.locator('body').ariaSnapshot()});await activePage.screenshot({path:path.join(ui,'automation-failure-'+id+'.png'),fullPage:true});}
  if(activeBrowser)await activeBrowser.close();
  console.error(err.stack);process.exitCode=1;
});
