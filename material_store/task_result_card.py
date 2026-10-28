"""Compact administrator result receipt without internal IDs, JSON or job metadata."""

def card(kind,actor,subject,good,origin='https://materials.pudu.work'):
    shipping=kind=='发货信息同步'
    allocation=kind.startswith('申请物料库存') or kind=='物料申请撤回删除'
    section='发货' if shipping else '配货' if allocation else '物料管理'
    titles={'采购补库':'采购补库已完成','库存减库':'库存减库已完成','物料品类同步':'品类变更已完成','物料品类删除':'品类删除已完成','型号语种管理':'基础信息变更已完成','申请物料库存编辑':'配货调整已完成','申请物料库存确认':'库存核实已完成','申请物料库存驳回':'物料申请已驳回','物料申请撤回删除':'申请删除已完成','发货信息同步':'发货信息已同步'}
    label=titles.get(kind,section+'任务已完成') if good else section+'任务需核对'
    path='/management/shipping-calendar' if shipping else '/management/allocation' if allocation else '/management'
    def text(value):return {'tag':'plain_text','content':str(value)}
    # Keep request data as plain text; only the single navigation button is interactive.
    elements=[{'tag':'column_set','flex_mode':'none','background_style':'green-50' if good else 'orange-50','columns':[
        {'tag':'column','width':'weighted','weight':1,'padding':'12px','elements':[{'tag':'div','text':text('操作人：'+str(actor))}]}]}]
    if subject:elements.append({'tag':'div','text':text(subject)})
    if not good:elements.append({'tag':'div','text':text('部分后台处理或同步需要核对，请进入页面查看。')})
    elements.append({'tag':'button','text':text('查看'+section),'type':'primary_filled','width':'fill','behaviors':[{'type':'open_url','default_url':origin.rstrip('/')+path}]})
    return {'schema':'2.0','config':{'width_mode':'default','update_multi':True,'summary':{'content':label}},
        'header':{'title':text(label),'template':'green' if good else 'orange'},
        'body':{'direction':'vertical','padding':'12px','vertical_spacing':'12px','elements':elements}}
