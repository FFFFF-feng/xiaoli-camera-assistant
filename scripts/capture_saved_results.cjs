const fs=require('fs'),path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'..'),out=path.join(root,'data/history/main-acceptance-20261014/ui-replay');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const b=await chromium.launch({headless:true,channel:'chrome'});
 try{
 const page=await b.newPage({viewport:{width:1365,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8502/');
 for(const caseId of ['P02','P03','B08','D10','D17','D01']){
  const select=page.getByRole('combobox',{name:'保存的真实结果回看（0 新 API）',exact:true});
  await select.waitFor({timeout:30000});
  await select.evaluate(e=>e.scrollIntoView({behavior:'instant',block:'center'}));
  await select.click();await page.getByRole('option',{name:caseId,exact:true}).waitFor({state:'attached'});
  const options=await page.getByRole('option').allTextContents();await page.keyboard.press('Home');
  for(let i=0;i<options.indexOf(caseId);i++)await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');await page.keyboard.press('Tab');
  await page.waitForTimeout(700);
  const body=await page.locator('body').innerText();
  if(await page.locator('[data-testid=stException]').count())throw new Error(caseId+' replay error');
  await page.getByText('建议设置 · 待测光和试拍验证',{exact:true}).evaluate(e=>e.scrollIntoView({behavior:'instant',block:'center'}));
  await page.screenshot({path:path.join(out,caseId+'-parameters.png')});
  await page.getByText(/^拍摄位置：/).first().evaluate(e=>e.scrollIntoView({behavior:'instant',block:'center'}));
  await page.screenshot({path:path.join(out,caseId+'-environment.png')});
  await page.setViewportSize({width:390,height:844});
  await page.getByText('建议设置 · 待测光和试拍验证',{exact:true}).evaluate(e=>e.scrollIntoView({behavior:'instant',block:'center'}));
  await page.screenshot({path:path.join(out,caseId+'-mobile.png')});
  await page.setViewportSize({width:1365,height:1000});
  fs.writeFileSync(path.join(out,caseId+'-review.json'),JSON.stringify({case:caseId,url:page.url(),real_api_calls:0,
   evidence_type:'saved_real_result_page_replay',viewports:[[1365,1000],[390,844]],body_text:body,errors},null,2));
  console.log(caseId+' zero-API result render checked');
 }
 }finally{await b.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
