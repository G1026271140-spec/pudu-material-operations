import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {transformWithOxc} from 'vite';
async function compiled(name,replacements={}) {
 let {code}=await transformWithOxc(await fs.readFile(new URL('../src/'+name,import.meta.url),'utf8'),name);
 code=code.replace(/import\s+['"]\.\/[^'"]+\.css['"];?/g,'');
 for(const [from,to] of Object.entries(replacements))code=code.replaceAll(`"${from}"`,JSON.stringify(to)).replaceAll(`'${from}'`,JSON.stringify(to));
 for(const name of ['react','react/jsx-runtime'])code=code.replaceAll(`"${name}"`,JSON.stringify(import.meta.resolve(name))).replaceAll(`'${name}'`,JSON.stringify(import.meta.resolve(name)));
 return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64');
}
const group=await compiled('categoryGroups.ts');
const rows=await compiled('CategoryGroups.tsx',{'./categoryGroups':group});
const {default:Picker,chosenRejectionLines}=await import(await compiled('RejectionLinePicker.tsx',{'./CategoryGroups':rows}));
const lines=[{id:'one',product:'文化衫',model:'M',dimension:'华南',quantity:2,issued:2,approved:2,status:'已发放',remark:'',can_reject:true},
 {id:'two',product:'夹克',model:'L',dimension:'华南',quantity:1,issued:0,approved:0,status:'已驳回',remark:'',can_reject:false}];
test('only eligible selected lines are submitted, with no default selection',()=>{
 assert.deepEqual(chosenRejectionLines(lines,[]),[]);
 assert.deepEqual(chosenRejectionLines(lines,['one','two','foreign']),[lines[0]]);
 const html=renderToStaticMarkup(createElement(Picker,{lines,enabled:true,lang:'zh'}));
 assert.ok(!html.includes('checked=""'));
 assert.equal((html.match(/type="checkbox"/g)||[]).length,2);
 assert.equal((html.match(/disabled=""/g)||[]).length,1);
 assert.ok(html.includes('colSpan="6"'));
});
test('selected line is highlighted and confirmation can display just that line',()=>{
 const html=renderToStaticMarkup(createElement(Picker,{lines,selectedIds:['one'],enabled:true,lang:'zh'}));
 assert.ok(html.includes('at-rejection-selected')&&html.includes('已选 1 项 / 2 件'));
 const confirmation=renderToStaticMarkup(createElement(Picker,{lines:chosenRejectionLines(lines,['one']),lang:'zh'}));
 assert.ok(confirmation.includes('文化衫')&&!confirmation.includes('夹克')&&!confirmation.includes('type="checkbox"'));
});
