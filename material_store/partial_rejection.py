"""Selective cultural/apparel rejection inside the existing PostgreSQL job transaction."""
from __future__ import annotations

def request_identities(request_id):
    import app
    from . import repository as repo
    identities={request_id}
    client=app.feishu_client()
    def lookup(conn):return repo.raw_record(conn,repo.named_table(conn,app.REQUEST_TABLE_NAME),request_id)
    row=client._call(lookup)
    if row['remote_id']:identities.add(row['remote_id'])
    return identities

def select_lines(lines, line_ids=None, *, id_key='line_record_id'):
    import app
    available={str(line[id_key]):line for line in lines}
    if line_ids is not None:
        if (not isinstance(line_ids,list) or not 1<=len(line_ids)<=200
            or any(not isinstance(key,str) or not key or key not in available for key in line_ids)
            or len(set(line_ids))!=len(line_ids)):
            raise ValueError('请选择当前申请单中有效且不重复的驳回明细。')
        chosen=set(line_ids)
    else:chosen=set(available)
    active=[line for line in lines if line.get('status')!=app.CULTURAL_REQUEST_STATUS_REJECTED]
    selected=[line for line in active if str(line[id_key]) in chosen]
    remaining=[line for line in active if str(line[id_key]) not in chosen]
    return selected,remaining


def apparel_plan(request_no,operator,line_ids=None):
    import app
    from . import apparel
    if operator not in set(app.enabled_role_open_ids('HR'))|set(app.enabled_admin_open_ids()):
        raise PermissionError('仅 HR 和管理员可驳回企业文化衫申领。')
    context=app.corporate_apparel_request_context(request_no);request=context['request']
    selected,remaining=select_lines(context['lines'],line_ids)
    if not selected or request['status']==app.CULTURAL_REQUEST_STATUS_REJECTED:
        return {'already_rejected':True,'context':context,'stock_targets':[],'quota_targets':[]}
    if request['status'] not in {app.CULTURAL_REQUEST_STATUS_ISSUED,app.CULTURAL_REQUEST_STATUS_REJECTING}:
        raise ValueError('仅已发放的企业文化衫申领可以驳回。')
    client=app.corporate_apparel_source_client()
    rows=client.list_records(app.CORPORATE_APPAREL_SOURCE_TABLE_ID)
    source={row['record_id']:row for row in rows}
    aliases={row['record_id']:app.corporate_apparel_source_record_id(row['fields'].get('SourceID')) for row in app.fresh_feishu_rows(app.CORPORATE_APPAREL_TABLE_NAME)}
    targets=[];totals={};redeemed={}
    for item in selected:
        source_id=item.get('source_record_id') or aliases.get(item['record_id']) or item['record_id']
        row=source.get(source_id)
        if not row:
            row=client.get_record(app.CORPORATE_APPAREL_SOURCE_TABLE_ID,source_id)
        source_id=row['record_id']
        key=item.get('style_key') or apparel.group_rows([row])[0]['key']
        quantity=max(0,int(item.get('issued_quantity',item['quantity'])))
        totals[key]=totals.get(key,0)+quantity
        current=redeemed.get(source_id,app.feishu_int(row['fields'],'系统兑换数量'))
        redeemed[source_id]=max(0,current-quantity)
        targets.append({**item,'quantity':quantity,'source_record_id':source_id,'target_system_redeemed':redeemed[source_id]})
    permission=next((row for row in app.fresh_feishu_rows(app.USER_PERMISSION_TABLE_NAME) if request['requester_open_id'] in app.feishu_person_open_ids(row['fields'],['用户账号','用户','成员'])),None)
    if not permission:raise ValueError('未找到申请人权限记录。')
    quota=[]
    for key,quantity in totals.items():
        if key in app.CORPORATE_APPAREL_QUOTA_FIELDS:
            field,_=app._corporate_apparel_quota_field(key)
            quota.append({'field':field,'target':max(0,app.feishu_int(permission['fields'],field)-quantity)})
    return {'already_rejected':False,'context':context,'permission_record_id':permission['record_id'],
            'stock_targets':targets,'quota_targets':quota,'partial_rejected':bool(remaining),
            'rejected_line_ids':[item['line_record_id'] for item in selected],'remaining_line_count':len(remaining)}


