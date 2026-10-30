import assert from 'node:assert/strict';
import test from 'node:test';
import {filterRequests,selectMany,addExtra,exportBody} from '../src/orderPacking.ts';
const row=(n,date='2026-11-02')=>({request_id:String(n),request_no:'REQ-'+n,requester:'Test',department:'Marketing',usage:'Expo',ship_date:date,arrival_start:'2026-11-08',order_date:'2026-10-20',submitted_at:'2026-10-01',lines:[{category:'Flyer',model:'ET1',language:'French'}],quantity:2,selectable:true,fingerprint:'v1-'+n});
test('Bulk selection includes every filtered request and retains other dates',()=>{
 const rows=Array.from({length:250},(_,i)=>row(i));let selected=selectMany({'prior':{...row('prior'),fingerprint:'original'}},rows,true);
 assert.equal(Object.keys(selected).length,251);assert.equal(selected.prior.fingerprint,'original');
 selected=selectMany(selected,[{...row(0),fingerprint:'new'}],true);assert.equal(selected['0'].fingerprint,'v1-0');
 assert.equal(Object.keys(selectMany(selected,rows,false)).length,1);
 const body=exportBody(selected,[],'2026-11-02');assert.equal(body.request_ids.length,251);assert.equal(body.fingerprints['0'],'v1-0');
});
test('Calendar filters preserve unscheduled requests and all-dates search',()=>{
 const rows=[row(1),row(2,'2026-12-01'),row(3,'')];assert.equal(filterRequests(rows,'',false,'2026-11','','ship_date').length,2);
 assert.deepEqual(filterRequests(rows,'req-2',true,'2026-11','','ship_date').map(x=>x.request_id),['2']);
 assert.equal(filterRequests(rows,'french',false,'2026-11','2026-11-02','ship_date').length,1);
 assert.equal(Object.keys(selectMany({},[{...row(4),selectable:false}],true)).length,0);
});
test('Additional items merge only identical source specification purpose and production remarks',()=>{
 const item={id:'one',source:'catalog',material_id:'mat-1',category:'Flyer',model:'ET1',language:'French',quantity:5,usage:'Reserve',remark:''};
 const merged=addExtra([item],{...item,id:'two',quantity:7});assert.equal(merged.length,1);assert.equal(merged[0].quantity,12);assert.equal(merged[0].id,'one');
 assert.equal(addExtra(merged,{...item,id:'three',usage:'Expo'}).length,2);assert.equal(addExtra(merged,{...item,id:'four',remark:'Thicker paper'}).length,2);
 assert.equal(addExtra(merged,{...item,id:'custom',source:'custom',material_id:''}).length,2);
});
