export type Spec={material_id:string;code:string;category:string;category_display?:string;model:string;language:string};
export type Line=Spec&{line_id:string;quantity:number;remark:string};
export type OrderRequest={request_id:string;request_no:string;requester:string;department:string;usage:string;status:string;ship_date:string;arrival_start:string;order_date:string;submitted_at:string;lines:Line[];quantity:number;selectable:boolean;warnings:string[];fingerprint:string};
export type Extra={id:string;source:'catalog'|'custom';material_id:string;category:string;model:string;language:string;quantity:number;usage:string;remark:string};
export type Basis='ship_date'|'arrival_start'|'order_date'|'submitted_at';
export type PrintFilter='print'|'none'|'all';
// Keep unresolved print associations visible for review instead of hiding them.
export function hasPrintItems(row:OrderRequest){return row.lines.length>0||row.warnings.length>0;}
export function filterRequests(rows:OrderRequest[],query:string,all:boolean,month:string,day:string,basis:Basis,printFilter:PrintFilter='print'){
 const q=query.trim().toLowerCase();return rows.filter(r=>(printFilter==='all'||hasPrintItems(r)===(printFilter==='print'))&&(all||(!r[basis]&&!day)||(day?r[basis]===day:r[basis].startsWith(month)))&&(!q||[r.request_no,r.requester,r.department,r.usage,...r.lines.flatMap(l=>[l.category,l.model,l.language])].join(' ').toLowerCase().includes(q)));
}
export function selectMany(current:Record<string,OrderRequest>,rows:OrderRequest[],checked:boolean){
 const next={...current};for(const row of rows){if(checked&&row.selectable){if(!next[row.request_id])next[row.request_id]=row;}else if(!checked)delete next[row.request_id];}return next;
}
export function addExtra(rows:Extra[],item:Extra){
 const key=(r:Extra)=>JSON.stringify([r.source,r.material_id,r.category,r.model,r.language,r.usage,r.remark]);
 const found=rows.find(r=>key(r)===key(item));return found?rows.map(r=>r.id===found.id?{...r,quantity:r.quantity+item.quantity}:r):[...rows,item];
}
export function exportBody(selected:Record<string,OrderRequest>,extras:Extra[],generation_date:string){
 const request_ids=Object.keys(selected).sort();return {request_ids,fingerprints:Object.fromEntries(request_ids.map(k=>[k,selected[k].fingerprint])),extras,generation_date};
}
