const fs=require('fs'),path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
 const b=await chromium.launch({headless:true,channel:'chrome'});
 try{
 const p=await b.newPage({viewport:{width:1365,height:1000}});
 await p.goto('http://127.0.0.1:8501/');
 await p.getByText('相机与镜头（选填）',{exact:true}).click();
 const c=p.getByRole('combobox',{name:'相机型号',exact:true});
 await c.evaluate(e=>e.scrollIntoView({block:'center'}));
 console.log(await c.evaluate(e=>e.outerHTML));
 await c.click();
 console.log('clicked',await c.getAttribute('aria-expanded'),await p.getByRole('option').allTextContents());
 await p.keyboard.press('Home');
 for(let i=0;i<4;i++)await p.keyboard.press('ArrowDown');
 await p.keyboard.press('Enter');
 console.log('key',await c.inputValue(),await c.getAttribute('aria-expanded'),await p.getByRole('option').allTextContents());
 console.log((await p.locator('body').ariaSnapshot()).slice(-5000));
 await p.screenshot({path:path.join(root,'data/history/main-acceptance-20261014/ui/control-probe.png')});
 }finally{await b.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
