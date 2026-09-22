import base64
import csv
import io
import textwrap
import zipfile
from html import escape
from pathlib import Path


def encode_file(path: Path, content: str, encoding: str = 'utf-8') -> bytes:
    """Encode content as the type selected by the filename extension."""
    if encoding == 'base64':
        try:
            return base64.b64decode(content, validate=True)
        except ValueError as exc:
            raise ValueError('content is not valid base64 data.') from exc
    encoders = {'.pdf': _pdf, '.doc': _doc, '.docx': _docx, '.xls': _xls}
    encoders.update({'.xlsx': _xlsx, '.ppt': _ppt, '.pptx': _pptx})
    selected = encoders.get(path.suffix.lower())
    return selected(content) if selected else content.encode('utf-8')


def _zip(parts: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value.encode('utf-8'))
    return output.getvalue()


def _docx(content: str) -> bytes:
    body = ''.join(f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>' for line in (content.splitlines() or ['']))
    return _zip({
        '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml': f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}<w:sectPr/></w:body></w:document>'})


def _table(content: str) -> list[list[str]]:
    try:
        rows = list(csv.reader(io.StringIO(content)))
    except csv.Error:
        rows = []
    return rows or [[line] for line in content.splitlines()] or [['']]


def _column(index: int) -> str:
    value = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _xlsx(content: str) -> bytes:
    rows = []
    for row_number, values in enumerate(_table(content), 1):
        cells = ''.join(f'<c r="{_column(index)}{row_number}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>' for index, value in enumerate(values, 1))
        rows.append(f'<row r="{row_number}">{cells}</row>')
    return _zip({
        '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': f'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(rows)}</sheetData></worksheet>'})


def _slides(content: str) -> list[list[str]]:
    sections = [part.strip() for part in content.replace('\r\n', '\n').split('\n\n') if part.strip()]
    return [section.splitlines() for section in sections] or [['Presentation']]


def _pptx(content: str) -> bytes:
    slides = _slides(content)
    overrides = ''.join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, len(slides) + 1))
    ids = ''.join(f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, len(slides) + 1))
    rels = ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>' for i in range(1, len(slides) + 1))
    parts = {
        '[Content_Types].xml': f'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>{overrides}</Types>',
        '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>',
        'ppt/presentation.xml': f'<?xml version="1.0"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst>{ids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>',
        'ppt/_rels/presentation.xml.rels': f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>'}
    for index, lines in enumerate(slides, 1):
        runs = ''.join(f'<a:p><a:r><a:t>{escape(line)}</a:t></a:r></a:p>' for line in lines)
        parts[f'ppt/slides/slide{index}.xml'] = (
            '<?xml version="1.0"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Content"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            '<p:spPr><a:xfrm><a:off x="685800" y="685800"/><a:ext cx="10820400" cy="5486400"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/>{runs}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
    return _zip(parts)


def _pdf(content: str) -> bytes:
    lines = []
    for line in content.splitlines() or ['']:
        lines.extend(textwrap.wrap(line, 90) or [''])
    pages = [lines[i:i + 48] for i in range(0, len(lines), 48)] or [['']]
    objects = [b'', b'<< /Type /Catalog /Pages 2 0 R >>']
    page_ids = [4 + index * 2 for index in range(len(pages))]
    kids = ' '.join(f'{item} 0 R' for item in page_ids)
    objects += [f'<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>'.encode(),
                b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for index, page in enumerate(pages):
        page_id, stream_id = page_ids[index], page_ids[index] + 1
        commands = ['BT /F1 11 Tf 50 790 Td 14 TL']
        for line in page:
            safe = line.encode('cp1252', 'replace').decode('latin1')
            safe = safe.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'({safe}) Tj T*')
        commands.append('ET')
        stream = '\n'.join(commands).encode('latin1')
        while len(objects) <= stream_id:
            objects.append(b'')
        objects[page_id] = f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>'.encode()
        objects[stream_id] = f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream'
    output = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for index, obj in enumerate(objects[1:], 1):
        offsets.append(len(output))
        output.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(output)
    output.extend(f'xref\n0 {len(objects)}\n0000000000 65535 f \n'.encode())
    output.extend(b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:]))
    output.extend(f'trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(output)


def _doc(content: str) -> bytes:
    output = []
    for char in content:
        if char in '\\{}':
            output.append('\\' + char)
        elif char == '\n':
            output.append('\\par\n')
        elif ord(char) > 127:
            value = ord(char)
            output.append(f'\\u{value if value < 32768 else value - 65536}?')
        else:
            output.append(char)
    return ('{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Calibri;}}\\fs22 ' + ''.join(output) + '}').encode('ascii')


def _xls(content: str) -> bytes:
    rows = ''.join('<Row>' + ''.join(f'<Cell><Data ss:Type="String">{escape(value)}</Data></Cell>' for value in row) + '</Row>' for row in _table(content))
    return f'<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Sheet1"><Table>{rows}</Table></Worksheet></Workbook>'.encode()


def _ppt(content: str) -> bytes:
    slides = ''.join(f'<section><h1>{escape(lines[0])}</h1>{"".join(f"<p>{escape(line)}</p>" for line in lines[1:])}</section>' for lines in _slides(content))
    return f'<html xmlns:o="urn:schemas-microsoft-com:office:office"><head><meta charset="utf-8"><meta name="ProgId" content="PowerPoint.Slide"></head><body>{slides}</body></html>'.encode()
