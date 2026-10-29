import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithOxc } from 'vite';
let {code}=await transformWithOxc(await fs.readFile(new URL('../src/TaskMonitorPage.tsx',import.meta.url),'utf8'),'TaskMonitorPage.tsx');
code=code.replace(/import\s+['"]\.\/[^'"]+\.css['"];?/g,'').replace(/import ToastMessage from [^;]+;/,'const ToastMessage=()=>null;');
for(const name of ['react','react/jsx-runtime'])code=code.replaceAll('"'+name+'"',JSON.stringify(import.meta.resolve(name))).replaceAll("'"+name+"'",JSON.stringify(import.meta.resolve(name)));
const {TaskTable,taskTime,taskLabel,WorkerHeartbeats}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('task list distinguishes running, retry and conflict with human business labels',()=>{
 const entries=['processing','retry','conflict'].map((state,n)=>({kind:['jobs','outbox','effects'][n],id:'task-'+n,title:'send_interactive_message',subject:'REQ-20261029-001',state,created_at:'2026-10-29T06:00:00Z',attempts:n,last_error:n===2?'<script>blocked</script>':null}));
 const html=renderToStaticMarkup(createElement(TaskTable,{entries,lang:'zh',onOpen:()=>{}}));
 for(const label of ['正在执行','等待重试','同步冲突','REQ-20261029-001','发送飞书卡片','业务处理','飞书同步','卡片与通知'])assert.ok(html.includes(label));
 assert.equal((html.match(/<button/g)||[]).length,3);assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));
});
test('task times always use China time regardless of browser timezone',()=>{
 assert.match(taskTime('2026-10-29T16:01:00Z','en'),/30\/10\/2026.*00:01/);
 assert.equal(taskLabel('done','en'),'Completed');assert.equal(taskTime(null,'zh'),'—');
});

test('scheduled contacts show their last successful refresh without a continuous-heartbeat warning',()=>{
 const workers=[{name:'worker:business:admin',updated_at:'2026-10-29T06:00:00Z',version:'V4.0.7',healthy:true,mode:'continuous'},
 {name:'worker:contacts',updated_at:'2026-10-28T19:10:00Z',version:'V4.0.3',healthy:null,mode:'scheduled'}];
 const html=renderToStaticMarkup(createElement(WorkerHeartbeats,{workers,lang:'zh'}));
 assert.ok(html.includes('1/1'));assert.ok(html.includes('1 项定时任务'));assert.ok(html.includes('定时刷新 · 上次完成'));assert.ok(!html.includes('心跳已过期'));
 workers[0].healthy=false;
 const stale=renderToStaticMarkup(createElement(WorkerHeartbeats,{workers,lang:'zh'}));assert.ok(stale.includes('心跳已过期'));
});
