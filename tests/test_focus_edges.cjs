// Optional browser integration test; see test_browser.cjs.
const {chromium}=require('playwright');
const path=require('path');
const {pathToFileURL}=require('url');
(async()=>{
  const launch={headless:true,args:['--no-sandbox']};
  if(process.env.CHROMIUM_PATH)launch.executablePath=process.env.CHROMIUM_PATH;
  const browser=await chromium.launch(launch), failures=[];
  for(const mobile of [false,true]){
    const p=await browser.newPage({viewport:mobile?{width:390,height:844}:{width:1400,height:1000},isMobile:mobile,hasTouch:mobile});
    p.on('pageerror',e=>failures.push(e.message));
    await p.goto(pathToFileURL(path.resolve(__dirname,'../index.html')).href);
    await p.waitForFunction(()=>document.querySelector('#status').textContent.includes('Loaded'),null,{timeout:60000});
    for(const direction of ['TB','BT','LR','RL']){
      const data={direction,nodes:[{id:'parent',content:'Group',unfolded:true,children:[{id:'a',content:'A',to:{b:'Forward'}},{id:'b',content:'B',to:{a:'Loop'}}]},{id:'external',content:'External'}]};
      await p.locator('#json-input').fill(JSON.stringify(data)); await p.locator('#render-button').click();
      await p.locator('[data-flow-focus="parent"]').click(); await p.waitForTimeout(150);
      const result=await p.evaluate(()=>{
        const view=document.querySelector('#diagram').getBoundingClientRect(),card=document.querySelector('[data-node-id="parent"]').getBoundingClientRect();
        const label=[...document.querySelectorAll('.flow-label')].find(e=>e.textContent==='Loop');
        const edge=label.previousElementSibling, box=edge.getBoundingClientRect(), lb=label.getBoundingClientRect();
        const inside=r=>r.left>=view.left-1&&r.top>=view.top-1&&r.right<=view.right+1&&r.bottom<=view.bottom+1;
        return {dx:Math.abs((view.left+view.right-card.left-card.right)/2),dy:Math.abs((view.top+view.bottom-card.top-card.bottom)/2),edge:inside(box),label:inside(lb),zoom:document.querySelector('#zoom-reset').textContent};
      });
      if(result.dx>2||result.dy>2||!result.edge||!result.label) failures.push(`${mobile?'mobile':'desktop'} ${direction}: ${JSON.stringify(result)}`);
    }
    await p.close();
  }
  await browser.close();
  if(failures.length){console.error(failures.join('\n'));process.exit(1)}
  console.log('Focused parent remains centered and includes its internal loop and label.');
})().catch(e=>{console.error(e);process.exit(1)});
