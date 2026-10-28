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
