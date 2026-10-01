import assert from 'node:assert/strict';
// Optional tool dependency stays outside the application and desktop permissions.
const { chromium } = await import(process.env.FLOWCHART_PLAYWRIGHT_MODULE ?? 'playwright');
const baseURL = process.env.FLOWCHART_SMOKE_URL ?? 'http://127.0.0.1:8429';
const browser = await chromium.launch({ headless: true, env: process.env });
const page = await browser.newPage({ viewport: { width: 1700, height: 1200 } }), errors=[];
page.on('pageerror',e=>errors.push(e.message));
const workspace={schema_version:'flowchart.v2',name:`Branch smoke ${Date.now()}`,gameplan:{flowchart:{elements:[
 {id:'a',kind:'action',position:{x:100,y:100},title:'Roll'}, {id:'b',kind:'decision',position:{x:100,y:300},title:'Hit?'},
 {id:'c',kind:'plan',position:{x:500,y:300},title:'Pivot'}],connections:[
 {id:'ab',source:'a',target:'b',condition:'Hit two star',source_handle:'bottom',target_handle:'top'},
 {id:'bc',source:'b',target:'c',condition:'Otherwise',notes:'Pivot carefully',source_handle:'right',target_handle:'left'}]}}};
const response=await page.request.post(`${baseURL}/api/flowchart/workspaces/import`,{data:{workspace}});assert.equal(response.status(),201);const record=await response.json();
const url=`${baseURL}/api/flowchart/workspaces/${record.id}`;
const tools=page.getByRole('toolbar',{name:'Layout and selection'}),canvasTools=page.getByRole('toolbar',{name:'Canvas tools'});
/** Read only the disposable workspace created by this smoke run. */
const load=async()=> (await (await page.request.get(url)).json()).workspace.gameplan.flowchart;
/** Allow debounce to finish, then verify autosave status before inspecting storage. */
const waitSaved=async()=>{await page.waitForTimeout(1100);assert.equal((await page.getByRole('status').first().textContent()).trim(),'Saved');};
/** Pick a node away from text editors and connection handles. */
const selectNode=async(id,modifiers=[])=>page.locator(`.react-flow__node[data-id="${id}"]`).click({position:{x:20,y:15},modifiers});
try{
 await page.goto(`${baseURL}/flowchart`);await page.locator('.react-flow__node[data-id="a"]').waitFor();
 // Reproduce the persistent selection rectangle, rather than only selecting with keyboard shortcuts.
 const aBox=await page.locator('.react-flow__node[data-id="a"]').boundingBox();
 const bBox=await page.locator('.react-flow__node[data-id="b"]').boundingBox();
 await page.mouse.move(Math.min(aBox.x,bBox.x)-12,Math.min(aBox.y,bBox.y)-12);await page.mouse.down();
 await page.mouse.move(Math.max(aBox.x+aBox.width,bBox.x+bBox.width)+12,Math.max(aBox.y+aBox.height,bBox.y+bBox.height)+12,{steps:10});await page.mouse.up();
 assert.equal(await page.locator('.react-flow__node.selected').count(),2);
 assert.equal(await page.locator('.react-flow__nodesselection-rect').count(),1);
 const canvasBox=await page.getByTestId('flowchart-canvas').boundingBox();
 const empty={x:canvasBox.x+canvasBox.width-100,y:canvasBox.y+50};
 const menu=page.getByRole('group',{name:'Selection menu'});
 // A press must neither clear the highlight nor open a popup before release.
 await page.mouse.move(empty.x,empty.y);await page.mouse.down({button:'right'});await page.waitForTimeout(75);
 assert.equal(await menu.count(),0);assert.equal(await page.locator('.react-flow__node.selected').count(),2);
 await page.mouse.up({button:'right'});await menu.waitFor();
 assert.equal(await page.locator('.react-flow__node.selected').count(),2);
 const menuBox=await menu.boundingBox();assert.ok(Math.abs(menuBox.x-empty.x)<4);assert.ok(Math.abs(menuBox.y-empty.y)<4);
 await page.keyboard.press('Escape');assert.equal(await menu.count(),0);
 const viewport=page.locator('.react-flow__viewport'),beforePan=await viewport.getAttribute('style');
 await page.mouse.down({button:'right'});await page.mouse.move(empty.x-80,empty.y+30,{steps:8});await page.mouse.up({button:'right'});
 assert.notEqual(await viewport.getAttribute('style'),beforePan);assert.equal(await menu.count(),0);
 assert.equal(await page.locator('.react-flow__node.selected').count(),2);
 // A drag that returns to its starting point and a stationary hold are also not clicks.
 await page.mouse.down({button:'right'});await page.mouse.move(empty.x-140,empty.y+30,{steps:4});await page.mouse.move(empty.x-80,empty.y+30,{steps:4});await page.mouse.up({button:'right'});
 assert.equal(await menu.count(),0);
 await page.mouse.down({button:'right'});await page.waitForTimeout(400);await page.mouse.up({button:'right'});assert.equal(await menu.count(),0);
 // Restore the viewport so the following layout/clipboard checks start from their original scene.
 await page.mouse.down({button:'right'});await page.mouse.move(empty.x,empty.y,{steps:8});await page.mouse.up({button:'right'});
 assert.equal(await viewport.getAttribute('style'),beforePan);
 await page.mouse.click(empty.x,empty.y);
 assert.equal(await page.locator('.react-flow__node.selected, .react-flow__edge.selected, .react-flow__nodesselection-rect').count(),0);
 // Right-clicking an object targets it; choosing a command dismisses the popup.
 await page.locator('.flowchart-edge-label[data-id="ab"]').click({button:'right'});await menu.waitFor();
 await page.locator('.react-flow__edge.selected[data-id="ab"]').waitFor();
 assert.equal(await menu.getByRole('button',{name:'Insert action',exact:true}).isEnabled(),true);
 await page.keyboard.press('Escape');
 const cBox=await page.locator('.react-flow__node[data-id="c"]').boundingBox();
 await page.mouse.click(cBox.x+20,cBox.y+15,{button:'right'});await menu.waitFor();
 await page.locator('.react-flow__node.selected[data-id="c"]').waitFor();
 await menu.getByRole('button',{name:'Close menu',exact:true}).click();assert.equal(await menu.count(),0);
 await page.mouse.click(empty.x,empty.y,{button:'right'});await menu.waitFor();
 await menu.getByRole('button',{name:'Add note',exact:true}).click();assert.equal(await menu.count(),0);
 await waitSaved();assert.equal((await load()).elements.filter(e=>e.kind==='note').length,1);
 await canvasTools.getByRole('button',{name:'Undo',exact:true}).click();await waitSaved();assert.equal((await load()).elements.length,3);
 console.log(JSON.stringify({passed:true,checks:['marquee deselection','right click on release','right pan preserves selection','returning drag','hold','node/edge context menu','add at cursor','menu dismissal']}));
 // Reload after the pointer fixture so React Flow's temporary selection/gesture state is fresh.
 await page.reload();await page.locator('.react-flow__node[data-id="a"]').waitFor();
 await selectNode('a');await selectNode('b',['Shift']);await tools.getByRole('button',{name:'Group',exact:true}).click();
 await waitSaved();let doc=await load();let group=doc.elements.find(e=>e.kind==='group');assert.ok(group);assert.equal(doc.elements.filter(e=>e.parent_id===group.id).length,2);
 await page.locator(`.react-flow__node[data-id="${group.id}"]`).getByRole('button',{name:'Collapse group',exact:true}).click();
 await page.locator('.react-flow__edge[data-id="bc"]').waitFor();
 assert.equal(await page.locator('.react-flow__node[data-id="a"]').count(),0);assert.equal(await page.locator('.react-flow__edge[data-id="ab"]').count(),0);assert.equal(await page.locator('.react-flow__edge[data-id="bc"]').count(),1);
 await tools.getByRole('button',{name:'Layout diagram',exact:true}).click();await page.waitForTimeout(800);await page.getByText('Arranging diagram…').waitFor({state:'hidden'});
 assert.equal(await page.getByRole('alert').count(),0);await waitSaved();
 await page.locator(`.react-flow__node[data-id="${group.id}"]`).getByRole('button',{name:'Expand group',exact:true}).click();
 await page.waitForTimeout(800);
 await page.locator('.react-flow__edge[data-id="bc"] .react-flow__edge-interaction').click({force:true});
 const guard=page.getByLabel('Guard in properties',{exact:true});await guard.dblclick();
 const longGuard='A long guard that wraps: choose this branch when contested, after finding a strong item holder and preserving enough economy for the next stage.';
 await page.locator('textarea[aria-label="Guard in properties"]').fill(longGuard);await page.locator('textarea[aria-label="Guard in properties"]').press('Control+Enter');
 await waitSaved();assert.equal((await load()).connections.find(e=>e.id==='bc').condition,longGuard);
 await page.waitForTimeout(600);const segments=page.locator('.flowchart-bend-grip');assert.ok(await segments.count()>0);
 const segment=await segments.nth(1).boundingBox();assert.ok(segment);
 await page.mouse.move(segment.x+segment.width/2,segment.y+segment.height/2);await page.mouse.down();await page.mouse.move(segment.x+segment.width/2+45,segment.y+segment.height/2+45,{steps:8});await page.mouse.up();
 await waitSaved();assert.ok((await load()).connections.find(e=>e.id==='bc').waypoints.length>0);
 await selectNode(group.id);await page.keyboard.press('Control+c');await page.mouse.move(1100,800);await page.keyboard.press('Control+v');await waitSaved();
 doc=await load();assert.equal(doc.elements.filter(e=>e.kind==='group').length,2);assert.equal(doc.elements.length,7);
 await canvasTools.getByRole('button',{name:'Undo',exact:true}).click();await waitSaved();assert.equal((await load()).elements.length,4);
 await canvasTools.getByRole('button',{name:'Redo',exact:true}).click();await waitSaved();assert.equal((await load()).elements.length,7);
 // Save a personal view, collapse a group, and verify both document and local views after reload.
 await selectNode(group.id);await page.getByLabel('Focus mode',{exact:true}).selectOption('downstream');
 await page.locator(`.react-flow__node[data-id="${group.id}"]`).getByRole('button',{name:'Collapse group',exact:true}).click();
 await page.getByLabel('Focus view name',{exact:true}).fill('Branch view');await page.getByRole('button',{name:'Save view',exact:true}).click();
 await page.reload();await page.locator(`.react-flow__node[data-id="${group.id}"]`).waitFor();
 await page.locator('.react-flow__edge[data-id="bc"]').waitFor();
 assert.equal(await page.locator('.react-flow__node[data-id="a"]').count(),0);assert.equal(await page.getByLabel('Named focus views').locator('option').count(),2);
 doc=await load();assert.equal(doc.elements.length,7);assert.equal(doc.connections.find(e=>e.id==='bc').condition,longGuard);assert.ok(doc.connections.find(e=>e.id==='bc').waypoints.length>0);
 if(process.env.FLOWCHART_SMOKE_SCREENSHOT) await page.screenshot({path:process.env.FLOWCHART_SMOKE_SCREENSHOT});assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,checks:['group','collapse proxies','layout','long guard','manual bend','clipboard','undo/redo','reload document and personal view'],elements:doc.elements.length,connections:doc.connections.length}));

 // Exercise the production worker bundles at the documented graph limits.
 const elements = Array.from({ length: 400 }, (_, i) => ({ id: `n${i}`, kind: 'action', title: `Node ${i}`,
   position: { x: (i % 20) * 240, y: Math.floor(i / 20) * 160 }, size: { width: 160, height: 70 } }));
 const connections = Array.from({ length: 800 }, (_, i) => ({ id: `e${i}`, source: `n${i % 400}`,
   target: `n${(i % 400 + (i < 400 ? 20 : 1)) % 400}`, condition: 'guard', source_handle: 'bottom', target_handle: 'top' }));
 const largeResponse = await page.request.post(`${baseURL}/api/flowchart/workspaces/import`, { data: { workspace: {
   schema_version: 'flowchart.v2', name: `Large smoke ${Date.now()}`, gameplan: { flowchart: { elements, connections } },
 } } });
 assert.equal(largeResponse.status(), 201);
 const large = await largeResponse.json();
 try {
   await page.reload();
   await page.locator('.flowchart-progress').waitFor();
   const routeStarted = Date.now();
   await page.getByLabel('Search diagram', { exact: true }).fill('Node 399');
   await page.getByRole('button', { name: 'element: Node 399', exact: true }).waitFor();
   const routingInputMs = Date.now() - routeStarted;
   assert.ok(routingInputMs < 2000, `Routing blocked search for ${routingInputMs} ms`);
   await page.locator('.flowchart-progress').waitFor({ state: 'hidden', timeout: 60000 });
   await tools.getByRole('button', { name: 'Layout diagram', exact: true }).click();
   await page.getByText('Arranging diagram…').waitFor();
   const layoutStarted = Date.now();
   await page.getByLabel('Search diagram', { exact: true }).fill('Node 0');
   await page.getByRole('button', { name: 'element: Node 0', exact: true }).waitFor();
   const layoutInputMs = Date.now() - layoutStarted;
   assert.ok(layoutInputMs < 2000, `Layout blocked search for ${layoutInputMs} ms`);
   await page.getByText('Arranging diagram…').waitFor({ state: 'hidden', timeout: 60000 });
   await page.locator('.flowchart-progress').waitFor({ state: 'hidden', timeout: 60000 });
   assert.equal(await page.getByRole('alert').count(), 0);
   assert.deepEqual(errors, []);
   console.log(JSON.stringify({ passed: true, elements: 400, connections: 800, routingInputMs, layoutInputMs }));
 } finally { await page.request.delete(`${baseURL}/api/flowchart/workspaces/${large.id}`); }
} finally { await page.request.delete(url); await browser.close(); }
