/** Real production-browser journeys over isolated backend and external-model boundaries. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { createWriteStream } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../../', import.meta.url));
const output = process.env.VALIDATION_ARTIFACTS ?? path.join(root,'.runtime/validation/journeys',`${Date.now()}-${process.pid}`);
await mkdir(output,{recursive:true});
const owned = new Set();

/** Poll an observable outcome with a bounded deadline. */
async function until(check, message, timeout=30000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) { if(await check()) return; await new Promise(resolve=>setTimeout(resolve,100)); }
  throw new Error(message);
}

/** Start an independent application interpreter with a disposable fixture server. */
async function start(app,port) {
  if(!port) { const reservation=createServer(); reservation.listen(0,'127.0.0.1'); await once(reservation,'listening'); port=reservation.address().port; await new Promise(resolve=>reservation.close(resolve)); }
  const url=`http://127.0.0.1:${port}`;
  const interpreter=process.env[app==='chat'?'CHAT_TEST_PYTHON':'VOD_TEST_PYTHON'] ?? path.join(root,app==='chat'?'tft-chat':'vod-review','.venv/bin/python');
  const log=createWriteStream(path.join(output,`${app}-journey-server.log`),{flags:'a'});
  const child=spawn(interpreter,['-m','uvicorn','--app-dir','tests/browser',`${app}_fixture:app`,'--host','127.0.0.1','--port',String(port)],{
    cwd:root,env:{...process.env,JOURNEY_BASE_URL:url,VOD_DATA_DIR:path.join(output,'vod'),TFT_MEDIA_DIR:path.join(output,'media'),
      VOD_GDRIVE_TOKEN_FILE:path.join(output,'vod/gdrive/token.json'),VOD_GDRIVE_CLIENT_FILE:'',
      VOD_TRACE_JSONL:path.join(output,'vod-trace.jsonl'),VOD_OCR_CACHE_DIR:path.join(output,'vod/ocr_cache'),
      VOD_FRAMES_DIR:path.join(output,'vod/frames'),VOD_BOXES_DIR:path.join(output,'vod/boxes'),VOD_SAVE_FRAMES:'0',VOD_SAVE_BOXES:'0'},stdio:['ignore','pipe','pipe']});
  child.stdout.pipe(log);child.stderr.pipe(log); owned.add(child);
  child.once('close',()=>{log.end();owned.delete(child);});
  await until(async()=>{if(child.exitCode!==null)throw new Error(`${app} fixture exited: inspect ${output}`);try{return (await fetch(url+(app==='chat'?'/api/config':'/api/health'))).ok;}catch{return false;}},`${app} fixture startup timed out`);
  return {child,url,port};
}

/** Stop only the fixture interpreter owned by this browser run. */
async function stop(server) {
  if(!server || server.child.exitCode!==null) return;
  const exited=once(server.child,'close');server.child.kill('SIGTERM');
  const timer=setTimeout(()=>server.child.kill('SIGKILL'),5000);
  try{await exited;}finally{clearTimeout(timer);}
}

