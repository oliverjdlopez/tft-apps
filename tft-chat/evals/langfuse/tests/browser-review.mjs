import {AssistantName} from '../../../app/frontend/src/assistant-names.js';
/** Verify native case authoring, evaluator editing, human review, and regression capture. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';

assert.equal(process.env.LANGFUSE_TEST_DEPLOYMENT, '1', 'Use an isolated mock deployment');
const {chromium} = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE || '/tmp/chattft-browser/node_modules/playwright/index.mjs').href);
const env = Object.fromEntries(fs.readFileSync(process.env.LANGFUSE_BROWSER_ENV_FILE || 'evals/langfuse/.env','utf8').trim().split(/\r?\n/).map(line=>[line.slice(0,line.indexOf('=')),line.slice(line.indexOf('=')+1)]));
const base = process.env.LANGFUSE_BROWSER_URL || 'http://localhost:15510';
const headers = {Authorization:`Basic ${Buffer.from(`${env.LANGFUSE_PUBLIC_KEY}:${env.LANGFUSE_SECRET_KEY}`).toString('base64')}`};
const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
const page = await browser.newPage({viewport:{width:1440,height:1000}});
page.setDefaultTimeout(30000);
const stamp = `native-review-${Date.now()}`;
const since = new Date(Date.now()-10000).toISOString();

/** Read persisted native resources without exposing credentials. */
async function api(route, params={}) {
  const response=await page.request.get(`${base}/api/public/${route}`,{headers,params});
  assert.ok(response.ok(),route);
  return response.json();
}

/** Update CodeMirror through normal keyboard events. */
async function edit(editor, text) {
  await page.mouse.move(1400,950);
  await editor.focus();
  await editor.press('ControlOrMeta+A');
  await page.keyboard.insertText(text);
}

