"""Order/packing exports styled from the user's approved workbook, without source data."""
from copy import copy
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import fromstring
import json
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font,PatternFill,Border,Alignment,Protection
from openpyxl.worksheet.dimensions import SheetFormatProperties
from openpyxl.worksheet.properties import WorksheetProperties
from openpyxl.worksheet.page import PrintPageSetup,PageMargins
from openpyxl.worksheet.header_footer import HeaderFooter

HEADERS=('类型','物料名称','语种','数量','用途')
TEMPLATE=Path(__file__).resolve().parents[1]/'assets/order_packing/template-style.json'


@lru_cache(maxsize=1)
def template():
    return json.loads(TEMPLATE.read_text(encoding='utf-8'))


def template_sha256():
    return template()['source_sha256']


def workbook(view):
    profile=template();wb=Workbook();wb.remove(wb.active);wb.loaded_theme=profile['theme'].encode()
    classes={'font':Font,'fill':PatternFill,'border':Border,'alignment':Alignment,'protection':Protection}
    styles={key:{**{kind:cls.from_tree(fromstring(item[kind])) for kind,cls in classes.items()},'number_format':item['number_format']} for key,item in profile['styles'].items()}
    def apply(cell,key):
        for kind,value in styles[key].items():setattr(cell,kind,copy(value))
    def row(ws,values,keys):
        for value in values:
            if isinstance(value,str) and (len(value)>32767 or ILLEGAL_CHARACTERS_RE.search(value)):raise ValueError('导出文字过长或含无效字符，请核对用途和备注。')
        ws.append(values);number=ws.max_row
        for cell,key in zip(ws[number],keys):
            apply(cell,key)
            if isinstance(cell.value,str):cell.data_type='s'
        return number
    def sheet(name):
        settings=profile['sheets'][name];ws=wb.create_sheet(name)
        for col,width in settings['column_widths'].items():ws.column_dimensions[col].width=width
        for key,cls in [('sheet_format',SheetFormatProperties),('sheet_properties',WorksheetProperties),('page_setup',PrintPageSetup),('page_margins',PageMargins),('header_footer',HeaderFooter)]:
            setattr(ws,'HeaderFooter' if key=='header_footer' else key,cls.from_tree(fromstring(settings[key])))
        ws.freeze_panes=settings['freeze_panes'];ws.sheet_view.showGridLines=settings['gridlines'];ws.sheet_view.zoomScale=settings['zoom_scale']
        row(ws,HEADERS,settings['header_styles'])
        if settings['header_height'] is not None:ws.row_dimensions[1].height=settings['header_height']
        return ws,settings
    orders,settings=sheet('下单表')
    for item in view['orders']:
        # The reference uses single-line purpose summaries, separated with +.
        row(orders,[item[k].replace('\n',' + ') if isinstance(item[k],str) else item[k] for k in ['category','model','language','quantity','usage']],settings['body_styles'])
    packing,settings=sheet('分装表')
    for index,group in enumerate(view['packing']):
        if index:
            for _ in range(2 if index==1 else 1):row(packing,[None]*5,settings['separator_styles'])
        start=None;keys=settings['group_styles'][index%len(settings['group_styles'])]
        for i,item in enumerate(group['rows']):
            model=item['model']+('（制作备注：'+item['remark']+'）' if item.get('remark') else '')
            number=row(packing,[item['category'],model,item['language'],item['quantity'],group['label'] if i==0 else None],keys)
            if start is None:start=number
        if start is not None and packing.max_row>start:packing.merge_cells(start_row=start,end_row=packing.max_row,start_column=5,end_column=5)
    output=BytesIO();wb.save(output);return output.getvalue()
