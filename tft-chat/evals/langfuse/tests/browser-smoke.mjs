/** Exercise native Langfuse edits, webhook runs, snapshots, and replay offline. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const {chromium} = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE || '/tmp/chattft-browser/node_modules/playwright/index.mjs').href);
const root = path.resolve('evals/langfuse');
const env = Object.fromEntries(fs.readFileSync(process.env.LANGFUSE_BROWSER_ENV_FILE || path.join(root,'.env'),'utf8').trim().split(/\r?\n/).map(line=>[line.slice(0,line.indexOf('=')),line.slice(line.indexOf('=')+1)]));
const snapshots = process.env.LANGFUSE_BROWSER_SNAPSHOTS || path.join(root,'snapshots');
const base = process.env.LANGFUSE_BROWSER_URL || 'http://localhost:15500';
const project = 'chattft-evals';
const publicHeaders = {Authorization:`Basic ${Buffer.from(`${env.LANGFUSE_PUBLIC_KEY}:${env.LANGFUSE_SECRET_KEY}`).toString('base64')}`};
const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
const page = await browser.newPage({viewport:{width:1440,height:1000}});
page.setDefaultTimeout(30000);
const stamp = `browser-${Date.now()}`;
const since = new Date(Date.now()-10000).toISOString();
let originalItem, originalPrompt, originalLatestPrompt, dataset, changedCase=false, changedPrompt=false;

/** Type through the editor's normal keyboard handling to preserve CodeMirror state. */
async function replaceEditor(editor,text) {
  await page.mouse.move(1400, 950);
  await editor.focus();
  await editor.press('ControlOrMeta+A');
  await page.keyboard.insertText(text);
}

/** Read persisted platform data, never printing authentication headers. */
async function api(route, params={}) {
  const response = await page.request.get(`${base}/api/public/${route}`, {headers:publicHeaders,params});
  assert.equal(response.status(),200,`Public API failed: ${route}`);
  return response.json();
}

