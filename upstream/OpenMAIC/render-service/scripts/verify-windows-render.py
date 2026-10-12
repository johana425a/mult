"""Deterministic, self-authored renderer acceptance fixture. NOT model generation."""
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
import zipfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_runtime as runtime


def main():
    runtime.prepare()
    if not runtime.health():
        raise RuntimeError('Start renderer before acceptance fixture')
    out = ROOT / 'reports' / 'render-fixture'
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / 'project'
    assets = fixture / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    wav = assets / 'narration.wav'
    speech = "This is a local rendering test. The lesson slide and audio are self authored. This is not AI generated."
    powershell = "Add-Type -AssemblyName System.Speech; $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speaker.Rate = 1; $speaker.SetOutputToWaveFile('" + str(wav).replace("'", "''") + "'); $speaker.Speak('" + speech + "'); $speaker.Dispose()"
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', powershell], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    with wave.open(str(wav)) as audio:
        audio_seconds = audio.getnframes() / audio.getframerate()
    duration = math.ceil(audio_seconds + 1)
    gsap = ROOT / 'upstream' / 'OpenMAIC' / 'node_modules' / '.pnpm' / 'gsap@3.15.0' / 'node_modules' / 'gsap' / 'dist' / 'gsap.min.js'
    if not gsap.exists():
        raise RuntimeError('Official GSAP dependency is not installed yet')
    shutil.copy2(gsap, assets / 'gsap.min.js')
    html = '''<!doctype html><html><head><meta charset="UTF-8"><title>Self-authored renderer check</title>
<style>*{box-sizing:border-box}body{margin:0;background:#101b35;color:white;font-family:Arial,sans-serif}.badge{color:#83e5c3;letter-spacing:3px;font-size:22px}h1{font-size:48px;margin:28px 0}p{font-size:26px;line-height:1.6}.card{position:absolute;left:64px;right:64px;top:55px}.track{height:18px;background:#263b5f;border-radius:10px;margin-top:45px;overflow:hidden}#progress{width:0;height:100%;background:#83e5c3}.label{font-size:18px;color:#abc0df}#second{opacity:0;color:#83e5c3}</style></head>
<body><div id="fixture" data-composition-id="fixture" data-start="0" data-duration="DURATION" data-width="1280" data-height="720" style="width:1280px;height:720px;position:relative;overflow:hidden">
<div class="card"><div class="badge">LOCAL VIDEO ENGINE CHECK</div><h1>From a lesson slide to an MP4</h1><p>Original slide + Windows local narration<br>Chromium frame capture + FFmpeg encoding</p><p id="second">Video and audio are now rendered together.</p><div class="track"><div id="progress"></div></div><p class="label">Deterministic self-authored fixture. Not an AI-generated lesson.</p></div>
<audio id="voice" class="clip" data-start="0" data-duration="AUDIO_DURATION" data-track-index="2" data-volume="1" src="assets/narration.wav"></audio></div>
<script src="assets/gsap.min.js"></script><script>var tl=gsap.timeline({paused:true});tl.to('#progress',{width:'100%',duration:DURATION,ease:'none'},0);tl.to('#second',{opacity:1,duration:0.3},DURATION/2);tl.set({}, {}, DURATION);window.__timelines={fixture:tl};</script></body></html>'''.replace('AUDIO_DURATION', str(audio_seconds)).replace('DURATION', str(duration))
    (fixture / 'index.html').write_text(html, encoding='utf-8')
    (fixture / 'README.txt').write_text('Original deterministic renderer fixture, not AI generation. Narration generated locally with Windows System.Speech. GSAP is the project dependency with its original license header. No cloud model or TTS calls.', encoding='utf-8')
    archive = out / 'render-fixture.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for path in fixture.rglob('*'):
            if path.is_file():
                zipf.write(path, path.relative_to(fixture).as_posix())
    boundary = '----EduAgent' + uuid.uuid4().hex
    body = bytearray()
    for name, value in [('fps', '12'), ('quality', 'draft'), ('format', 'mp4')]:
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="project"; filename="render-fixture.zip"\r\nContent-Type: application/zip\r\n\r\n'.encode())
    body.extend(archive.read_bytes())
    body.extend(f'\r\n--{boundary}--\r\n'.encode())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(runtime.BASE + '/render', data=body, headers={'Content-Type': f'multipart/form-data; boundary={boundary}', 'x-openmaic-client': 'local-renderer-acceptance'})
    start = time.monotonic()
    with opener.open(request, timeout=60) as response:
        submitted = json.load(response)
    job_id = submitted['jobId']
    print(json.dumps({'job_id': job_id, 'duration_seconds': duration}), flush=True)
    runtime.dump(out / 'submitted.json', {'jobId': job_id, 'submitted': submitted, 'fixture_seconds': duration, 'ai_generated': False})
    deadline = time.monotonic() + 600
    last_status = None
    while time.monotonic() < deadline:
        with opener.open(runtime.BASE + '/render/' + job_id, timeout=10) as response:
            state = json.load(response)
        observed = (state.get('status'), state.get('progress'))
        if observed != last_status:
            print(json.dumps({'status': observed[0], 'progress': observed[1]}), flush=True)
            last_status = observed
        if state['status'] in ('succeeded', 'failed', 'cancelled'):
            break
        time.sleep(2)
    runtime.dump(out / 'job.json', state)
    if state['status'] != 'succeeded':
        raise RuntimeError('Renderer did not succeed: ' + json.dumps(state))
    video = out / 'render-fixture.mp4'
    with opener.open(runtime.BASE + '/render/' + job_id + '/download', timeout=60) as source, video.open('wb') as target:
        shutil.copyfileobj(source, target)
    ffmpeg = runtime.ffmpeg()
    probe = json.loads(subprocess.check_output([str(ffmpeg.with_name('ffprobe.exe')), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video)], text=True, encoding='utf-8'))
    streams = probe['streams']
    video_stream = next(s for s in streams if s['codec_type'] == 'video')
    audio_stream = next(s for s in streams if s['codec_type'] == 'audio')
    assert video_stream['width'] == 1280 and video_stream['height'] == 720
    assert float(probe['format']['duration']) >= duration - .2
    pcm = subprocess.check_output([str(ffmpeg), '-v', 'error', '-i', str(video), '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'])
    samples = array.array('h', pcm)
    rms = math.sqrt(sum(int(x) ** 2 for x in samples) / len(samples))
    assert rms > 10, 'Audio is silent'
    frames = []
    for number, position in enumerate((1.0, duration - 1.0)):
        frame = out / f'frame-{number + 1}.png'
        subprocess.run([str(ffmpeg), '-v', 'error', '-y', '-ss', str(position), '-i', str(video), '-frames:v', '1', str(frame)], check=True)
        frames.append(str(frame))
    assert hashlib.sha256(Path(frames[0]).read_bytes()).digest() != hashlib.sha256(Path(frames[1]).read_bytes()).digest()
    result = {'passed': True, 'ai_generated': False, 'purpose': 'Real local renderer acceptance, not AI lesson quality', 'job_id': job_id, 'duration_seconds': probe['format']['duration'], 'elapsed_seconds': round(time.monotonic() - start, 2), 'video_codec': video_stream['codec_name'], 'audio_codec': audio_stream['codec_name'], 'audio_rms_s16': round(rms, 2), 'dimensions': [video_stream['width'], video_stream['height']], 'video_path': str(video), 'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest(), 'frames': frames, 'health': runtime.health(), 'job': state}
    runtime.dump(ROOT / 'reports' / 'render-acceptance.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
