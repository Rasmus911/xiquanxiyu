"""Real OOXML fixtures exercise parsing and bounded hostile input rejection."""
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET
import pytest


def rewrite(raw, name, transform):
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
        for row in source.infolist():
            target.writestr(row.filename, transform(source.read(row.filename)) if row.filename == name else source.read(row.filename))
    return output.getvalue()


def module():
    from app import inventory_xlsx
    return inventory_xlsx


def source():
    return [dict(name='奶膏', stock_quantity='800.000', package_cost='120.00', id='fixture-stock',
                 version=3, mapping_token='token'),
            dict(name='=名字不是公式', stock_quantity='0.000', package_cost=None, id='second', version=1)]


def test_roundtrip_keeps_numeric_zero_blank_cost_and_hidden_identity():
    api = module(); raw = api.export_inventory_xlsx(source())
    rows = api.parse_inventory_xlsx(raw)
    assert rows[0]['name'] == '奶膏' and rows[0]['quantity'] == '800.000'
    assert rows[0]['package_cost'] == '120.00'
    assert rows[0]['stock_item_id'] == 'fixture-stock' and rows[0]['source_version'] == '3'
    assert rows[1]['name'] == '=名字不是公式' and rows[1]['quantity'] == '0.000'
    assert rows[1]['package_cost'] == ''
    with ZipFile(BytesIO(raw)) as archive:
        sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        assert sheet.find('s:cols/s:col[@min="4"]', ns).get('hidden') == '1'
        assert sheet.find('.//s:c[@r="A4"]', ns).get('t') == 'inlineStr'


def test_formulas_are_rejected_even_with_cached_values():
    api = module(); raw = api.export_inventory_xlsx(source())
    unsafe = rewrite(raw, 'xl/worksheets/sheet1.xml', lambda data: data.replace(b'<v>800.000</v>', b'<f>1+1</f><v>800.000</v>'))
    with pytest.raises(ValueError, match='公式'): api.parse_inventory_xlsx(unsafe)


def test_external_relationship_is_not_followed():
    api = module(); raw = api.export_inventory_xlsx(source())
    unsafe = rewrite(raw, 'xl/_rels/workbook.xml.rels', lambda data: data.replace(b'Target="worksheets/sheet1.xml"',
        b'TargetMode="External" Target="https://example.invalid/stock.xml"'))
    with pytest.raises(ValueError, match='外部'): api.parse_inventory_xlsx(unsafe)


def test_entities_and_unsafe_zip_paths_are_rejected():
    api = module(); raw = api.export_inventory_xlsx(source())
    unsafe = rewrite(raw, 'xl/worksheets/sheet1.xml', lambda data: b'<!DOCTYPE worksheet [<!ENTITY a "boom">]>' + data)
    with pytest.raises(ValueError): api.parse_inventory_xlsx(unsafe)
    output = BytesIO()
    with ZipFile(output, 'w') as target:
        target.writestr('../private.xml', 'cannot extract')
    with pytest.raises(ValueError): api.parse_inventory_xlsx(output.getvalue())


def test_excess_rows_and_invalid_zip_fail_before_use():
    api = module()
    with pytest.raises(ValueError): api.export_inventory_xlsx(source() * 501)
    with pytest.raises(ValueError): api.parse_inventory_xlsx(b'not Excel')


def test_shared_strings_from_excel_are_supported():
    api = module(); raw = api.export_inventory_xlsx(source())
    raw = rewrite(raw, 'xl/worksheets/sheet1.xml', lambda data: data.replace(
        '<c r="A3" t="inlineStr"><is><t>奶膏</t></is></c>'.encode(), b'<c r="A3" t="s"><v>0</v></c>'))
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as before, ZipFile(output, 'w', ZIP_DEFLATED) as after:
        for info in before.infolist(): after.writestr(info.filename, before.read(info.filename))
        after.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>奶膏</t></si></sst>')
    assert api.parse_inventory_xlsx(output.getvalue())[0]['name'] == '奶膏'


def test_numeric_excel_dates_cannot_silently_become_stock_balances():
    api = module(); raw = api.export_inventory_xlsx(source())
    unsafe = rewrite(raw,'xl/styles.xml',lambda data:data.replace(b'numFmtId="164" formatCode="0.###"',b'numFmtId="164" formatCode="yyyy/mm/dd"'))
    with pytest.raises(ValueError,match='日期'):api.parse_inventory_xlsx(unsafe)
