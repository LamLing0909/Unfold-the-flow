// Optional integration test; see test_browser.cjs.
const {chromium}=require('playwright');
const path=require('path');
const {pathToFileURL}=require('url');
(async()=>{
  const launch={headless:true,args:['--no-sandbox']};
  if(process.env.CHROMIUM_PATH) launch.executablePath=process.env.CHROMIUM_PATH;
  const browser=await chromium.launch(launch), page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true}), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(path.resolve(__dirname,'../index.html')).href);
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Loaded'),null,{timeout:120000});
  let node={id:'leaf'};
  for(let i=0;i<60;i++)node={id:`n${i}`,children:[node]};
  await page.locator('#json-input').fill(JSON.stringify({nodes:[node]}));
  await page.locator('#render-button').click();
  const deep=await page.locator('#status').textContent();
  if(!deep.includes('Loaded 61 nodes')) errors.push('deep tree: '+deep);
  const invalid={nodes:[{id:'a',unfolded:1}]};
  await page.locator('#json-input').fill(JSON.stringify(invalid));
  await page.locator('#render-button').click();
  const status=await page.locator('#status').textContent();
  if(!status.includes('unfolded')) errors.push('invalid input: '+status);
  if(await page.locator('.flow-node').count()!==1) errors.push('prior graph not retained after invalid JSON');
  await browser.close();
  if(errors.length){console.error(errors.join('\n'));process.exit(1)}
  console.log('file:// Pydantic, 60-level input, strict validation and error recovery passed.');
})().catch(e=>{console.error(e);process.exit(1)});
