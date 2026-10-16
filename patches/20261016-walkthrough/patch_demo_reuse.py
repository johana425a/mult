"""DeepSteam 2026-10-16: 打开示例课堂 reuses the existing demo lesson (it was renamed to Chinese)."""
import sys, pathlib
p = pathlib.Path(sys.argv[1]) / 'portal' / 'app.py'; s = p.read_text(encoding='utf-8')
old = """    for existing in store.list('lessons'):
        if existing['title'] == 'Conditional probability · Prepared demo' and existing['status'] == 'ready':"""
new = """    # DeepSteam 2026-10-16 demo reuse: the demo was renamed to Chinese; match both names.
    demo_titles = {payload()[0]['name'], 'Conditional probability · Prepared demo'}
    for existing in store.list('lessons'):
        if existing['title'] in demo_titles and existing['status'] == 'ready':"""
if 'DeepSteam 2026-10-16 demo reuse' in s:
    print('app.py already patched')
else:
    assert s.count(old) == 1, 'demo anchor not found (file changed?)'
    p.write_text(s.replace(old, new), encoding='utf-8', newline=''); print('app.py patched')
