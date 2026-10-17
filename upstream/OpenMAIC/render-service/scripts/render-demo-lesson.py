"""Render the original probability lesson through native OpenMAIC compiler/MP4 APIs."""
from __future__ import annotations
import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
import wave

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'portal'))
import render_runtime as runtime
from demo_classroom import payload


def main():
    out = ROOT / 'reports' / 'demo-native-export'
    out.mkdir(parents=True, exist_ok=True)
    stage, scenes = payload()
    # The source's self-authored labeling stays on the two native slide scenes.
    texts = [
        '一百名成员中，四十人会编程，三十人会摄影，十八人两者都会。已知会摄影，就只看三十人，所以概率是十八除以三十，等于百分之六十。',
        '已知会编程，分母则变成四十，结果是百分之四十五。条件改变，比较范围就改变。',
        '请暂停思考：已知不会编程，他会摄影的概率是多少？分母是谁？',
    ]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    audios, frames = {}, {}
    for index, (scene, text) in enumerate(zip(scenes, texts)):
        action_id = 'original-narration-' + str(index + 1)
        audio = out / (action_id + '.wav')
        escaped = text.replace("'", "''")
        ps = "Add-Type -AssemblyName System.Speech; $voice=New-Object System.Speech.Synthesis.SpeechSynthesizer; $voice.SelectVoice('Microsoft Huihui Desktop'); $voice.Rate=2; $voice.SetOutputToWaveFile('" + str(audio).replace("'", "''") + "'); $voice.Speak('" + escaped + "'); $voice.Dispose()"
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ps], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        with wave.open(str(audio)) as w:
            duration = w.getnframes() / w.getframerate() * 1000
        scene['actions'] = [{'id': action_id, 'type': 'speech', 'text': text, 'audioId': action_id}]
        audios[action_id] = {'path': str(audio), 'durationMs': duration, 'voice': 'Microsoft Huihui Desktop', 'local': True}
        if scene['type'] == 'slide':
            req = {'version': 1, 'stage': stage, 'scene': scene, 'viewport': {'width': 1280, 'height': 720, 'deviceScaleFactor': 1}}
            request = urllib.request.Request(runtime.BASE + '/preview', data=json.dumps(req, ensure_ascii=False).encode(), headers={'Content-Type': 'application/json', 'x-openmaic-client': 'local-authored-demo'})
            frame = out / (scene['id'] + '.png')
            with opener.open(request, timeout=45) as response:
                frame.write_bytes(response.read())
            frames[scene['id']] = str(frame)
            print(json.dumps({'snapshot': scene['id'], 'audio_ms': duration}), flush=True)
    runtime.dump(out / 'input.json', {'stage': stage, 'scenes': scenes, 'audio': audios, 'frames': frames})
    app = ROOT / 'upstream' / 'OpenMAIC'
    subprocess.run([str(runtime.NODE), str(runtime.SERVICE / 'node_modules' / 'tsx' / 'dist' / 'cli.mjs'), '--tsconfig', str(Path(__file__).with_name('native-export-tsconfig.json')), str(Path(__file__).with_name('build-demo-native-export.ts'))], cwd=app, check=True)
    archive = out / 'native-project.zip'
    boundary = '----EduAgent' + uuid.uuid4().hex
    body = bytearray()
    for name, value in [('fps', '24'), ('quality', 'standard'), ('format', 'mp4')]:
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="project"; filename="native-project.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode())
    body.extend(archive.read_bytes())
    body.extend(f'\r\n--{boundary}--\r\n'.encode())
    req = urllib.request.Request(runtime.BASE + '/render', data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}', 'x-openmaic-client': 'local-authored-demo'})
    start = time.monotonic()
    with opener.open(req, timeout=60) as response:
        submitted = json.load(response)
    job_id = submitted['jobId']
    runtime.dump(out / 'submission.json', submitted)
    print(json.dumps(submitted), flush=True)
    deadline = time.monotonic() + 600
    last = None
    while time.monotonic() < deadline:
        with opener.open(runtime.BASE + '/render/' + job_id, timeout=10) as response:
            state = json.load(response)
        status = (state.get('status'), state.get('progress'))
        if status != last:
            print(json.dumps({'status': status[0], 'progress': status[1]}), flush=True)
            last = status
        if state['status'] in ('succeeded', 'failed', 'cancelled'):
            break
        time.sleep(3)
    runtime.dump(out / 'job.json', state)
    if state['status'] != 'succeeded':
        raise RuntimeError(json.dumps(state))
    video = ROOT / 'reports' / 'demo-lesson-video.mp4'
    with opener.open(runtime.BASE + '/render/' + job_id + '/download', timeout=60) as source, video.open('wb') as target:
        shutil.copyfileobj(source, target)
    ffmpeg = runtime.ffmpeg()
    probe = json.loads(subprocess.check_output([str(ffmpeg.with_name('ffprobe.exe')), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video)], text=True, encoding='utf-8'))
    video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio_stream = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    pcm = subprocess.check_output([str(ffmpeg), '-v', 'error', '-i', str(video), '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'])
    samples = array.array('h', pcm)
    rms = math.sqrt(sum(int(x) ** 2 for x in samples) / len(samples))
    assert rms > 10
    timeline = json.loads((out / 'timeline.json').read_text(encoding='utf-8'))
    rendered_frames = []
    for index, scene in enumerate(timeline['scenes']):
        position = (scene['startMs'] + scene['durationMs'] * .5) / 1000
        frame = out / f'video-scene-{index+1}.png'
        subprocess.run([str(ffmpeg), '-v', 'error', '-y', '-ss', str(position), '-i', str(video), '-frames:v', '1', str(frame)], check=True)
        rendered_frames.append(str(frame))
    report = {'passed': True, 'content_type': 'Original authored educational sample, not a live AI generation result', 'source': str(ROOT / 'demo' / '条件概率与信息更新.md'), 'speech': 'Windows local Microsoft Huihui Desktop, rate 2; no cloud TTS', 'native_pipeline': ['OpenMAIC preview slide snapshots', 'compileVideoTimeline', 'emitHyperframes', 'packageVideoZip', 'POST /render', 'GET /render/id/download'], 'not_tested': ['browser store collection', 'UI one-click export', 'live AI generation'], 'seconds': probe['format']['duration'], 'video_codec': video_stream['codec_name'], 'audio_codec': audio_stream['codec_name'], 'dimensions': [video_stream['width'], video_stream['height']], 'audio_rms_s16': rms, 'elapsed_seconds': round(time.monotonic()-start, 2), 'sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'path': str(video), 'frames': rendered_frames, 'job': state}
    report['quiz_video_mode'] = 'Native quiz cover with narrated question and subtitles; interactive choices/answer remain in the classroom'
    report['compiler_diagnostics'] = timeline.get('diagnostics', [])
    report['source_sha256'] = hashlib.sha256((ROOT / 'demo' / '条件概率与信息更新.md').read_bytes()).hexdigest()
    report['scene_input_sha256'] = hashlib.sha256((out / 'input.json').read_bytes()).hexdigest()
    native_report_path = out / 'native-export-report.json'
    native_report = json.loads(native_report_path.read_text(encoding='utf-8'))
    native_report['pipeline'][-1] = 'POST /render succeeded; MP4 downloaded and probed'
    native_report['render_job_id'] = job_id
    native_report['render_passed'] = True
    runtime.dump(native_report_path, native_report)
    runtime.dump(ROOT / 'reports' / 'render-demo-lesson.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