const browser=await chromium.launch({headless:true});
let chat, vod;
try {
  chat=await start('chat');vod=await start('vod');
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]) {
    const context=await browser.newContext({viewport});
    await context.tracing.start({screenshots:true,snapshots:true});
    const page=await context.newPage();page.setDefaultTimeout(15000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    try {
      await page.goto(chat.url);
      const input=page.getByPlaceholder(/Ask a TFT question/);
      await input.fill('Rank units in the synthetic fixture');await input.press('Enter');
      await page.getByText('62.5%',{exact:true}).waitFor();
      await page.getByText(/Synthetic evidence supports this fixture answer/).waitFor();
      const metrics=await (await page.request.get(chat.url+'/__test__/metrics')).json();
      assert.ok(metrics.rank_calls>0 && metrics.presentations>0);
      await page.getByText('Explore table: sort, search and group').click();
      await page.getByLabel('Search loaded rows').fill('Fixture Carry');
      const navigate=async name=>{const button=page.getByRole('button',{name,exact:true});
        if(!await button.isVisible())await page.getByRole('button',{name:'Toggle Sidebar'}).first().click();
        await page.getByRole('button',{name,exact:true}).click();
        if(viewport.width<768)await page.getByRole('dialog').waitFor({state:'hidden'});};
      await navigate('Developer');await navigate('Chat');
      assert.equal(await page.getByLabel('Search loaded rows').inputValue(),'Fixture Carry');
      await page.getByRole('button',{name:'New conversation'}).click();
      assert.equal(await page.getByLabel('Search loaded rows').count(),0);
      const cancellationMetrics=await (await page.request.get(chat.url+'/__test__/metrics')).json();
      const beforeCancel=cancellationMetrics.model_requests;
      await input.fill('cancel fixture');await input.press('Enter');
      await until(async()=> (await (await page.request.get(chat.url+'/__test__/metrics')).json()).model_requests>beforeCancel,'Model did not start cancellable request');
      // Closing/reloading the view is the existing application's cancellation boundary.
      await page.reload();
      await until(async()=> (await (await page.request.get(chat.url+'/__test__/metrics')).json()).cancelled>cancellationMetrics.cancelled,'Chat cancellation did not finalize');

      const workspace={schema_version:'flowchart.v2',name:`Journey ${viewport.width}`,gameplan:{flowchart:{elements:[{id:'a',kind:'action',position:{x:100,y:100},title:'Fixture action'}],connections:[]}}};
      const created=await page.request.post(chat.url+'/api/flowchart/workspaces/import',{data:{workspace}});assert.equal(created.status(),201);
      const record=await created.json(),endpoint=chat.url+`/api/flowchart/workspaces/${record.id}`;
      await page.goto(chat.url+'/flowchart');await page.getByText('Fixture action',{exact:true}).first().waitFor();
      const current=await (await page.request.get(endpoint)).json();
      const edited={...current.workspace,name:`Saved ${viewport.width}`};
      const saved=await page.request.put(endpoint,{data:{revision:current.revision,workspace:edited}});assert.equal(saved.status(),200);
      const conflict=await page.request.put(endpoint,{data:{revision:current.revision,workspace:current.workspace}});assert.equal(conflict.status(),409);
      await page.reload();await page.getByText('Fixture action',{exact:true}).first().waitFor();
      const invalid=await page.request.put(endpoint,{data:{revision:(await saved.json()).revision,workspace:{...edited,schema_version:'unsupported'}}});
      assert.equal(invalid.status(),422);
      assert.equal((await (await page.request.get(endpoint)).json()).workspace.name,edited.name);
      const recovered=await page.request.put(endpoint,{data:{revision:current.revision+1,workspace:edited}});assert.equal(recovered.status(),200);
      const exported=await page.request.post(endpoint+'/export');assert.equal(exported.status(),200);
      assert.equal((await exported.json()).workspace.name,edited.name);
      const library=await page.request.post(chat.url+'/api/flowchart/groups',{data:{name:`Library ${viewport.width}`,fragment:workspace.gameplan.flowchart}});
      assert.equal(library.status(),201);
      assert.ok((await (await page.request.get(chat.url+'/api/flowchart/groups')).json()).groups.some(row=>row.name===`Library ${viewport.width}`));
      // API conflict/recovery changed the revision; reopen before testing a
      // separate transport outage so that this client starts from current state.
      await page.reload();
      await until(async()=>await page.getByLabel('Workspace title').inputValue()===edited.name,'Workspace did not reopen at the current revision');
      let injectFailure=true;
      await page.route(endpoint+'**',async route=>{
        if(route.request().method()==='PATCH' && injectFailure){injectFailure=false;await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Injected save outage'})});}
        else await route.continue();
      });
      const title=page.getByLabel('Workspace title');
      await title.fill(`Unsaved ${viewport.width}`);await title.press('Enter');
      await page.getByRole('alert').filter({hasText:'Injected save outage'}).waitFor();
      assert.equal((await (await page.request.get(endpoint)).json()).workspace.name,edited.name);
      await title.fill(`Recovered ${viewport.width}`);await title.press('Enter');
      await until(async()=> (await (await page.request.get(endpoint)).json()).workspace.name===`Recovered ${viewport.width}`,'UI save did not recover');
      await page.unroute(endpoint+'**');await page.reload();
      await until(async()=>await page.getByLabel('Workspace title').inputValue()===`Recovered ${viewport.width}`,'Reload lost the recovered save');

      await page.goto(vod.url);
      const media=await page.request.get(vod.url+'/__test__/media');
      await page.getByLabel('Video file').first().setInputFiles({name:`fixture-${viewport.width}.mp4`,mimeType:'video/mp4',buffer:await media.body()});
      await page.getByRole('button',{name:'Draw box',exact:true}).waitFor();
      const video=page.locator('video');await until(()=>video.evaluate(node=>node.readyState>=2 && node.videoWidth===128 && node.videoHeight===96),'Synthetic video frame was not decoded');
      await page.getByRole('button',{name:'Draw box',exact:true}).click();
      const canvas=await page.getByLabel('Draw a bounding box on the video').boundingBox();assert.ok(canvas);
      await page.mouse.move(canvas.x+canvas.width*.1,canvas.y+canvas.height*.1);await page.mouse.down();
      await page.mouse.move(canvas.x+canvas.width*.8,canvas.y+canvas.height*.8,{steps:5});await page.mouse.up();
      await page.getByRole('button',{name:'Save box',exact:true}).click();
      await page.getByLabel('Analysis interval in seconds').fill('1');
      await page.getByRole('button',{name:'Process video',exact:true}).click();
      await page.getByRole('button',{name:/21.*95% confidence/}).waitFor({timeout:30000});
      await page.getByLabel('Seek offset in seconds').fill('2');
      await page.getByRole('button',{name:/21.*95% confidence/}).click();
      await until(()=>video.evaluate(node=>node.currentTime>=1.8),'Round seek offset was not applied');
      const records=await (await page.request.get(vod.url+'/api/videos')).json();
      const selected=records.find(row=>row.original_name===`fixture-${viewport.width}.mp4`);assert.ok(selected);
      const transcription=await page.request.post(vod.url+`/api/videos/${selected.id}/transcription`);assert.equal(transcription.status(),202);
      await until(async()=>{const response=await page.request.get(vod.url+`/api/videos/${selected.id}/transcription`);return response.ok()&&(await response.json()).status==='completed';},'Transcript completion timed out');
      await until(async()=>{const resources=await (await page.request.get(chat.url+'/api/shared-media?kind=text')).json();return resources.some(row=>row.metadata?.type==='transcript');},'Chat did not discover VOD transcript');
      const resources=await (await page.request.get(chat.url+'/api/shared-media?kind=text')).json();
      const resource=resources.find(row=>row.metadata?.type==='transcript');
      assert.equal(await (await page.request.get(chat.url+resource.content_url)).text(),'Fixture transcript — Café ☕');
      const port=vod.port;await stop(vod);vod=await start('vod',port);
      await page.reload();
      // A fresh page deliberately starts without a selected review. Reopen the
      // persisted library entry through the same control a user would use.
      await page.getByLabel('Recent videos').selectOption(selected.id);
      const restored=await (await page.request.get(vod.url+`/api/videos/${selected.id}`)).json();
      assert.equal(restored.current_job.status,'completed');
      const restoredTranscript=await (await page.request.get(vod.url+`/api/videos/${selected.id}/transcription`)).json();
      assert.equal(restoredTranscript.transcript,'Fixture transcript — Café ☕');
      await page.getByRole('button',{name:/21.*95% confidence/}).waitFor();
      await page.getByRole('button',{name:'View transcript',exact:true}).click();
      assert.equal(await page.getByLabel('Transcript text').inputValue(),'Fixture transcript — Café ☕');
      await page.keyboard.press('Escape');
      // Escape must close the source dialog and restore a keyboard focus target.
      const settings=page.getByRole('button',{name:'Replay source settings'});await settings.click();await page.keyboard.press('Escape');
      assert.equal(await page.getByRole('dialog').count(),0);
      assert.equal(await settings.evaluate(node=>node===document.activeElement),true);
      assert.deepEqual(errors,[]);
      console.log(JSON.stringify({passed:true,viewport,journeys:['chat-sdk-sql-evidence-cancel','flowchart-persistence-conflict-export','vod-process-seek-transcript-restart']}));
    } finally {
      await page.screenshot({path:path.join(output,`journey-${viewport.width}.png`),fullPage:true}).catch(()=>{});
      await context.tracing.stop({path:path.join(output,`journey-${viewport.width}.zip`)});
      await context.close();
    }
  }
} finally {
  await stop(vod);await stop(chat);await browser.close();
  for(const child of owned)child.kill('SIGKILL');
}
