import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithOxc } from 'vite';

async function compiled(name,replacements={}) {
  const source=await fs.readFile(new URL('../src/'+name,import.meta.url),'utf8');
  let {code}=await transformWithOxc(source,name);
  code=code.replace(/import\s+['"]\.\/[^'"]+\.css['"];?/g,'');
  for(const [from,to] of Object.entries(replacements)) code=code.replaceAll(`"${from}"`,JSON.stringify(to)).replaceAll(`'${from}'`,JSON.stringify(to));
  for(const name of ['react','react/jsx-runtime']) code=code.replaceAll(`"${name}"`,JSON.stringify(import.meta.resolve(name))).replaceAll(`'${name}'`,JSON.stringify(import.meta.resolve(name)));
  return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64');
}
const selectionURL=await compiled('splitSelection.ts');
const {toggleSplitModel,changeSplitLanguage,addSplitLanguage}=await import(selectionURL);
const options=[{record_id:'ar',model:'A',language:'俄语(Russian)'},{record_id:'ae',model:'A',language:'英语(English)'},{record_id:'af',model:'A',language:'法语(French)'},{record_id:'be',model:'B',language:'英语(English)'}];

test('model pool chooses one language and rebalances quantity when models change',()=>{
 const one=toggleSplitModel({},options,'A',101);assert.deepEqual(one,{ae:101});
 const two=toggleSplitModel(one,options,'B',101);assert.deepEqual(two,{ae:51,be:50});
 assert.deepEqual(toggleSplitModel({ae:30,af:20,be:51},options,'A',101),{be:101});
});
test('language changes keep quantities and merge an existing combination without duplicates',()=>{
 const input={ae:7,af:3,be:20};const changed=changeSplitLanguage(input,options,'ae','af');
 assert.deepEqual(changed,{af:10,be:20});assert.deepEqual(input,{ae:7,af:3,be:20});
 assert.throws(()=>changeSplitLanguage(input,options,'ae','be'));
});
test('adding a language preserves the model subtotal and other selected models',()=>{
 const next=addSplitLanguage({ae:51,be:50},options,'A');
 assert.deepEqual(next,{ae:26,be:50,ar:25});
 assert.equal(next.ae+next.ar,51);
 assert.deepEqual(addSplitLanguage({be:50},options,'B'),{be:50});
});
test('selected table is rendered above a model-only pool with selected models blue',async()=>{
 const {default:Editor}=await import(await compiled('SplitSelectionEditor.tsx',{'./splitSelection':selectionURL}));
 const html=renderToStaticMarkup(createElement(Editor,{options,quantities:{ae:50,be:50},total:100,lang:'zh',onChange:()=>{}}));
 assert.ok(html.indexOf('<table')<html.indexOf('class="split-model-pool"'));
 assert.equal((html.match(/<select /g)||[]).length,2);
 const pool=html.slice(html.indexOf('class="split-model-pool"'));
 assert.equal((pool.match(/class="chosen"/g)||[]).length,2);
 assert.equal((pool.match(/<button /g)||[]).length,2);
 assert.ok(!pool.includes('<select')&&!pool.includes('<input')&&!pool.includes('Russian'));
});
test('category grouping emits one full-span horizontal band per category',async()=>{
 const groupURL=await compiled('categoryGroups.ts');
 const {CategoryRows}=await import(await compiled('CategoryGroups.tsx',{'./categoryGroups':groupURL}));
 const rows=[{category:'折页',quantity:10},{category:'礼品',quantity:3},{category:'折页',quantity:20}];
 const html=renderToStaticMarkup(createElement('table',{},createElement('tbody',{},createElement(CategoryRows,{items:rows,category:r=>r.category,columns:11,lang:'zh',render:(row,index)=>createElement('tr',{key:index},createElement('td',{},String(index)))}))));
 assert.equal((html.match(/class="request-category-band" colSpan="11"/gi)||[]).length,2);
 assert.ok(html.includes('2 条 · 30 件'));
});
