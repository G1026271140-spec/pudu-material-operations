import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import { transformWithOxc } from 'vite';
const source = await fs.readFile(new URL('../src/categoryGroups.ts', import.meta.url), 'utf8');
const { code } = await transformWithOxc(source, 'categoryGroups.ts');
const { groupByCategory, splitCategoryRows } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const materials = Object.fromEntries(['a','b','c'].map((id,i) => [id,{ record_id:id, category:'折页',model:'型号'+i,language:'EN',quantity:100,category_definition:'印刷物料' }]));
materials.other={record_id:'other',category:'礼品',model:'',language:'',quantity:10};
const rows=[{uid:'a',category:'折页',line_record_id:'lineA',material_record_id:'a',quantity:10,remark:'第一条'}, {uid:'other',category:'礼品',material_record_id:'other',quantity:2}, {uid:'b',category:'折页',line_record_id:'lineB',material_record_id:'b',quantity:20,remark:'第二条'}];
test('category groups preserve first appearance and original indices for edits',()=>{
 const groups=groupByCategory(rows,r=>r.category);
 assert.deepEqual(groups.map(g=>[g.category,g.quantity,g.entries.map(e=>e.index)]),[['折页',30,[0,2]],['礼品',2,[1]]]);
 assert.equal(groups[0].entries[1].item,rows[2]);
});
test('one split replaces all category rows and preserves other categories',()=>{
 const next=splitCategoryRows(rows,'折页',{a:15,c:15},materials,['lineA','lineB'],()=> 'new');
 assert.deepEqual(next.map(r=>[r.material_record_id,r.quantity]),[['a',15],['c',15],['other',2]]);
 assert.equal(next[0].line_record_id,'lineA');assert.equal(next[1].line_record_id,'');
 assert.deepEqual(next[1].split_source_line_ids,['lineA','lineB']);
 assert.equal(next[2],rows[1]);assert.equal(rows.length,3);
});
test('category split supports consolidation and re-splitting without duplicate materials',()=>{
 const consolidated=splitCategoryRows(rows,'折页',{b:30},materials,['lineA','lineB'],()=> 'new');
 assert.equal(consolidated.length,2);assert.equal(consolidated[0].line_record_id,'lineB');
 const split=splitCategoryRows(consolidated,'折页',{a:10,b:10,c:10},materials,['lineA','lineB'],()=>crypto.randomUUID());
 assert.equal(new Set(split.map(r=>r.material_record_id)).size,4);
 assert.equal(split.reduce((n,r)=>n+r.quantity,0),32);
});
test('invalid target category and fractional/empty splits are rejected',()=>{
 for(const input of [{other:30},{a:1.2},{}]) assert.throws(()=>splitCategoryRows(rows,'折页',input,materials,['lineA','lineB'],()=> 'new'));
});
