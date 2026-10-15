const fs=require('fs'),path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const out=path.resolve(__dirname,'../data/history/main-targeted-20261015');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const page=await browser.newPage({viewport:{width:1365,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8501/');
  await page.getByRole('button',{name:'让小栗帮我配参数',exact:true}).waitFor({timeout:30000});
  const body=await page.locator('body').innerText();
  const check={url:page.url(),title:await page.title(),entry:'ordinary app.py',api_calls:0,
   uploader_present:await page.locator('input[type=file]').count()===1,
   glm_dino_visible:body.includes('glm-4.6v')&&body.includes('Grounding DINO'),
   no_exception:await page.locator('[data-testid=stException]').count()===0,errors,
   dom:await page.locator('body').ariaSnapshot()};
  fs.writeFileSync(path.join(out,'final-page-check.json'),JSON.stringify(check,null,2));
  await page.screenshot({path:path.join(out,'final-page.png'),fullPage:true});
  if(!check.uploader_present||!check.glm_dino_visible||!check.no_exception||errors.length)throw new Error('Final page failed');
  console.log('Ordinary 8501 page verified; zero model submissions');
 }finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
