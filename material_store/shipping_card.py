"""Applicant shipment receipt. The only action opens the owner-scoped read-only view."""
import html
from urllib.parse import quote

def card(number,request_id,shipped,ship_date,arrival_start,text,image_count,origin):
    def safe(value):
        value=html.escape(str(value or '未设置'),quote=True)
        for character in '*_[]()#~':value=value.replace(character,'&#'+str(ord(character))+';')
        return value
    url=origin.rstrip('/')+'/management/shipping-calendar?shipping_request='+quote(request_id,safe='')+'&shipping_view=readonly'
    return {'schema':'2.0','config':{'update_multi':True,'width_mode':'default','summary':{'content':'您的物料申请已发货' if shipped else '您的物料申请发货信息已更新'}},
        'header':{'title':{'tag':'plain_text','content':'您的物料申请已发货' if shipped else '您的物料申请发货信息已更新'},'subtitle':{'tag':'plain_text','content':'申请单号：'+str(number)},'template':'green' if shipped else 'blue'},
        'body':{'direction':'vertical','padding':'12px','vertical_spacing':'12px','elements':[
            {'tag':'column_set','flex_mode':'none','background_style':'green-50' if shipped else 'blue-50','horizontal_spacing':'12px','columns':[
                {'tag':'column','width':'weighted','weight':1,'padding':'12px','elements':[{'tag':'markdown','content':'**计划发货日**\n'+safe(ship_date)}]},
                {'tag':'column','width':'weighted','weight':1,'padding':'12px','elements':[{'tag':'markdown','content':'**要求到达开始日**\n'+safe(arrival_start)}]}]},
            {'tag':'markdown','content':'**发货单号及文字信息**\n'+safe(text or '未填写')[:5000]+'\n\n发货图片：'+str(image_count)+' 张，请进入申请单查看。'},
            {'tag':'button','text':{'tag':'plain_text','content':'查看申请单及发货图片（只读）'},'type':'primary_filled','width':'fill','behaviors':[{'type':'open_url','default_url':url}]}]}}


def date_change_card(number,request_id,previous_date,new_date,shipped,origin):
    """One applicant notice for a confirmed change to the planned ship date."""
    title='物料发货时间变更通知'
    url=origin.rstrip('/')+'/management/shipping-calendar?shipping_request='+quote(request_id,safe='')+'&shipping_view=readonly'
    def text(value):return {'tag':'plain_text','content':str(value)}
    return {'schema':'2.0','config':{'update_multi':True,'width_mode':'default','summary':{'content':title}},
        'header':{'title':text(title),'subtitle':text('申请单号：'+str(number)),'template':'blue'},
        'body':{'direction':'vertical','padding':'12px','vertical_spacing':'12px','elements':[
            {'tag':'div','text':text('您的物料申请发货日期已调整。')},
            {'tag':'column_set','flex_mode':'none','columns':[
                {'tag':'column','width':'weighted','weight':1,'elements':[{'tag':'div','text':text('原发货日期：'+str(previous_date or '未设置'))}]},
                {'tag':'column','width':'weighted','weight':1,'elements':[{'tag':'div','text':text('新发货日期：'+str(new_date or '未设置'))}]}]},
            {'tag':'div','text':text('发货状态：'+('已发货' if shipped else '未发货'))},
            {'tag':'button','text':text('查看申请单（只读）'),'type':'primary_filled','width':'fill','behaviors':[{'type':'open_url','default_url':url}]}]}}
