"""Launch only competition services, never the user's personal learning app."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import python_executable
from offline_tokenizer import configure_tokenizer_cache
from storage_paths import select_storage
from installation_identity import command_in_install

ROOT = Path(__file__).resolve().parents[1]
PYTHON = python_executable('portal')
STORAGE = select_storage(ROOT)
STATE = STORAGE.process_root / 'portal-process.json'
LOG = STORAGE.logs / 'portal.log'
URL = 'http://127.0.0.1:3791'
EXPECTED_PORTS = {3791, 3792, 3793, 3794, 8011}
STARTUP_TIMEOUT = 180
SERVICE_PORTS = {'portal': 3791, 'deeptutor_ui': 3792, 'openmaic': 3793,
                 'renderer': 3794, 'harness': 3796,
                 'deeptutor_api': 8011}


def harness_installed():
    """An installed helper makes the sidecar a required service, not a demo."""
    return (ROOT / 'scripts' / 'harness_runtime.py').is_file()


def http_ready(url, timeout=3):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def harness_ready(timeout=3):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:3796/health', timeout=timeout) as response:
            body = json.load(response)
            return response.status == 200 and body.get('healthy') is True
    except Exception:
        return False


def startup_ready(result):
    """A recorded process or an empty service dictionary is not readiness."""
    services = result.get('services', {}).get('services', {})
    # Model credentials are optional at launch. Connecting a provider is a
    # user operation, never a prerequisite for opening the desktop application.
    required = ('deeptutor', 'openmaic')
    if not result.get('healthy') or not all(services.get(name, {}).get('ok') is True for name in required):
        return False
    listeners = result.get('listeners', [])
    if any(item.get('host') not in ('127.0.0.1', '::1') for item in listeners):
        return False
    expected_ports = EXPECTED_PORTS | ({3796} if harness_installed() else set())
    if not expected_ports.issubset({item.get('port') for item in listeners}):
        return False
    auxiliary = result.get('auxiliary_http', {})
    return (auxiliary.get('deeptutor_ui') is True and auxiliary.get('renderer') is True
            and (not harness_installed() or auxiliary.get('harness') is True))


def environment():
    env = os.environ.copy()
    for key in list(env):
        if key.endswith('_API_KEY') or key in {'OPENAI_BASE_URL', 'ANTHROPIC_AUTH_TOKEN'}:
            env.pop(key, None)
    env.update(PYTHONPATH=str(ROOT), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    env.update(STORAGE.child_environment())
    env['EDUAGENT_DATA'] = str(STORAGE.data)
    return env


def status(timeout=3):
    import psutil
    result = {'url': URL, 'healthy': False, 'listeners': []}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + '/api/status', timeout=min(6, timeout)) as response:
            result['healthy'] = response.status == 200
            result['services'] = json.load(response)
    except Exception:
        pass
    result['auxiliary_http'] = {
        'deeptutor_ui': http_ready('http://127.0.0.1:3792/chat', timeout),
        'renderer': http_ready('http://127.0.0.1:3794/health', timeout),
    }
    if harness_installed():
        result['auxiliary_http']['harness'] = harness_ready(timeout)
    for conn in psutil.net_connections(kind='inet'):
        if conn.status == 'LISTEN' and conn.laddr.port in EXPECTED_PORTS | {3796}:
            result['listeners'].append({'host': conn.laddr.ip, 'port': conn.laddr.port, 'pid': conn.pid})
    if any(r['host'] not in ('127.0.0.1', '::1') for r in result['listeners']):
        raise RuntimeError('Competition service is unexpectedly exposed outside loopback')
    return result


def recorded_processes():
    """Read only launch records; never accept an unrelated listener as ours."""
    import psutil
    render = ROOT / 'runtime' / 'render-service'
    if not (render / 'src' / 'main.ts').is_file():
        render = ROOT / 'upstream' / 'OpenMAIC' / 'render-service'
    records = [(STATE, {None: 3791}),
               (STORAGE.process_root / 'deeptutor-processes.json', {'frontend': 3792, 'backend': 8011}),
               (STORAGE.process_root / 'openmaic-process.json', {None: 3793}),
               (STORAGE.render_local(render) / 'process.json', {None: 3794})]
    if harness_installed():
        records.append((STORAGE.process_root / 'harness-state' / 'runtime.json', {None: 3796}))
    owned, stopped = {}, set()
    for filename, ports in records:
        try:
            value = json.loads(filename.read_text('utf-8'))
            entries = value.get('processes', [value])
        except (OSError, ValueError, AttributeError):
            continue
        for entry in entries:
            port = ports.get(entry.get('name')) if isinstance(entry, dict) else None
            if port is None:
                continue
            try:
                process = psutil.Process(entry['pid'])
                if (abs(process.create_time() - entry['created']) >= 0.5
                        or not command_in_install(process.cmdline(), ROOT)):
                    continue
                if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                    stopped.add(port)
                    continue
                pids = {process.pid}
                # Renderer uses a Node launcher whose child owns the listener.
                for child in process.children(recursive=True):
                    try:
                        if command_in_install(child.cmdline(), ROOT):
                            pids.add(child.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        # A short-lived child is not proof its parent died.
                        continue
                owned[port] = pids
            except psutil.NoSuchProcess:
                stopped.add(port)
            except (KeyError, TypeError, ValueError, psutil.AccessDenied):
                continue
    return owned, stopped


def missing_services(result, owned):
    """Safe diagnostic names and ports, without logs, credentials or lessons."""
    required = dict(SERVICE_PORTS)
    if not harness_installed():
        required.pop('harness')
    listeners = result.get('listeners', [])
    services = result.get('services', {}).get('services', {})
    auxiliary = result.get('auxiliary_http', {})
    missing = []
    for name, port in required.items():
        listening = any(item.get('port') == port and item.get('pid') in owned.get(port, set())
                        and item.get('host') in ('127.0.0.1', '::1') for item in listeners)
        healthy = (result.get('healthy') is True if name == 'portal' else
                   services.get('deeptutor', {}).get('ok') is True if name == 'deeptutor_api' else
                   auxiliary.get(name) is True if name in ('deeptutor_ui', 'renderer', 'harness') else
                   services.get(name, {}).get('ok') is True)
        if not listening or not healthy:
            missing.append({'service': name, 'port': port})
    return missing


def wait_for_startup(timeout=STARTUP_TIMEOUT, cancelled=None):
    """Wait for actual readiness; this loop never launches or replaces a process."""
    deadline = time.monotonic() + timeout
    last = {}
    missing = [{'service': name, 'port': port} for name, port in SERVICE_PORTS.items()
               if name != 'harness' or harness_installed()]
    while True:
        if cancelled is not None and cancelled():
            return {'ready': False, 'reason': 'cancelled', 'missing': missing}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {'ready': False, 'reason': 'timeout', 'missing': missing}
        # Four bounded local probes together fit within the remaining budget.
        last = status(timeout=min(3, max(.001, remaining / 4)))
        owned, stopped = recorded_processes()
        missing = missing_services(last, owned)
        if cancelled is not None and cancelled():
            return {'ready': False, 'reason': 'cancelled', 'missing': missing}
        unowned = any(item.get('pid') not in owned.get(item.get('port'), set())
                      for item in last.get('listeners', []))
        if unowned:
            return {'ready': False, 'reason': 'unverified_listener', 'missing': missing}
        if startup_ready(last) and not missing:
            return {'ready': True, 'reason': 'ready', 'missing': []}
        if stopped & {item['port'] for item in missing}:
            return {'ready': False, 'reason': 'service_exited', 'missing': missing}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {'ready': False, 'reason': 'timeout', 'missing': missing}
        time.sleep(min(.5, remaining))


def start_portal():
    configure_tokenizer_cache(ROOT)
    import psutil
    if STATE.exists():
        item = json.loads(STATE.read_text('utf-8'))
        try:
            process = psutil.Process(item['pid'])
            if (abs(process.create_time() - item['created']) < 1
                    and command_in_install(process.cmdline(), ROOT)):
                return status()
        except psutil.NoSuchProcess:
            pass
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 3791)) == 0:
            raise RuntimeError('Port 3791 occupied by another process; refusing to replace it')
    STORAGE.prepare(LOG.parent, STATE.parent, STORAGE.data, STORAGE.temporary)
    env = environment()
    # Embedded Python intentionally ignores PYTHONPATH; insert this install's
    # application root in code rather than relying on the developer shell.
    launch_code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
                   'import uvicorn; uvicorn.run("portal.app:app", host="127.0.0.1", '
                   'port=3791, access_log=False, proxy_headers=False)')
    with LOG.open('ab') as output:
        proc = subprocess.Popen([str(PYTHON), '-I', '-B', '-c', launch_code], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    STATE.write_text(json.dumps({'pid': proc.pid, 'created': psutil.Process(proc.pid).create_time()}), 'utf-8')
    for _ in range(25):
        if proc.poll() is not None:
            raise RuntimeError('Portal startup failed; inspect logs/portal.log')
        time.sleep(0.5)
        result = status()
        if result['healthy']:
            return result
    raise RuntimeError('Portal has not become ready; its owned process remains recorded')


def stop_portal():
    import psutil
    if not STATE.exists():
        return
    item = json.loads(STATE.read_text('utf-8'))
    try:
        process = psutil.Process(item['pid'])
        if (abs(process.create_time() - item['created']) >= 1
                or not command_in_install(process.cmdline(), ROOT)):
            raise RuntimeError('Process ID reused; no process was stopped')
        children = process.children(recursive=True)
        for proc in [*children, process]:
            proc.terminate()
        _, alive = psutil.wait_procs([*children, process], timeout=10)
        for proc in alive:
            proc.kill()
    except psutil.NoSuchProcess:
        pass
    STATE.unlink(missing_ok=True)


def _timing(service, phase, started, origin, exit_code=None):
    """Only bounded, public stage identifiers and monotonic durations."""
    return {'service': service, 'phase': phase,
            'started_after_seconds': round(max(0, started - origin), 3),
            'elapsed_seconds': round(max(0, time.monotonic() - started), 3),
            'exit_code': exit_code}


def _write_startup_timings(timings):
    """Diagnostics must never make a successful start fail or expose payloads."""
    try:
        STORAGE.logs.mkdir(parents=True, exist_ok=True)
        with (STORAGE.logs / 'startup-timings.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps({'timings': timings}, ensure_ascii=True) + '\n')
    except Exception:
        pass


def _start_upstream_service(filename, cancelled, origin):
    started = time.monotonic()
    result = {'service': filename}
    try:
        if cancelled is not None and cancelled():
            result.update(status='cancelled', exit_code=130)
        else:
            script = ROOT / 'scripts' / filename
            if not script.exists():
                result['status'] = 'not_installed'
            else:
                interpreter = python_executable('deeptutor') if filename == 'deeptutor_runtime.py' else PYTHON
                # Keep each launcher's existing load/probe timeouts and process
                # records. Killing only this wrapper on an outer timeout could
                # orphan a model or lose a launch record during its write.
                child = subprocess.run([str(interpreter), '-I', '-B', str(script), 'start'], cwd=ROOT,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, check=False)
                result['exit_code'] = child.returncode
    except KeyboardInterrupt:
        result.update(status='cancelled', exit_code=130)
    except Exception:
        # An OS error can contain paths, arguments or private environment data.
        # Keep a machine-readable failure without copying its raw message.
        result.update(status='launcher_failed', exit_code=None)
    result['timing'] = _timing(filename, 'launch', started, origin, result.get('exit_code'))
    return result


def upstream(action, cancelled=None, timings=None, origin=None):
    order = ['deeptutor_runtime.py', 'openmaic_runtime.py', 'render_runtime.py']
    if harness_installed():
        order.insert(0, 'harness_runtime.py')
    if action == 'stop':
        order.reverse()
    if action == 'start':
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        origin = time.monotonic() if origin is None else origin
        # Independent runtimes load together. The context manager always joins
        # every submitted worker, even on cancellation or a failed launcher, so
        # no delayed spawn can occur after this function has returned.
        interrupted = False
        with ThreadPoolExecutor(max_workers=len(order), thread_name_prefix='deepsteam-start') as executor:
            futures = [executor.submit(_start_upstream_service, filename, cancelled, origin)
                       for filename in order]
            try:
                for future in futures:
                    future.result()
            except KeyboardInterrupt:
                # Join inside the executor context first, then retain every
                # completed launcher's diagnostics before propagating Ctrl-C.
                interrupted = True
        results = [future.result() for future in futures]
        if timings is not None:
            timings.extend(result['timing'] for result in results)
        if interrupted or any(result.get('status') == 'cancelled' for result in results):
            raise KeyboardInterrupt
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        return results
    results = []
    for filename in order:
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        script = ROOT / 'scripts' / filename
        if not script.exists():
            results.append({'service': filename, 'status': 'not_installed'})
            continue
        interpreter = python_executable('deeptutor') if filename == 'deeptutor_runtime.py' else PYTHON
        child = subprocess.run([str(interpreter), '-I', '-B', str(script), action], cwd=ROOT,
                               stdin=subprocess.DEVNULL, check=False)
        results.append({'service': filename, 'exit_code': child.returncode})
    return results


def start_services(timeout=STARTUP_TIMEOUT, cancelled=None):
    origin = time.monotonic()
    timings = []
    exit_code = 1
    try:
        results = upstream('start', cancelled, timings=timings, origin=origin)
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        started = time.monotonic()
        portal_exit_code = 1
        try:
            start_portal()
            portal_exit_code = 0
        except RuntimeError:
            # Its recorded process may still be initializing after the old fixed
            # window. Wait without a second launch; strict ownership checks below
            # distinguish that case from another program occupying the port.
            pass
        finally:
            timings.append(_timing('portal', 'launch', started, origin, portal_exit_code))
        started = time.monotonic()
        try:
            readiness = wait_for_startup(timeout, cancelled)
            exit_code = 0 if readiness['ready'] else 130 if readiness['reason'] == 'cancelled' else 1
        finally:
            timings.append(_timing('all_services', 'readiness', started, origin, exit_code))
        return {'services': results, 'startup': readiness, 'timings': timings}
    except KeyboardInterrupt:
        exit_code = 130
        raise
    finally:
        timings.append(_timing('all_services', 'total', origin, origin, exit_code))
        _write_startup_timings(timings)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status', 'start-portal', 'stop-portal'])
    action = parser.parse_args(argv).action
    if action == 'start':
        try:
            report = start_services()
        except KeyboardInterrupt:
            report = {'startup': {'ready': False, 'reason': 'cancelled'}}
            print(json.dumps(report, ensure_ascii=False))
            return 130
        except Exception:
            # Do not repeat raw child/log errors that can include secrets.
            print(json.dumps({'startup': {'ready': False, 'reason': 'startup_check_failed'}}, ensure_ascii=False))
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['startup']['ready'] else 130 if report['startup']['reason'] == 'cancelled' else 1
    elif action == 'stop':
        stop_portal()
        print(json.dumps(upstream('stop'), ensure_ascii=False, indent=2))
    elif action == 'start-portal':
        portal = start_portal()
        print(json.dumps(portal, ensure_ascii=False, indent=2))
        if not portal.get('healthy'):
            return 1
    elif action == 'stop-portal':
        stop_portal()
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
