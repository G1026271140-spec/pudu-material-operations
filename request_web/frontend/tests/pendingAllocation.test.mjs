import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithOxc } from 'vite';
async function moduleCode(name){return (await transformWithOxc(await fs.readFile(new URL('../src/'+name,import.meta.url),'utf8'),name)).code;}
const uri=code=>'data:text/javascript;base64,'+Buffer.from(code).toString('base64');
const grouping=await moduleCode('pendingAllocation.ts');
const {groupPendingByDate,submissionDay}=await import(uri(grouping));
let list=await moduleCode('PendingAllocationList.tsx');
list=list.replace(/(['"])\.\/pendingAllocation\1/g,JSON.stringify(uri(grouping)));
list=list.replace(/(['"])\.\/allocationPresentation\1/g,JSON.stringify(uri(await moduleCode('allocationPresentation.ts'))));
for(const name of ['react','react/jsx-runtime'])list=list.replaceAll('"'+name+'"',JSON.stringify(import.meta.resolve(name))).replaceAll("'"+name+"'",JSON.stringify(import.meta.resolve(name)));
const {default:PendingList}=await import(uri(list));
const requests=[
 {requestId:'one',requestNo:'REQ-DEMO-001',submittedAt:'2026-10-29 10:00:00',requester:'申请人 A',department:'市场部',reason:'展会支持',lineCount:3,recordVersion:1,reviewLabel:'暂缓评估',reviewNote:'等待展会预算确认',requiredArrivalStart:'2026-11-10'},
 {requestId:'two',requestNo:'REQ-DEMO-002',submittedAt:'2026-10-29 09:00:00',requester:'申请人 B',department:'市场部',reason:'客户演示',lineCount:2,recordVersion:0},
 {requestId:'old',requestNo:'REQ-DEMO-003',submittedAt:'2026-10-23 11:00:00',requester:'申请人 C',department:'销售部',reason:'活动支持',lineCount:5,recordVersion:0,reviewNote:'已向申请人补充了解活动安排'},
];
test('pending requests group by Beijing submission date, newest dates first; undated requests remain visible',()=>{
 const grouped=groupPendingByDate([{requestId:'none',requestNo:'N'},...requests]);
 assert.deepEqual(grouped.map(g=>g.date),['2026-10-29','2026-10-23','']);
 assert.deepEqual(grouped[0].requests.map(r=>r.requestId),['one','two']);
 assert.equal(submissionDay('2026-10-29T17:30:00Z'),'2026-10-30');
 assert.equal(submissionDay('2026-10-29 03:00:00'),'2026-10-29');
 assert.equal(submissionDay('2026-02-30'),'');assert.equal(submissionDay('invalid'),'');
});
test('custom labels mark only the labeled card and notes are escaped',()=>{
 const data=structuredClone(requests);data[0].reviewNote='<script>unsafe</script>';
 const html=renderToStaticMarkup(createElement(PendingList,{requests:data,lang:'zh',onOpen:()=>{},onAnnotate:()=>{}}));
 assert.equal((html.match(/class="pending-card is-tagged"/g)||[]).length,1);
 assert.ok(html.includes('暂缓评估')&&html.includes('2026年10月29日')&&html.includes('2026年10月23日'));
 assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));
 assert.equal((html.match(/标签和备注 REQ-DEMO/g)||[]).length,3);
 const first=html.slice(html.indexOf('<article'),html.indexOf('</article>'));
 assert.ok(first.indexOf('</button>')<first.indexOf('<button',first.indexOf('<button')+1));
 data[0].reviewLabel='';
 const cleared=renderToStaticMarkup(createElement(PendingList,{requests:data,lang:'en',onOpen:()=>{},onAnnotate:()=>{}}));
 assert.ok(!cleared.includes('pending-card is-tagged'));
});
if(process.env.PUDU_PENDING_PREVIEW){
 const html=renderToStaticMarkup(createElement(PendingList,{requests,lang:'zh',onOpen:()=>{},onAnnotate:()=>{}}));
 const css=await fs.readFile(new URL('../src/allocation.css',import.meta.url),'utf8')+'\n'+await fs.readFile(new URL('../src/pending-followup.css',import.meta.url),'utf8');
 await fs.writeFile(process.env.PUDU_PENDING_PREVIEW,`<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>待核实标签样式验收</title><style>body{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif}${css}</style><main class="allocation-page standalone"><section class="pending-panel"><div class="pending-head"><h2>待库存核实申请</h2><span>3 条</span></div>${html}</section></main></html>`);
}
