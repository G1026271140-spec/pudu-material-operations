import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import test from 'node:test';
import { transformWithOxc } from 'vite';
const {code}=await transformWithOxc(await fs.readFile(new URL('../src/allocationRows.ts',import.meta.url),'utf8'),'allocationRows.ts');
const {chooseAllocationMaterial,nextAllocationMaterial,mergeAllocationRows}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const materials=[{record_id:'ar',category:'折页',model:'A',language:'RU'},{record_id:'ae',category:'折页',model:'A',language:'EN'},{record_id:'br',category:'折页',model:'B',language:'RU'},{record_id:'be',category:'折页',model:'B',language:'EN'}];
test('changing model preserves the chosen language even when another language is first in the catalog',()=>{
 assert.equal(chooseAllocationMaterial(materials,materials[1],'model','B').record_id,'be');
 assert.equal(chooseAllocationMaterial(materials,materials[1],'language','RU').record_id,'ar');
});
test('add skips existing specifications and stops when all are selected',()=>{
 assert.equal(nextAllocationMaterial(materials,[{material_record_id:'ar',quantity:10}]).record_id,'ae');
 assert.equal(nextAllocationMaterial(materials,materials.map(x=>({material_record_id:x.record_id,quantity:1}))),undefined);
});
test('converging edits preserve total quantities, notes and sources without changing the original draft',()=>{
 const rows=[{uid:'one',line_record_id:'line1',material_record_id:'be',quantity:20,remark:'原行',split_source_line_ids:['line1']},{uid:'two',line_record_id:'line2',material_record_id:'be',quantity:30,remark:'调整行',order_required:true,split_source_line_ids:['line2']},{uid:'other',material_record_id:'ar',quantity:7}];
 const copy=structuredClone(rows), result=mergeAllocationRows(rows);
 assert.equal(result.length,2);assert.equal(result[0].quantity,50);assert.equal(result[0].line_record_id,'line1');
 assert.equal(result[0].remark,'原行；调整行');assert.equal(result[0].order_required,true);
 assert.deepEqual(result[0].split_source_line_ids,['line1','line2']);assert.equal(result[1].quantity,7);
 assert.deepEqual(rows,copy);assert.deepEqual(mergeAllocationRows(result),result);
});
test('different languages stay separate and invalid quantities cannot be hidden by merging',()=>{
 assert.equal(mergeAllocationRows([{material_record_id:'be',quantity:10},{material_record_id:'br',quantity:20}]).length,2);
 for(const quantity of [-1,0,1.5,NaN]) assert.throws(()=>mergeAllocationRows([{material_record_id:'be',quantity:20},{material_record_id:'be',quantity}]));
});
