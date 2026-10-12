"""Pre-authored sample made with coding assistance; not live model generation."""
import base64
import html
import time


def text_element(key, text, x, y, width, height, size=26, color='#183d35'):
    return {'type': 'text', 'id': key, 'left': x, 'top': y, 'width': width, 'height': height, 'rotate': 0, 'defaultFontName': 'Microsoft YaHei', 'defaultColor': color, 'content': f'<p style="font-size:{size}px;color:{color};">{html.escape(text)}</p>'}


def payload():
    stamp = int(time.time() * 1000)
    sid = 'authored-demo'
    stage = {'id': sid, 'name': 'Conditional probability · Prepared demo', 'description': 'An open prepared example created with Codex assistance to check classroom playback and interaction. It is not a live model generation result.', 'createdAt': stamp, 'updatedAt': stamp, 'languageDirective': 'Use English', 'agentIds': []}
    diagram = '''<svg xmlns="http://www.w3.org/2000/svg" width="840" height="230" viewBox="0 0 840 230">
      <rect width="840" height="230" rx="18" fill="#f2f5ed"/>
      <g font-family="Microsoft YaHei,sans-serif" font-size="22" text-anchor="middle" fill="#183d35">
      <text x="190" y="43">100 club members</text><text x="625" y="43">Given: photography</text>
      <rect x="65" y="67" width="250" height="90" rx="12" fill="#d3e5db"/>
      <text x="190" y="106">40 know Python</text><text x="190" y="139">P(Python) = 40/100</text>
      <path d="M350 110h130m-20-15 20 15-20 15" fill="none" stroke="#bc9147" stroke-width="5"/>
      <rect x="500" y="67" width="250" height="90" rx="12" fill="#d3e5db"/>
      <text x="625" y="106" font-size="16">30 photographers; 18 know Python</text><text x="625" y="139" font-size="18">P(Python | Photography) = 18/30</text>
      <text x="420" y="204" font-size="20">New information changes the comparison group; the denominator matches the condition.</text></g></svg>'''
    diagram_uri = 'data:image/svg+xml;base64,' + base64.b64encode(diagram.encode()).decode()
    def slide(key, title, order, elements):
        elements.append(text_element(key + '-notice', 'Prepared example · Created with Codex assistance · Not live model generation', 45, 520, 910, 30, 16, '#747c6e'))
        return {'id': key, 'stageId': sid, 'title': title, 'order': order, 'type': 'slide', 'actions': [], 'content': {'type': 'slide', 'schemaVersion': 1, 'canvas': {'id': key + '-canvas', 'viewportSize': 1000, 'viewportRatio': 0.5625, 'background': {'type': 'solid', 'color': '#fafbf7'}, 'theme': {'backgroundColor': '#fafbf7', 'themeColors': ['#1f6551', '#bc9147'], 'fontColor': '#183d35', 'fontName': 'Microsoft YaHei'}, 'elements': elements}}}
    scenes = [slide('demo-range', 'How new information changes the comparison group', 0, [
        text_element('title-1', 'Conditional probability: identify your comparison group', 45, 38, 910, 70, 38),
        text_element('intro-1', 'Of 100 people, 40 know Python, 30 know photography, and 18 know both.', 45, 125, 910, 90, 25),
        {'id': 'source-figure', 'type': 'image', 'left': 80, 'top': 225, 'width': 840, 'height': 230, 'rotate': 0, 'fixedRatio': True, 'src': diagram_uri},
    ]), slide('demo-reverse', 'Why the condition and conclusion cannot be swapped', 1, [
        text_element('title-2', 'The same 18 people, different denominators', 45, 38, 910, 70, 38),
        text_element('formula-1', 'Given photography: 18 / 30 = 0.60', 65, 165, 870, 80, 36),
        text_element('formula-2', 'Given Python: 18 / 40 = 0.45', 65, 270, 870, 80, 36),
        text_element('reason', 'Ask first: what is given, and how many people meet that condition?', 65, 405, 870, 70, 26),
    ]), {'id': 'demo-quiz', 'stageId': sid, 'title': 'Check your choice of denominator', 'order': 2, 'type': 'quiz', 'actions': [], 'content': {'type': 'quiz', 'questions': [{'id': 'denominator-check', 'type': 'single', 'question': 'Given that this person does not know Python, what is the probability they know photography? (Prepared example)', 'options': [{'value': 'A', 'label': '12/100'}, {'value': 'B', 'label': '12/60'}, {'value': 'C', 'label': '18/30'}, {'value': 'D', 'label': '30/100'}], 'answer': ['B'], 'analysis': 'There are 60 people who do not know Python; 12 know photography. The conditional probability is 12/60 = 0.2.', 'hasAnswer': True, 'points': 1}]}}]
    return stage, scenes
