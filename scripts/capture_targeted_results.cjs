const fs=require('fs'),path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'..'),out=path.join(root,'data/history/main-targeted-20261015/ui-replay-verified');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1365,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8502/');
  const select=page.getByRole('combobox',{name:'保存结果回看（0 新 API）',exact:true});
  await select.waitFor({timeout:30000});
  await select.click();
  const labels=await page.getByRole('option').allTextContents();
  await page.keyboard.press('Escape');
  for(let i=0;i<labels.length;i++){
   await select.evaluate(e=>e.scrollIntoView({behavior:'instant',block:'center'}));
   await select.click();await page.keyboard.press('Home');
   for(let n=0;n<i;n++)await page.keyboard.press('ArrowDown');
   await page.keyboard.press('Enter');await page.keyboard.press('Tab');
   await page.getByText('本次回看记录：'+labels[i]+' · 0 API',{exact:true}).waitFor({timeout:30000});
   if(await page.locator('[data-testid=stException]').count())throw new Error(labels[i]+' rendering exception');
   const text=await page.locator('body').innerText();
   const check={label:labels[i],evidence_type:'saved-result UI replay',api_calls:0,
    knowledge_scope_visible:text.includes('知识引用与支持范围'),
    preserved_composition:text.includes('方案 1'),
    missing_shutter_visible:text.includes('缺失项：快门'),
    source_original_label:text.includes('模型动作原文'),
    program_check_label:text.includes('程序生成的现场比较'),
    quoted_principle:text.includes('知识原则：'),isolation_label:text.includes('未经独立人审'),
    body_text:text,dom:await page.locator('body').ariaSnapshot(),errors};
   fs.writeFileSync(path.join(out,'case-'+i+'.json'),JSON.stringify(check,null,2));
   const rejected=page.getByText('已隔离的候选引用',{exact:true});
   if(await rejected.count())await rejected.click();
   const retrieved=page.getByText('本次检索到的摄影知识',{exact:true});
   if(await retrieved.count())await retrieved.click();
   await page.getByText('知识引用与支持范围',{exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,'case-'+i+'-sources.png')});
   await page.getByText(/^方案 1 · /).first().scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,'case-'+i+'-composition.png')});
   await page.setViewportSize({width:390,height:844});
   await page.screenshot({path:path.join(out,'case-'+i+'-mobile.png')});
   check.mobile_horizontal_overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
   fs.writeFileSync(path.join(out,'case-'+i+'.json'),JSON.stringify(check,null,2));
   await page.setViewportSize({width:1365,height:1000});
   console.log(labels[i]+' zero-API render checked');
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
