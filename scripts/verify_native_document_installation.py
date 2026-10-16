"""Acceptance of installed native ingestion using only synthetic local sources.

Run with the installation's runtime/python/python.exe -I -B. This script
never imports developer checkout code, reads account settings or calls models.
Its unique JSON report stays beside synthetic fixtures under installation tmp.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

INSTALL = Path(__file__).resolve().parents[1]


def main() -> int:
    python = INSTALL / 'runtime/python/python.exe'
    if Path(sys.executable).resolve() != python.resolve() or not INSTALL.is_dir():
        raise SystemExit('Use this installation\'s packaged Python with -I -B.')
    root = Path(tempfile.mkdtemp(prefix='native-document-installed-', dir=INSTALL / 'runtime'))
    os.environ.update(DEEPTUTOR_HOME=str(root / 'home'), DEEPTUTOR_WORKSPACE_ROOT=str(root / 'content'),
                      PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0, str(INSTALL))
    overlay = INSTALL / 'runtime/deeptutor-packages'
    if overlay.is_dir():
        sys.path.insert(0, str(overlay))
    import deeptutor.reading.extract as reading
    from deeptutor.services.parsing.engines.text_only import engine
    from deeptutor.services.parsing.service import ParseService
    from integration import shared_document_extraction as shared

    code_paths = {name: str(Path(module.__file__).resolve()) for name, module in (
        ('reading', reading), ('parser', engine), ('shared', shared))}
    for location in code_paths.values():
        Path(location).relative_to(INSTALL)
    assert shared.ROOT.resolve() == INSTALL.resolve(), 'Shared runtime root is not the installation.'

    from PIL import Image, ImageDraw, ImageFont
    from docx import Document
    from docx.oxml import parse_xml
    import pymupdf

    image = Image.new('RGB', (1300, 420), 'white')
    ImageDraw.Draw(image).text((45, 90), 'LOCAL SCAN EVIDENCE 12345',
                              font=ImageFont.load_default(size=56), fill='black')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    picture = buffer.getvalue()
    scan = root / 'synthetic-scan.pdf'
    pdf = pymupdf.open()
    pdf.new_page(width=720, height=320).insert_image(pymupdf.Rect(0, 0, 720, 320), stream=picture)
    pdf.save(scan)
    pdf.close()
    word = root / 'synthetic-equation.docx'
    document = Document()
    paragraph = document.add_paragraph('Synthetic equation ')
    paragraph._p.append(parse_xml('<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:f><m:num><m:r><m:t>x</m:t></m:r></m:num><m:den><m:r><m:t>y</m:t></m:r></m:den></m:f></m:oMath>'))
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = 'table left', 'table right'
    document.add_paragraph('Synthetic picture evidence').add_run().add_picture(io.BytesIO(picture))
    document.save(word)

    results = []
    report = {'kind': 'installed-native-document-acceptance', 'fixtures_only': True,
              'models_called': 0, 'parser_network_required': False, 'code_paths': code_paths,
              'created_at': datetime.now(timezone.utc).isoformat(), 'results': results, 'passed': False}
    try:
        assert engine.TextOnlyParser().is_ready({}).ready, 'Bundled components not ready.'
        service = ParseService(cache_root=root / 'parse-cache')
        for source in (scan, word):
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            extracted = reading.extract_material(source)
            parsed = service.parse(source, engine='text_only')
            text = '\n'.join(extracted.units)
            assert '12345' in text and '12345' in parsed.markdown
            assert extracted.media, 'Reading media missing.'
            assert parsed.asset_dir and list(parsed.asset_dir.glob('*.png')), 'Parser source images missing.'
            if source.suffix == '.pdf':
                assert extracted.unit == 'page' and extracted.render_mode == 'pdf'
                assert parsed.blocks[0]['source_locator']['page'] == 1
            else:
                assert r'\frac{x}{y}' in text and 'table left' in text
                assert any(row.get('equations') for row in parsed.blocks)
                assert any(row.get('table') for row in parsed.blocks)
                assert all('page_idx' not in row for row in parsed.blocks)
            assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, 'Original changed.'
            results.append({'source': source.name, 'passed': True, 'unit_count': len(extracted.units),
                            'reading_images': len(extracted.media), 'parser_blocks': len(parsed.blocks),
                            'source_sha256': digest, 'physical_pages_only_for_pdf': True})
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
    report_path = root / 'acceptance.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'report': str(report_path)}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
