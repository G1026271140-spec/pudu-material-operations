"""Two printable supplier sheets using the approved existing five-column format."""
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Alignment,Border,Font,PatternFill,Side
from openpyxl.utils import get_column_letter
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
import math,unicodedata

HEADERS=('类型','物料名称','语种','数量','用途')


def workbook(view):
    wb=Workbook();wb.remove(wb.active)
    edge=Side(style='thin',color='B8CDD6')
    def sheet(name,widths):
        ws=wb.create_sheet(name);ws.append(HEADERS);ws.freeze_panes='A2';ws.sheet_view.showGridLines=False
        for i,width in enumerate(widths,1):ws.column_dimensions[get_column_letter(i)].width=width
        for cell in ws[1]:cell.font=Font(name='微软雅黑',size=11,bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17647A');cell.alignment=Alignment(vertical='center')
        ws.row_dimensions[1].height=28;ws.print_title_rows='1:1';ws.sheet_properties.pageSetUpPr.fitToPage=True
        ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A4;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
        ws.oddFooter.center.text='第 &P 页 / 共 &N 页';return ws
    def row(ws,data,fill=False):
        for value in data:
            if isinstance(value,str) and (len(value)>32767 or ILLEGAL_CHARACTERS_RE.search(value)):raise ValueError('导出文字过长或含无效字符，请核对用途和备注。')
        ws.append(data);number=ws.max_row
        for cell in ws[number]:
            if isinstance(cell.value,str):
                if len(cell.value)>32767 or ILLEGAL_CHARACTERS_RE.search(cell.value):raise ValueError('导出文字过长或含无效字符，请核对用途和备注。')
                cell.data_type='s'
            cell.font=Font(name='微软雅黑',size=10);cell.border=Border(left=edge,right=edge,top=edge,bottom=edge)
            cell.alignment=Alignment(vertical='center',wrap_text=True,horizontal='right' if cell.column==4 else 'left')
            if fill:cell.fill=PatternFill('solid',fgColor='EFF6F8')
        lines=max((sum(max(1,math.ceil(sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in segment)/(ws.column_dimensions[get_column_letter(i)].width-2))) for segment in str(v).split('\n')) for i,v in enumerate(data,1) if v is not None),default=1)
        ws.row_dimensions[number].height=min(409,max(25,13*(lines+1)));ws.cell(number,4).number_format='#,##0'
    orders=sheet('下单表',[22,22,25,12,78])
    for i,item in enumerate(view['orders']):row(orders,[item[k] for k in ['category','model','language','quantity','usage']],i%2==1)
    packing=sheet('分装表',[22,22,25,12,65])
    for index,group in enumerate(view['packing']):
        if index:packing.append([])
        start=None
        for i,item in enumerate(group['rows']):
            label=group['label']
            model=item['model']+('\n制作备注：'+item['remark'] if item.get('remark') else '')
            row(packing,[item['category'],model,item['language'],item['quantity'],label if i==0 else ''],index%2==1)
            if start is None:start=packing.max_row
        if start is not None and packing.max_row>start:packing.merge_cells(start_row=start,end_row=packing.max_row,start_column=5,end_column=5)
    output=BytesIO();wb.save(output);return output.getvalue()