/** Use native case editing controls so saved content is tested at the UI boundary. */
async function editCase(input) {
  await page.goto(`${base}/project/${project}/datasets/${dataset.id}/items`);
  await page.getByRole('button',{name:'Open menu',exact:true}).click();
  await page.getByRole('menuitem',{name:'Edit',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await page.waitForFunction(()=>document.querySelector('[role=dialog] .cm-content')?.textContent.includes('text'));
  await replaceEditor(dialog.locator('.cm-content').first(),JSON.stringify(input,null,2));
  await dialog.getByRole('button',{name:'Save changes',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  const saved=await api('dataset-items',{datasetName:'internal/fixtures/deterministic-trace'});
  assert.equal(saved.data[0].input.text,input.text);
}

/** Create a real version in the native prompt editor. */
async function editPrompt(text) {
  await page.goto(`${base}/project/${project}/prompts/${encodeURIComponent('chattft/assistants/chat')}`);
  await page.getByRole('button',{name:'New version',exact:true}).click();
  await page.locator('.cm-content').first().waitFor();
  await replaceEditor(page.locator('.cm-content').first(),text);
  await page.getByRole('button',{name:'Save new prompt version',exact:true}).click();
  await page.getByRole('button',{name:'New version',exact:true}).waitFor();
  const saved=await api(`v2/prompts/${encodeURIComponent('chattft/assistants/chat')}`,{label:'latest'});
  assert.equal(saved.prompt,text);
  return saved.version;
}

/** Submit through Langfuse's native button rather than calling our service directly. */
async function trigger(config) {
  await page.goto(`${base}/project/${project}/datasets/${dataset.id}/items`);
  await page.getByRole('link',{name:'Experiments',exact:true}).last().click();
  await page.getByRole('button',{name:'Run experiment',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Run',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await replaceEditor(dialog.locator('.cm-content'),JSON.stringify(config,null,2));
  const response=page.waitForResponse(r=>r.request().method()==='POST' && r.url().includes('RemoteExperiment'));
  await dialog.getByRole('button',{name:'Run',exact:true}).click();
  const result=await (await response).json();
  assert.ok(JSON.stringify(result).includes('"success":true'),`Native trigger failed: ${JSON.stringify(result)}`);
  console.log(`Native ${config.action} trigger accepted.`);
}

/** Wait for v4's asynchronous experiment and score ingestion with a bounded deadline. */
async function persistedRuns(expected) {
  const deadline=Date.now()+90000;
  while(Date.now()<deadline) {
    const rows=(await api('experiments',{fromStartTime:since,datasetId:dataset.id,limit:'100'})).data.filter(row=>row.name.includes(stamp));
    if(rows.length>=expected) {
      const items=[];
      for(const row of rows) {
        const result=await api('experiment-items',{fromStartTime:since,experimentId:row.id,fields:'core,io,scores',limit:'100'});
        items.push(...result.data);
      }
      if(items.length===expected && items.every(item=>['attempt_pass','execution_success','contract_pass',...originalItem.metadata.deterministic_checks.map(a=>a.name)].every(name=>item.scores?.some(score=>score.name===name && (score.value===1 || score.value===true))))) return {rows,items};
    }
    await page.waitForTimeout(1000);
  }
  throw new Error('Native experiment items/scores were not persisted before the deadline');
}

try {
  await page.goto(base);
  await page.getByLabel('Email').fill(env.LANGFUSE_INIT_USER_EMAIL);
  await page.locator('input[name="password"]').fill(env.LANGFUSE_INIT_USER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.waitForURL(url=>!url.pathname.includes('auth'));
  dataset=await api(`v2/datasets/${encodeURIComponent('internal/fixtures/deterministic-trace')}`);
  originalItem=structuredClone((await api('dataset-items',{datasetName:dataset.name})).data[0]);
  originalPrompt=await api(`v2/prompts/${encodeURIComponent('chattft/assistants/chat')}`,{label:'baseline'});
  originalLatestPrompt=await api(`v2/prompts/${encodeURIComponent('chattft/assistants/chat')}`,{label:'latest'});
  const input={...originalItem.input,text:`${originalItem.input.text} [${stamp}]`};
  changedCase=true;
  await editCase(input);
  changedPrompt=true;
  const promptVersion=await editPrompt(`${originalPrompt.prompt}\n\nBrowser acceptance version ${stamp}.`);
  console.log('Native dataset and prompt edits saved.');
  await trigger({action:'run',variants:[{name:`${stamp}-baseline`},{name:`${stamp}-candidate`}],repetitions:1});
  const catalog=JSON.parse(fs.readFileSync(path.join(snapshots,'catalog.json'),'utf8'));
  const snapshot=catalog.suites.find(entry=>entry.name==='dummy_assistant').snapshot;
  const frozen=JSON.parse(fs.readFileSync(path.join(snapshots,`${snapshot}.json`),'utf8'));
  assert.equal(frozen.items[0].input.text,input.text);
  assert.equal(frozen.prompts.chat.version,originalPrompt.version);
  assert.ok(promptVersion > originalPrompt.version, "Candidate versions leave the baseline label stable");
  await persistedRuns(2);
  console.log('Two UI variants persisted all fixture scores and frozen edits.');
  await editCase({...input,text:`${input.text} changed after snapshot`});
  await trigger({action:'replay',snapshot});
  const replay=await persistedRuns(4);
  assert.ok(replay.items.every(item=>JSON.stringify(item.input).includes(input.text) && !JSON.stringify(item.input).includes('changed after snapshot')));
  console.log('UI replay preserved original inputs after subsequent edits.');
  await page.reload();
  const comparisonRows=page.locator('tbody tr').filter({hasText:stamp});
  await comparisonRows.first().waitFor();
  await comparisonRows.nth(0).getByRole('checkbox').click();
  await comparisonRows.nth(1).getByRole('checkbox').click();
  await page.getByRole('button',{name:'Compare',exact:true}).click();
  await page.waitForURL(/experiments\/results/);
  await page.locator('tbody tr').first().waitFor();
  console.log('Native side-by-side comparison loaded.');
  await page.screenshot({path:process.env.LANGFUSE_BROWSER_SCREENSHOT || '/tmp/chattft-langfuse-browser.png',fullPage:true});
} catch(error) {
  console.error('Browser acceptance failed:',error.message);
  await page.screenshot({path:'/tmp/chattft-langfuse-browser-failure.png',fullPage:true});
  throw error;
} finally {
  // Restore authored content as new versions; keep experiment history and immutable run bundles.
  if(changedCase) {
    const restored=await page.request.post(`${base}/api/public/dataset-items`,{headers:publicHeaders,data:{id:originalItem.id,datasetName:'internal/fixtures/deterministic-trace',input:originalItem.input,expectedOutput:originalItem.expectedOutput,metadata:originalItem.metadata}});
    assert.ok(restored.ok(),'Restore fixture content');
  }
  if(changedPrompt) {
    const restored=await page.request.post(`${base}/api/public/v2/prompts`,{headers:publicHeaders,data:{name:'chattft/assistants/chat',type:'text',prompt:originalLatestPrompt.prompt,config:originalLatestPrompt.config,tags:originalLatestPrompt.tags}});
    assert.ok(restored.ok(),'Restore grading prompt');
  }
  if(dataset && changedCase) await trigger({action:'export'});
  await browser.close();
}
console.log('Langfuse native browser acceptance passed.');
