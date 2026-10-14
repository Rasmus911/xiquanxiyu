"""Bounded, value-only inventory OOXML. No macros, formulas or external fetches.

The Microsoft SpreadsheetML cell/shared-string contracts are used directly;
no new package or network installation is needed on the small production ECS.
"""
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import PurePosixPath
import posixpath
import re
import stat
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

MAX_FILE = 10 * 1024**2
MAX_EXPANDED = 50 * 1024**2
MAX_XML = 12 * 1024**2
MAX_ROWS = 1000
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
HEADERS = ['商品名', '包装成本（元）/最大单位', '现存基本单位数量', '库存项目ID', '记录版本', '匹配校验码']
ALIASES = {'商品名': 'name', '商品名称': 'name', '包装成本（元）': 'package_cost', '成本': 'package_cost',
           '包装成本（元）/最大单位': 'package_cost',
           '现存基本单位数量': 'quantity', '数量': 'quantity', '库存项目ID': 'stock_item_id',
           '记录版本': 'source_version', '匹配校验码': 'mapping_token'}


def _text(value):
    text = str(value)
    if len(text) > 1000 or any(ord(c) < 32 and c not in '\t\n\r' for c in text):
        raise ValueError('Excel 单元格文字过长或包含无效字符')
    return escape(text)


def export_inventory_xlsx(rows):
    rows = list(rows)
    if len(rows) > MAX_ROWS:
        raise ValueError('一次最多导出1000项库存')
    def cell(address, value, numeric=False, style=''):
        if value is None or value == '': return ''
        if numeric:
            return f'<c r="{address}" s="{style or "1"}"><v>{_text(value)}</v></c>'
        return f'<c r="{address}" t="inlineStr"><is><t>{_text(value)}</t></is></c>'
    today = datetime.now(ZoneInfo('Asia/Shanghai'))
    title = f'库存清点日期：{today.year}年{today.month}月{today.day}日'
    data = ['<row r="1" ht="30" customHeight="1">' + cell('A1', title) + '</row>',
            '<row r="2">' + ''.join(cell(f'{chr(65+i)}2', value) for i, value in enumerate(HEADERS)) + '</row>']
    for number, row in enumerate(rows, 3):
        quantity = format(Decimal(str(row['stock_quantity'])), 'f')
        if '.' in quantity: quantity = quantity.rstrip('0').rstrip('.')
        values = [row['name'], row.get('package_cost'), quantity, row.get('id', ''),
                  row.get('version', ''), row.get('mapping_token', '')]
        data.append(f'<row r="{number}">' + ''.join(cell(f'{chr(65+i)}{number}', value,
            numeric=i in (1, 2, 4), style='2' if i == 1 else '1') for i, value in enumerate(values)) + '</row>')
    sheet = f'<worksheet xmlns="{NS}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
    sheet += '<sheetFormatPr defaultRowHeight="24"/><cols><col min="1" max="1" width="36" customWidth="1"/><col min="2" max="3" width="24" customWidth="1"/><col min="4" max="6" width="18" hidden="1" customWidth="1"/></cols>'
    sheet += '<sheetData>' + ''.join(data) + f'</sheetData><autoFilter ref="A2:F{len(rows)+2}"/><mergeCells count="1"><mergeCell ref="A1:C1"/></mergeCells></worksheet>'
    parts = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + REL + '/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{NS}" xmlns:r="{REL}"><sheets><sheet name="库存" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + REL + '/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="' + REL + '/styles" Target="styles.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': sheet,
        'xl/styles.xml': f'<styleSheet xmlns="{NS}"><numFmts count="2"><numFmt numFmtId="164" formatCode="0.###"/><numFmt numFmtId="165" formatCode="0.00"/></numFmts><fonts count="1"><font><sz val="12"/><name val="Microsoft YaHei"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
    }
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for name, value in parts.items(): archive.writestr(name, value.encode('utf-8'))
    return output.getvalue()


def _xml(data):
    if (len(data) > MAX_XML or b'\x00' in data or data.count(b'<') > 50000 or
            b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper()):
        raise ValueError('Excel XML过大、过于复杂或包含不安全实体')
    try: return ET.fromstring(data)
    except ET.ParseError: raise ValueError('Excel XML损坏') from None


def _safe_name(name):
    return bool(name and not name.startswith('/') and '\\' not in name and ':' not in name and
                '..' not in PurePosixPath(name).parts and name.rstrip('/') == posixpath.normpath(name))