/** Submit the real application via the native Custom Experiment integration. */
async function trigger(dataset, config) {
  await page.goto(`${base}/project/tft-apps-evals/datasets/${dataset.id}/items`);
  await page.getByRole('link',{name:'Experiments',exact:true}).last().click();
  await page.getByRole('button',{name:'Run experiment',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Run',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await edit(dialog.locator('.cm-content'),JSON.stringify(config,null,2));
  const pending=page.waitForResponse(r=>r.request().method()==='POST' && r.url().includes('RemoteExperiment'));
  await dialog.getByRole('button',{name:'Run',exact:true}).click();
  assert.ok(JSON.stringify(await (await pending).json()).includes('"success":true'));
}

try {
  await page.goto(base);
  await page.getByLabel('Email').fill(env.LANGFUSE_INIT_USER_EMAIL);
  await page.locator('input[name=password]').fill(env.LANGFUSE_INIT_USER_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.waitForURL(url=>!url.pathname.includes('auth'));
  const dataset=await api(`v2/datasets/${encodeURIComponent('end-to-end')}`);
  await page.goto(`${base}/project/tft-apps-evals/datasets/${dataset.id}/items`);
  await page.getByRole('button',{name:'New item',exact:true}).click();
  let dialog=page.getByRole('dialog');
  await edit(dialog.locator('.cm-content').nth(0),JSON.stringify(`Hello! ${stamp}`));
  await edit(dialog.locator('.cm-content').nth(1),JSON.stringify({requirements:['Respond with a friendly greeting.']}));
  await edit(dialog.locator('.cm-content').nth(2),'{}');
  await dialog.getByRole('button',{name:'Add to dataset',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  const authored=(await api('dataset-items',{datasetName:dataset.name,limit:100})).data.find(item=>JSON.stringify(item.input).includes(stamp));
  assert.ok(authored?.id);
  assert.ok(!authored.metadata?.case_id,'Native case creation needs no internal identity');
  console.log('Native case created with a string input and readable requirements.');

  const evaluator=(await api('v2/evaluators')).data.find(row=>row.name==='answer_quality');
  const evaluatorText=Array.isArray(evaluator.prompt) ? evaluator.prompt.map(message=>message.content).join('\n') : evaluator.prompt;
  await page.goto(`${base}/project/tft-apps-evals/evals`);
  await page.getByText('answer_quality',{exact:true}).click();
  await page.waitForFunction(prompt=>document.querySelector('.cm-content')?.innerText===prompt,evaluatorText);
  await edit(page.locator('.cm-content').first(),`${evaluatorText}\nBrowser acceptance ${stamp}.`);
  const saving=page.waitForResponse(r=>r.request().method()==='POST' && r.url().includes('evals'));
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await saving;
  await page.waitForTimeout(500);
  const edited=await api(`v2/evaluators/${evaluator.id}`);
  assert.notEqual(edited.versionId,evaluator.versionId);
  assert.ok(JSON.stringify(edited.prompt).includes(stamp));
  console.log('Native evaluator edit created a new frozen version.');
  const baselinePrompt=await api(`v2/prompts/${encodeURIComponent(`chattft/assistants/${AssistantName.CHAT}`)}`,{label:'baseline'});
  await page.goto(`${base}/project/tft-apps-evals/prompts/${encodeURIComponent(baselinePrompt.name)}`);
  await page.getByRole('button',{name:'New version',exact:true}).click();
  await edit(page.locator('.cm-content').first(),`${baselinePrompt.prompt}\nCandidate acceptance ${stamp}.`);
  await page.getByRole('button',{name:'Save new prompt version',exact:true}).click();
  await page.getByRole('button',{name:'New version',exact:true}).waitFor();
  const candidatePrompt=await api(`v2/prompts/${encodeURIComponent(baselinePrompt.name)}`,{label:'latest'});
  assert.ok(candidatePrompt.version>baselinePrompt.version);

  // The prompt editor must run drafts against the same backend as datasets.
  // This isolated deployment uses a mock upstream LLM, never a paid provider.
  await page.getByRole('button',{name:'Playground',exact:true}).click();
  await page.getByText('Fresh playground',{exact:true}).click();
  await page.getByRole('combobox').first().click();
  await page.getByRole('option',{name:`ChatTFT backend: chattft/${AssistantName.CHAT}`,exact:true}).click();
  await edit(page.locator('.cm-content').first(),`Playground unsaved draft ${stamp}`);
  await page.getByRole('button',{name:'Message',exact:true}).click();
  await edit(page.locator('.cm-content').nth(1),'Hello from the backend Playground smoke test.');
  await page.getByRole('button',{name:'Submit',exact:true}).click();
  await page.getByText(/Inspect ChatTFT run: tools, handoffs, and prompts/).waitFor({timeout:60000});
  assert.ok((await page.locator('body').innerText()).includes('Mock application reply.'));
  // ClickHouse ingestion follows SDK flush; poll only until this run is visible.
  let draftRun;
  const draftDeadline=Date.now()+30000;
  while(Date.now()<draftDeadline && !draftRun) {
    const roots=(await api('v2/observations',{name:'chattft-playground',fromStartTime:since,
      fields:'core,basic,io,metadata',limit:100})).data;
    draftRun=roots.find(row=>JSON.stringify(row.input).includes(`Playground unsaved draft ${stamp}`));
    if(!draftRun) await page.waitForTimeout(1000);
  }
  assert.ok(draftRun?.traceId,'Draft run must retain its inspection trace');
  assert.equal(draftRun.metadata.assistant,AssistantName.CHAT);
  assert.equal(draftRun.metadata.prompt_overrides[AssistantName.CHAT].text,`Playground unsaved draft ${stamp}`);
  console.log('Native Playground executes an unsaved draft through the backend with an inspection trace.');

  const report=JSON.parse(fs.readFileSync('/tmp/chattft-native-judge-report.json'));
  const failed=report.experiments.find(row=>!row.expected_pass).items[0];
  const queue=(await api('annotation-queues')).data.find(row=>row.name==='ChatTFT review');
  const added=await page.request.post(`${base}/api/public/annotation-queues/${queue.id}/items`,{headers,data:{objectId:failed.observation_id,objectType:'OBSERVATION'}});
  assert.ok(added.ok());
  await page.goto(`${base}/project/tft-apps-evals/annotation-queues/${queue.id}`);
  await page.getByText('Process queue',{exact:true}).click();
  await page.getByText('TEST_FAILURE: contradicted requirements',{exact:true}).first().waitFor();
  await page.getByRole('combobox').click();
  await page.getByRole('option',{name:'application_failure',exact:true}).click();
  await page.getByRole('radio',{name:'False',exact:true}).click();
  await page.getByRole('button',{name:/Mark Completed/}).click();
  console.log('Failing native output received human acceptance and failure-category annotations.');
  await page.goto(`${base}/project/tft-apps-evals/traces/${failed.trace_id}?observation=${failed.observation_id}`);
  await page.getByRole('tab',{name:'Scores',exact:true}).click();
  await page.getByLabel('View comment for answer_quality: 0.20',{exact:true}).hover();
  await page.getByText('Mock evaluator: requirement violated.',{exact:false}).first().waitFor();

  const source=JSON.parse(fs.readFileSync('/tmp/chattft-development-trace.json'));
  await page.goto(`${base}/project/tft-apps-evals/traces/${source.traceId}?observation=${source.id}`);
  await page.getByRole('button',{name:'Add to datasets',exact:true}).click();
  dialog=page.getByRole('dialog');
  await dialog.getByText('Select datasets',{exact:true}).click();
  await page.getByText(dataset.name,{exact:true}).last().click();
  await page.keyboard.press('Escape');
  await edit(dialog.locator('.cm-content').nth(1),JSON.stringify({requirements:['Respond with a friendly greeting.']}));
  await dialog.getByRole('button',{name:'Add to dataset',exact:true}).click();
  await dialog.waitFor({state:'hidden'});
  const captured=(await api('dataset-items',{datasetName:dataset.name,limit:100})).data.find(item=>item.sourceObservationId===source.id);
  assert.ok(captured?.id);
  assert.equal(captured.sourceTraceId,source.traceId);
  assert.deepEqual(captured.input,source.input);
  console.log('Development observation captured natively with source links and unchanged conversation.');

  await trigger(dataset,{cases:[`${AssistantName.CHAT}/${authored.id}`,`${AssistantName.CHAT}/${captured.id}`],variants:[
    {name:`${stamp}-baseline`},{name:`${stamp}-candidate`,prompts:{[AssistantName.CHAT]:{name:candidatePrompt.name,version:candidatePrompt.version}}}
  ]});
  const snapshots=process.env.LANGFUSE_BROWSER_SNAPSHOTS || 'evals/langfuse/snapshots';
  const catalog=JSON.parse(fs.readFileSync(`${snapshots}/catalog.json`));
  const snapshot=catalog.suites.find(row=>row.name===AssistantName.CHAT).snapshot;
  const frozen=JSON.parse(fs.readFileSync(`${snapshots}/${snapshot}.json`));
  assert.ok(frozen.items.some(item=>item.source_observation_id===source.id));
  assert.equal(frozen.grading.evaluators.answer_quality.versionId,edited.versionId);
  await trigger(dataset,{action:'replay',snapshot});
  const deadline=Date.now()+180000;
  let completed=[];
  while(Date.now()<deadline) {
    const runs=(await api('experiments',{datasetId:dataset.id,fromStartTime:since,limit:100})).data.filter(row=>row.name.includes(stamp));
    const items=[];
    for(const run of runs) items.push(...(await api('experiment-items',{experimentId:run.id,fromStartTime:since,fields:'core,io,scores',limit:100})).data);
    if(items.length===8 && items.every(item=>item.scores.some(score=>score.name==='attempt_pass' && (score.value===1 || score.value===true)))) {
      completed=items;
      break;
    }
    await page.waitForTimeout(2000);
  }
  assert.equal(completed.length,8,'Full application variants and frozen replay must complete native grading');
  assert.ok(completed.every(item=>JSON.stringify(item.output).includes('Mock application reply.')));
  const observations=[];
  for(const item of completed) {
    const spans=(await api('v2/observations',{traceId:item.traceId,fields:'core,basic,usage,prompt',limit:100})).data;
    const generation=spans.find(span=>span.type==='GENERATION' && span.promptName===baselinePrompt.name);
    assert.ok(generation,'The real chat generation must link to its owning prompt');
    assert.equal(generation.promptVersion,item.experimentName.includes('-candidate') ? candidatePrompt.version : baselinePrompt.version);
    assert.equal(generation.totalUsage,15);
    assert.ok(spans.some(span=>span.id===generation.parentObservationId));
    assert.ok(!spans.some(span=>span.name==='assistant-usage'));
    observations.push(...spans);
  }
  fs.writeFileSync('/tmp/chattft-browser-review-report.json',JSON.stringify({snapshot,source,items:completed,observations},null,2));
  console.log('Two full application variants and frozen capture replay passed native grading.');
  await page.screenshot({path:'/tmp/chattft-langfuse-review.png',fullPage:true});
} catch(error) {
  await page.screenshot({path:'/tmp/chattft-langfuse-review-failure.png',fullPage:true});
  throw error;
} finally {
  await browser.close();
}
