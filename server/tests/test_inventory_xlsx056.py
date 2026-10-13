from io import BytesIO
from zipfile import ZipFile
from datetime import date
import xml.etree.ElementTree as ET
from app.inventory_xlsx import export_inventory_xlsx, parse_inventory_xlsx, NS

def test_export_uses_dated_template_and_large_cost_header_without_losing_hidden_matching():
    rows=[dict(name='奶膏',package_cost='120.00',stock_quantity='800.000',id='stock-1',version=3,mapping_token='signed-token')]
    raw=export_inventory_xlsx(rows)
    with ZipFile(BytesIO(raw)) as archive:
        sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        cells={cell.get('r'):cell for cell in sheet.findall(f'.//{{{NS}}}c')}
        assert ''.join(cells['A1'].itertext()).startswith('库存清点日期：')
        assert ''.join(cells['B2'].itertext())=='包装成本（元）/最大单位'
        assert cells['B3'].get('t','n')=='n'
        assert cells['C3'].findtext(f'{{{NS}}}v')=='800'
        assert sheet.find(f'{{{NS}}}cols/{{{NS}}}col[@min="4"]').get('hidden')=='1'
    parsed=parse_inventory_xlsx(raw)
    assert parsed[0]['package_cost']=='120.00'
    assert parsed[0]['quantity']=='800'
    assert parsed[0]['stock_item_id']=='stock-1' and parsed[0]['mapping_token']=='signed-token'

def test_fractional_stock_is_not_rounded_by_export_and_cost_remains_decimal():
    raw=export_inventory_xlsx([dict(name='液体',package_cost='0.60',stock_quantity='1.250')])
    parsed=parse_inventory_xlsx(raw)
    assert parsed[0]['quantity']=='1.25'
    assert parsed[0]['package_cost']=='0.60'