def parse_inventory_xlsx(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_FILE:
        raise ValueError('Excel文件不得超过10MiB')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist()
            if (len(members) > 256 or len({v.filename for v in members}) != len(members) or
                    sum(v.file_size for v in members) > MAX_EXPANDED or any(
                        not _safe_name(v.filename) or v.flag_bits & 1 or
                        v.compress_type not in {ZIP_DEFLATED, ZIP_STORED} or
                        stat.S_ISLNK(v.external_attr >> 16) for v in members)):
                raise ValueError('Excel压缩内容过大或包含不安全路径')
            names = {v.filename for v in members}
            if any('vbaproject' in name.lower() or 'externallinks/' in name.lower() for name in names):
                raise ValueError('Excel不得包含宏或外部链接')
            xmls = {}
            for info in members:
                if info.filename.endswith(('.xml', '.rels')):
                    if info.file_size > MAX_XML: raise ValueError('Excel XML过大')
                    # Read one extra byte so inaccurate size metadata cannot bypass a bound.
                    with archive.open(info) as stream: data = stream.read(MAX_XML + 1)
                    root = _xml(data)
                    if info.filename.endswith('.rels') and any(
                            row.get('TargetMode', '').lower() == 'external' for row in root):
                        raise ValueError('Excel不得包含外部链接')
                    xmls[info.filename] = root
            workbook = xmls.get('xl/workbook.xml')
            relationships = xmls.get('xl/_rels/workbook.xml.rels')
            if workbook is None or relationships is None: raise ValueError('Excel工作簿结构不完整')
            sheets = workbook.findall(f'{{{NS}}}sheets/{{{NS}}}sheet')
            visible = [row for row in sheets if row.get('state', 'visible') == 'visible']
            if not visible: raise ValueError('没有可导入的库存工作表')
            chosen = next((row for row in visible if row.get('name') == '库存'), visible[0])
            targets = {row.get('Id'): row.get('Target', '') for row in relationships
                       if row.get('Type', '').endswith('/worksheet')}
            target = targets.get(chosen.get(f'{{{REL}}}id'), '')
            path = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            if not _safe_name(path) or path not in xmls: raise ValueError('库存工作表关系无效')
            for other in targets.values():
                other_path = other.lstrip('/') if other.startswith('/') else posixpath.normpath('xl/' + other)
                other_root = xmls.get(other_path)
                if other_path != path and other_root is not None and other_root.find(f'.//{{{NS}}}c') is not None:
                    raise ValueError('请保留一张库存数据工作表，避免忽略其他表中的库存')
            shared_root = xmls.get('xl/sharedStrings.xml')
            shared = [''.join(row.itertext()) for row in shared_root] if shared_root is not None else []
            if len(shared) > 10000 or any(len(v) > 1000 for v in shared): raise ValueError('Excel共享文字过大')
            styles = xmls.get('xl/styles.xml')
            custom_formats = {row.get('numFmtId'): row.get('formatCode', '') for row in
                styles.findall(f'{{{NS}}}numFmts/{{{NS}}}numFmt')} if styles is not None else {}
            date_styles = set()
            for index, style in enumerate(styles.findall(f'{{{NS}}}cellXfs/{{{NS}}}xf') if styles is not None else []):
                format_id = style.get('numFmtId','0')
                if not re.fullmatch('[0-9]{1,5}', format_id): raise ValueError('Excel数字格式无效')
                fmt = re.sub(r'"[^"]*"|\\.', '', custom_formats.get(format_id,''))
                fmt = re.sub(r'\[(?![hms]+\])[^]]*\]', '', fmt, flags=re.I)
                if int(format_id) in {*range(14,23),*range(27,37),*range(45,48),*range(50,59)} or re.search('[ymdhs]',fmt,re.I):
                    date_styles.add(str(index))
            parsed, seen_rows = [], set()
            for row in xmls[path].findall(f'{{{NS}}}sheetData/{{{NS}}}row'):
                if len(parsed) > MAX_ROWS + 12: raise ValueError('Excel最多导入1000条业务行')
                number = row.get('r', '')
                if not re.fullmatch('[1-9][0-9]{0,5}', number) or number in seen_rows:
                    raise ValueError('Excel行号无效或重复')
                seen_rows.add(number)
                cells = {}
                for cell in row.findall(f'{{{NS}}}c'):
                    address = cell.get('r', '')
                    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,5})', address)
                    if not match or match[2] != number or match[1] in cells:
                        raise ValueError('Excel单元格位置无效或重复')
                    if cell.find(f'{{{NS}}}f') is not None: raise ValueError('请将公式转换为数值后导入')
                    kind = cell.get('t', 'n')
                    if kind == 'n' and cell.get('s','0') in date_styles:
                        raise ValueError('Excel日期或时间不能作为库存数量或成本，请改为数字')
                    value = cell.findtext(f'{{{NS}}}v', default='')
                    if kind == 'inlineStr': value = ''.join(cell.find(f'{{{NS}}}is').itertext())
                    elif kind == 's':
                        if not re.fullmatch('[0-9]{1,5}', value) or int(value) >= len(shared):
                            raise ValueError('共享文字编号无效')
                        value = shared[int(value)]
                    elif kind not in {'n', 'str'}: raise ValueError('Excel不能使用日期、布尔或错误值作为库存字段')
                    if len(value) > 1000: raise ValueError('Excel单元格过长')
                    cells[match[1]] = value.strip()
                if any(cells.values()): parsed.append((int(number), cells))
            header = None
            for index, (_, cells) in enumerate(parsed[:10]):
                candidate = {column: ALIASES[value] for column, value in cells.items() if value in ALIASES}
                if {'name', 'package_cost', 'quantity'} <= set(candidate.values()):
                    if len(candidate.values()) != len(set(candidate.values())) or any(
                            value and column not in candidate for column, value in cells.items()):
                        raise ValueError('Excel列名重复或包含不支持的字段')
                    header = candidate; data = parsed[index + 1:]; break
            if header is None: raise ValueError('需要商品名、包装成本（元）、现存基本单位数量三列')
            if not 1 <= len(data) <= MAX_ROWS: raise ValueError('Excel须包含1至1000条库存记录')
            result = []
            for number, cells in data:
                if any(value and column not in header for column, value in cells.items()):
                    raise ValueError(f'第{number}行包含多余字段')
                values = {key: cells.get(column, '') for column, key in header.items()}
                result.append(dict(name=values.get('name', ''), package_cost=values.get('package_cost', ''),
                    quantity=values.get('quantity', ''), stock_item_id=values.get('stock_item_id', ''),
                    source_version=values.get('source_version', ''), mapping_token=values.get('mapping_token', ''), row_number=number))
            return result
    except (BadZipFile, KeyError, RuntimeError, TypeError, AttributeError, NotImplementedError):
        raise ValueError('文件不是有效的xlsx库存表，或工作表结构损坏') from None
