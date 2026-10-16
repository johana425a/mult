"""Pre-authored sample made with coding assistance; not live model generation."""
import base64
import html
import time


def text_element(key, text, x, y, width, height, size=26, color='#183d35'):
    return {'type': 'text', 'id': key, 'left': x, 'top': y, 'width': width, 'height': height, 'rotate': 0, 'defaultFontName': 'Microsoft YaHei', 'defaultColor': color, 'content': f'<p style="font-size:{size}px;color:{color};">{html.escape(text)}</p>'}


def payload():
    stamp = int(time.time() * 1000)
    sid = 'authored-demo'
    stage = {'id': sid, 'name': '条件概率 · 预编写演示课', 'description': '由 Codex 辅助预编写的开放示例，用于检查课件播放与交互，不代表实时模型生成效果。', 'createdAt': stamp, 'updatedAt': stamp, 'languageDirective': '使用简体中文', 'agentIds': []}
    diagram = '''<svg xmlns="http://www.w3.org/2000/svg" width="840" height="230" viewBox="0 0 840 230">
      <rect width="840" height="230" rx="18" fill="#f2f5ed"/>
      <g font-family="Microsoft YaHei,sans-serif" font-size="22" text-anchor="middle" fill="#183d35">
      <text x="190" y="43">100 名社团成员</text><text x="625" y="43">已知：会摄影</text>
      <rect x="65" y="67" width="250" height="90" rx="12" fill="#d3e5db"/>
      <text x="190" y="106">40 人会 Python</text><text x="190" y="139">P(Python) = 40/100</text>
      <path d="M350 110h130m-20-15 20 15-20 15" fill="none" stroke="#bc9147" stroke-width="5"/>
      <rect x="500" y="67" width="250" height="90" rx="12" fill="#d3e5db"/>
      <text x="625" y="106" font-size="16">摄影组 30 人，18 人会 Python</text><text x="625" y="139" font-size="18">P(Python | 摄影) = 18/30</text>
      <text x="420" y="204" font-size="20">新信息改变比较范围；分母对应已知条件。</text></g></svg>'''
    diagram_uri = 'data:image/svg+xml;base64,' + base64.b64encode(diagram.encode()).decode()
    def slide(key, title, order, elements):
        elements.append(text_element(key + '-notice', '预编写示例 · Codex 辅助制作 · 非实时模型生成', 45, 520, 910, 30, 16, '#747c6e'))
        return {'id': key, 'stageId': sid, 'title': title, 'order': order, 'type': 'slide', 'actions': [], 'content': {'type': 'slide', 'schemaVersion': 1, 'canvas': {'id': key + '-canvas', 'viewportSize': 1000, 'viewportRatio': 0.5625, 'background': {'type': 'solid', 'color': '#fafbf7'}, 'theme': {'backgroundColor': '#fafbf7', 'themeColors': ['#1f6551', '#bc9147'], 'fontColor': '#183d35', 'fontName': 'Microsoft YaHei'}, 'elements': elements}}}
    scenes = [slide('demo-range', '新信息怎样改变比较范围', 0, [
        text_element('title-1', '条件概率：先确定你站在哪个范围里', 45, 38, 910, 70, 38),
        text_element('intro-1', '100 人中，40 人会 Python，30 人会摄影，18 人两者都会。', 45, 125, 910, 90, 25),
        {'id': 'source-figure', 'type': 'image', 'left': 80, 'top': 225, 'width': 840, 'height': 230, 'rotate': 0, 'fixedRatio': True, 'src': diagram_uri},
    ]), slide('demo-reverse', '条件和结论为什么不能互换', 1, [
        text_element('title-2', '同样的 18 人，分母却不同', 45, 38, 910, 70, 38),
        text_element('formula-1', '已知会摄影：18 ÷ 30 = 0.60', 65, 165, 870, 80, 36),
        text_element('formula-2', '已知会 Python：18 ÷ 40 = 0.45', 65, 270, 870, 80, 36),
        text_element('reason', '每次先问：现在已知什么？符合条件的共有多少人？', 65, 405, 870, 70, 26),
    ]), {'id': 'demo-quiz', 'stageId': sid, 'title': '检查你是否会选择分母', 'order': 2, 'type': 'quiz', 'actions': [], 'content': {'type': 'quiz', 'questions': [{'id': 'denominator-check', 'type': 'single', 'question': '已知这个人不会 Python，他会摄影的概率是多少？（预编写示例题）', 'options': [{'value': 'A', 'label': '12/100'}, {'value': 'B', 'label': '12/60'}, {'value': 'C', 'label': '18/30'}, {'value': 'D', 'label': '30/100'}], 'answer': ['B'], 'analysis': '不会 Python 的人共 60 人，其中 12 人会摄影，所以条件概率为 12/60=0.2。', 'hasAnswer': True, 'points': 1}]}}]
    return stage, scenes
