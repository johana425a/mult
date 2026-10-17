"""Bounded formula-only use of the bundled MinerU ONNX components.

Original DeepSteam integration. Upstream models/code retain their own licenses.
No model downloads, whole-document OCR, desktop control, or network inference.
The parent kills this private process at its deadline; partial crops survive.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
VERSION = 3


def number_has_formula(number_box, formulas, page_height):
    """A right-hand equation number belongs beside/below, not above, its math."""
    y = (number_box['bbox'][1] + number_box['bbox'][3]) / 2
    return any(item['label'] == 'display_formula' and
               -.02 * page_height <= y - (item['bbox'][1] + item['bbox'][3]) / 2 < .10 * page_height
               for item in formulas)


def main():
    request = json.load(sys.stdin)
    output = Path(request['output_dir']).resolve(strict=True)
    if not output.is_dir() or output.is_symlink():
        raise ValueError('A private formula output directory is required')
    from mineru_document_worker import configure_home, safe_asset
    configure_home(output / 'worker-home')
    # Lower CPU contention while the user is working in other applications.
    os.environ['OMP_NUM_THREADS'] = '2'
    from PIL import Image
    import numpy as np
    from mineru.model.layout.pp_doclayout_v2_onnx import PPDocLayoutV2LayoutModelONNX
    from mineru.model.mfr.pp_formulanet_plus_m_onnx import PPFormulaNetPlusMONNX

    start = time.monotonic()
    deadline = start + float(request.get('seconds', 30))
    models = ROOT / 'models/mineru/MinerU-4_models_onnx'
    layout = PPDocLayoutV2LayoutModelONNX(
        str(models / 'Layout/PP-DocLayoutV2/inference.onnx'), intra_op_num_threads=2)
    report = {'version': VERSION, 'engine': 'mineru', 'engine_version': importlib.metadata.version('mineru'),
              'backend': 'PP-DocLayoutV2 + PP-FormulaNet-Plus-M ONNX CPU',
              'local_vlm_used': False, 'pages': [], 'candidates': [], 'completed': False}
    pdf = None
    if request.get('source_pdf'):
        # The parent verifies the imported copy and its document hash before
        # passing it. Original PDF pixels are sharper than enlarging a preview.
        import pypdfium2
        pdf = pypdfium2.PdfDocument(request['source_pdf'])

    def save():
        report['elapsed_seconds'] = round(time.monotonic() - start, 3)
        temp = output / 'local-result.tmp'
        temp.write_text(json.dumps(report, ensure_ascii=False), 'utf-8')
        os.replace(temp, output / 'local-result.json')

    save()
    for entry in request['pages']:
        if time.monotonic() >= deadline:
            break
        path = Path(entry['path']).resolve(strict=True)
        # Inputs are prepared by the parent within this private cache entry.
        path.relative_to(output)
        with Image.open(path) as original:
            original = original.convert('RGB')
            boxes = layout.predict(original)
            width, height = original.size
            selected = [box for box in boxes if box['label'] == 'display_formula' or
                        (box['label'] == 'inline_formula' and
                         ((box['bbox'][2] - box['bbox'][0]) / width > .16 or
                          (box['bbox'][3] - box['bbox'][1]) / height > .035))]
            # A number without a nearby displayed equation is a source gap,
            # not permission to reconstruct a known textbook equation.
            for box in boxes:
                if box['label'] != 'formula_number':
                    continue
                if not number_has_formula(box, selected, height):
                    selected.append({**box, 'label': 'orphan_formula_number',
                        'bbox': [max(0, int(width * .10)), max(0, box['bbox'][1] - int(height * .12)),
                                 min(width, box['bbox'][2] + 8), min(height, box['bbox'][3] + 8)]})
            page_row = {'image_index': entry['image_index'], 'locator': entry.get('locator'),
                        'detected_formula_regions': len(selected), 'detection_complete': True}
            report['pages'].append(page_row)
            for box in selected:
                x0, y0, x1, y1 = box['bbox']
                bbox = [max(0, math.floor(x0) - 12), max(0, math.floor(y0) - 12),
                        min(width, math.ceil(x1) + 12), min(height, math.ceil(y1) + 12)]
                name = 'formula-' + str(len(report['candidates']) + 1)
                target = safe_asset(output, name + '.png')
                normalized = [bbox[0] / width, bbox[1] / height, bbox[2] / width, bbox[3] / height]
                crop_origin = 'retained_page_image'
                number = (entry.get('locator') or {}).get('page')
                if pdf is not None and type(number) is int and 1 <= number <= len(pdf):
                    page = pdf[number - 1]
                    try:
                        pw, ph = page.get_size()
                        bitmap = page.render(scale=3, crop=(normalized[0]*pw, (1-normalized[3])*ph,
                                                            (1-normalized[2])*pw, normalized[1]*ph))
                        try:
                            bitmap.to_pil().save(target)
                        finally:
                            bitmap.close()
                        crop_origin = 'original_pdf_216_dpi'
                    finally:
                        page.close()
                else:
                    original.crop(bbox).save(target)
                report['candidates'].append({'id': name, 'image_index': entry['image_index'],
                    'locator': entry.get('locator'), 'bbox': normalized, 'crop_origin': crop_origin,
                    'crop_file': target.name, 'crop_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'detector_label': box['label'], 'detector_score': box['score'],
                    'ocr_latex': None, 'ocr_status': 'pending', 'status': 'source_only'})
            save()
    formula = None
    for candidate in report['candidates']:
        if time.monotonic() >= deadline:
            break
        if candidate['detector_label'] == 'orphan_formula_number':
            candidate['ocr_status'] = 'source_gap'
            save()
            continue
        if formula is None:
            formula = PPFormulaNetPlusMONNX(
                str(models / 'MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M.onnx'),
                str(models / 'MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M_inference.yml'),
                intra_op_num_threads=2)
        with Image.open(output / candidate['crop_file']) as crop:
            # The formula model accepts BGR ndarray; keep the original PNG.
            pixels = np.asarray(crop.convert('RGB'))[:, :, ::-1].copy()
            predictions = formula.predict([{'label': 'display_formula', 'bbox': [0, 0, crop.width, crop.height]}], pixels, batch_size=1)
        candidate['ocr_latex'] = predictions[0].get('latex') if predictions else None
        candidate['ocr_status'] = 'recognized' if candidate['ocr_latex'] else 'empty'
        save()
    report['completed'] = (len(report['pages']) == len(request['pages']) and
                           all(item['ocr_status'] != 'pending' for item in report['candidates']))
    save()
    if pdf is not None:
        pdf.close()


if __name__ == '__main__':
    # -I omits the script's directory from sys.path; add only this install.
    sys.path.insert(0, str(ROOT / 'scripts'))
    main()