def reject_cultural(draft):
    import app
    from datetime import datetime
    operator=str(draft.get('operator_open_id') or '')
    if operator not in set(app.enabled_admin_open_ids())|set(app.enabled_role_open_ids('HR')):
        raise PermissionError('仅 HR 和管理员可驳回文化周边申领。')
    context=app.cultural_request_context(str(draft.get('request_no') or ''));request=context['request'];number=request['request_no']
    selected,remaining=select_lines(context['lines'],draft.get('line_ids'),id_key='record_id')
    if not selected or request['status']==app.CULTURAL_REQUEST_STATUS_REJECTED:
        return {'request_no':number,'already_rejected':True,'rejected':True,'restored_quantity':0}
    if request['status'] not in {app.CULTURAL_REQUEST_STATUS_ISSUED,app.CULTURAL_REQUEST_STATUS_REJECTING}:
        raise ValueError('仅已发放的文化周边申领可以驳回。')
    stock={row['record_id']:row for row in app.fresh_feishu_rows(app.CULTURAL_MATERIAL_TABLE_NAME)}
    ledgers={app.feishu_text(row['fields'],'幂等键'):row for row in app.fresh_feishu_rows(app.LEDGER_TABLE_NAME)}
    quantities={};restored=0
    # Validate every selected stock link before writing any changes.
    for line in selected:
        links=line.get('culture_record_ids') or []
        if len(links)!=1:raise ValueError('文化周边申请明细缺少有效的库存关联，无法驳回。')
        if links[0] not in stock:
            row=app.feishu_client().get_record(app.feishu_table_id(app.CULTURAL_MATERIAL_TABLE_NAME),links[0])
            stock[links[0]]=row
    for line in selected:
        key=line['record_id'];stock_alias=line['culture_record_ids'][0];row=stock[stock_alias];stock_id=row['record_id']
        stock[stock_id]=row
        quantity=max(0,int(line.get('issued_quantity',line['quantity'])))
        ledger_key='cultural-reject:'+number+':'+key
        if ledger_key not in ledgers and quantity:
            before=quantities.get(stock_id,app.feishu_int(stock[stock_id]['fields'],'当前库存'));after=before+quantity
            ledgers[ledger_key]=app.feishu_create_record(app.LEDGER_TABLE_NAME,{
                '操作':app.ACTION_PURCHASE,'数量':quantity,'库存变化':quantity,'变更前数量':before,'变更后数量':after,
                '幂等键':ledger_key,'流水业务类型':'文化周边申领驳回','文化周边战区快照':str(line.get('region') or ''),
                '文化周边物料':[stock_id],'关联明细':[key],
                '备注':f"文化周边申领驳回 {number}：{line.get('product')} / {line.get('model')} / {line.get('region')}",
                '时间':app.feishu_datetime_value(app.LEDGER_TABLE_NAME,'时间',datetime.now())})
            patch=app.cultural_stock_fields(after)
            if before<=0<after:patch[app.CULTURAL_CLAIMABLE_FIELD]=app.CULTURAL_CLAIMABLE_YES
            app.feishu_update_record_fields(app.CULTURAL_MATERIAL_TABLE_NAME,stock_id,patch)
            quantities[stock_id]=after;restored+=quantity
        app.feishu_update_record_fields(app.REQUEST_LINE_TABLE_NAME,key,{'审批通过数量':0,'实际发放数量':0,'明细状态':app.CULTURAL_REQUEST_STATUS_REJECTED})
    # Existing source choices stay intact: an issued header means there are
    # retained lines. History/cards derive the partial status from line states.
    app.feishu_update_record_fields(app.REQUEST_TABLE_NAME,request['record_id'],{
        '文化周边处理状态':app.CULTURAL_REQUEST_STATUS_ISSUED if remaining else app.CULTURAL_REQUEST_STATUS_REJECTED,
        '文化周边通知状态':'驳回待通知'})
    quota=app.recalculate_cultural_request_quota(request['requester_open_id'])
    return {'request_no':number,'rejected':True,'partial_rejected':bool(remaining),'restored_quantity':restored,
            'rejected_line_ids':[line['record_id'] for line in selected],'remaining_line_count':len(remaining),'quota':quota}


def notification_targets(request_no,*,apparel=False):
    import app,os
    from urllib.parse import urlencode
    context=app.corporate_apparel_request_context(request_no) if apparel else app.cultural_request_context(request_no)
    request=context['request'];lines=context['lines']
    rejected=[line for line in lines if line.get('status')==app.CULTURAL_REQUEST_STATUS_REJECTED]
    retained=[line for line in lines if line.get('status')!=app.CULTURAL_REQUEST_STATUS_REJECTED]
    partial=bool(retained);kind='企业文化衫领取' if apparel else '文化周边申领'
    title=kind+('部分驳回' if partial else '已驳回')
    identities=dict(request.get('message_ids') or {});recipients={}
    applicant=request.get('requester_open_id')
    if applicant:recipients['applicant:'+applicant]=applicant
    for identity in app.enabled_role_open_ids('HR') if apparel else app.enabled_admin_open_ids():
        recipients[('hr:' if apparel else 'admin:')+identity]=identity
    def table(rows):
        if apparel:
            from .apparel import display_name
            rows=[{**line,'product':display_name(str(line.get('product') or '')),'model':line.get('size')} for line in rows]
        return app._feishu_requester_material_table(rows)
    targets=[]
    for key,recipient in recipients.items():
        elements=[{'tag':'markdown','content':('您的' if key.startswith('applicant:') else str(request.get('requester') or '申请人')+' 的')+kind+('已有部分物料驳回，未驳回明细继续保留。' if partial else '已驳回。')+'所驳回明细的库存和领取额度已恢复。'},
                  {'tag':'markdown','content':'**已驳回明细**'},table(rejected)]
        if retained:elements.extend([{'tag':'markdown','content':'**保留明细**'},table(retained)])
        url=os.environ.get('PUDU_PUBLIC_ORIGIN','https://materials.pudu.work').rstrip('/')+'/management/request-history?'+urlencode({'request_id':request['record_id']})
        elements.append({'tag':'button','type':'primary_filled','width':'fill','text':{'tag':'plain_text','content':'查看申请记录'},'behaviors':[{'type':'open_url','default_url':url}]})
        card={'schema':'2.0','config':{'update_multi':True,'width_mode':'default','summary':{'content':title}},
              'header':{'template':'orange' if partial else 'red','title':{'tag':'plain_text','content':title},'subtitle':{'tag':'plain_text','content':request_no}},
              'body':{'direction':'vertical','padding':'12px','elements':elements}}
        targets.append({'key':key,'recipient_id':recipient,'message_id':identities.get(key,''),'card':card})
    return targets
