"""Branded banner + localized labels for ``deeptutor start`` / ``deeptutor init``.

Both commands read the user's language preference from
``data/user/settings/interface.json`` (default ``en``) so their startup
output matches the UI language the user has chosen.
"""

from __future__ import annotations
from deeptutor.product_brand import PRODUCT_NAME

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from deeptutor.__version__ import __version__

_ASCII_LOGO = r""" ____                  _____      _
|  _ \  ___  ___ _ __ |_   _|   _| |_ ___  _ __
| | | |/ _ \/ _ \ '_ \  | || | | | __/ _ \| '__|
| |_| |  __/  __/ |_) | | || |_| | || (_) | |
|____/ \___|\___| .__/  |_| \__,_|\__\___/|_|
                |_|"""


LABELS: dict[str, dict[str, str]] = {
    "en": {
        "tagline": "Agent-Native Personalized Tutoring",
        "lab": "Data Intelligence Lab @ HKU",
        # init
        "init.mode": "Workspace initializer",
        "init.workspace": "Workspace",
        "init.note_settings_dir": "Settings will be written under data/user/settings.",
        "init.cancelled": "Setup cancelled. Nothing was saved.",
        "init.step_ports": "Step {n}/{total} · Ports",
        "init.step_llm": "Step {n}/{total} · LLM provider",
        "init.step_embedding": "Step {n}/{total} · Embedding (RAG / Knowledge Base)",
        "init.step_search": "Step {n}/{total} · Web search",
        "init.step_review": "Step {n}/{total} · Review & save",
        "init.backend_port": "Backend port",
        "init.frontend_port": "Frontend port",
        "init.llm_section": "LLM provider",
        "init.pick_provider": "Pick an LLM provider",
        "init.pick_embedding_provider": "Pick an embedding provider",
        "init.show_all": "Show all providers",
        "init.custom_provider": "Custom / Other",
        "init.skip_step": "Skip / configure later",
        "init.back": "Back",
        "init.skipped": "Skipped — you can configure this later in Web Settings.",
        "init.binding": "Binding",
        "init.base_url": "Base URL",
        "init.api_key": "API key",
        "init.api_key_env_detected": "Detected {env_var}={masked} in your environment. Use it?",
        "init.api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.api_key_reuse_llm": "Reuse the LLM API key {masked}?",
        "init.edit_base_url": "Edit Base URL?",
        "init.new_base_url": "New Base URL",
        "init.model": "Model",
        "init.fetch_models": "Fetching available models from {url} ...",
        "init.fetch_models_ok": "Found {count} model(s).",
        "init.fetch_models_fail": "Could not list models ({error}). Using fallback list.",
        "init.pick_model": "Pick a model — or type {marker} to enter your own",
        "init.custom_model": "Custom model name",
        "init.embedding_section": "Embedding provider",
        "init.embedding_endpoint": "Embedding endpoint URL",
        "init.embedding_api_key": "Embedding API key",
        "init.embedding_model": "Embedding model",
        "init.embedding_dimension": "Embedding dimension (blank for auto)",
        "init.search_section": "Web search provider",
        "init.pick_search_provider": "Pick a web-search provider",
        "init.search_api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.search_base_url_prompt": "Base URL",
        "init.search_no_key_note": "{label} does not need an API key.",
        "init.search_disabled_note": "Web search will be disabled. Agents will skip search tools.",
        "init.review_search": "Search",
        "init.review_search_disabled": "disabled",
        "init.probe_offer": "Test connection now?",
        "init.probe_running": "Testing {what} ...",
        "init.probe_ok": "{what} OK  ·  {ms}ms",
        "init.probe_fail": "{what} failed: {error}",
        "init.probe_retry": "Re-enter API key and retry?",
        "init.copilot_reuse_login": "Reuse the GitHub Copilot login for {account}?",
        "init.copilot_login_start": "Starting GitHub device login ...",
        "init.copilot_login_ok": "GitHub Copilot login succeeded for {account}.",
        "init.copilot_login_fail": "GitHub Copilot login failed: {error}",
        "init.review_title": "Review",
        "init.review_llm": "LLM",
        "init.review_embedding": "Embedding",
        "init.review_ports": "Ports",
        "init.review_ports_value": "backend {backend}, frontend {frontend}",
        "init.confirm_save": "Save these settings?",
        "init.saved": "Settings saved. You can edit them later in the Web Settings page or data/user/settings/.",
        "init.next_step": f"Run `deeptutor start` to launch {PRODUCT_NAME}.",
        "init.choice": "Choice",
        "init.choice_invalid": "Invalid choice. Try again.",
        # start (launcher)
        "start.mode": "Launching backend + frontend",
        "start.backend": "Backend",
        "start.browser_api": "Browser API",
        "start.frontend": "Frontend",
        "start.workspace": "Workspace",
        "start.frontend_runtime": "Frontend runtime",
        "start.press_ctrl_c": "Press Ctrl+C to stop.",
        "start.detached_started": f"{PRODUCT_NAME} is starting in the background (launcher PID {{pid}}).",
        "start.detached_already_running": (
            f"A detached {PRODUCT_NAME} launcher is already running (PID {{pid}}). Log: {{log}}"
        ),
        "start.detached_log": "Log: {path}",
        "start.detached_stop_hint": 'Stop it with `deeptutor stop --home "{home}"`.',
        "start.starting_backend": "Starting backend ...",
        "start.starting_frontend": "Starting frontend ...",
        "start.reusing_frontend": "Reusing existing frontend at {url} (PID {pid}).",
        "start.restarting_frontend": (
            "Existing frontend at {url} is not responding; restarting it (PID {pid})."
        ),
        "start.frontend_restart_failed": (
            "Existing frontend at {url} is not responding and could not be stopped automatically. "
            "Stop PID {pid} and run `deeptutor start` again."
        ),
        "start.waiting_for": "Waiting for {name} at {url} ...",
        "start.ready": "{name} is ready.",
        "start.open_in_browser": "Open {url} in your browser.",
        "start.received_signal": "Received {signal}; shutting down ...",
        "start.stopping": "Stopping {name} (PID {pid})",
        "start.exited": "{name} exited with code {code}",
        "stop.not_running": f"No detached {PRODUCT_NAME} launcher is running.",
        "stop.requested": "Requested a graceful stop from launcher PID {pid}.",
        "stop.complete": f"{PRODUCT_NAME} stopped.",
        "stop.timeout": "Launcher PID {pid} did not stop in time. Check {log}.",
        "start.not_ready": (
            "{name} did not become ready within {timeout}s. "
            "Slow hardware or a workspace with data to migrate can need longer; "
            "set {env} to a larger number of seconds."
        ),
        "start.port_in_use": (
            f"{PRODUCT_NAME} cannot start because port(s) already in use: {{ports}}. "
            "Stop the existing process or change data/user/settings/system.json."
        ),
        "start.port_conflict_title": "Port conflict detected:",
        "start.port_conflict_line": "  {role} port {port} is in use by:",
        "start.port_conflict_proc": "    PID {pid} · {command}",
        "start.port_conflict_unknown_proc": "    (process info unavailable)",
        "start.port_option_change": "Change ports (saved to data/user/settings/system.json)",
        "start.port_option_kill": "Stop the occupying process(es) and continue",
        "start.port_invalid": "Invalid port: {value}. Enter a free port between 1 and 65535.",
        "start.port_saved": "Ports saved to {path}.",
        "start.port_killing": "Stopping PID {pid} ({command}) ...",
        "start.port_kill_failed": "Could not free port {port} (PID {pid}).",
        "start.port_freed": "Port {port} released.",
    },
    "zh": {
        "tagline": "Agent-Native Personalized Tutoring",
        "lab": "Data Intelligence Lab @ HKU",
        # init
        "init.mode": "Workspace initializer",
        "init.workspace": "Workspace",
        "init.note_settings_dir": "Settings will be written under data/user/settings.",
        "init.cancelled": "Setup cancelled. Nothing was saved.",
        "init.step_ports": "Step {n}/{total} · Ports",
        "init.step_llm": "Step {n}/{total} · LLM provider",
        "init.step_embedding": "Step {n}/{total} · Embedding (RAG / Knowledge Base)",
        "init.step_search": "Step {n}/{total} · Web search",
        "init.step_review": "Step {n}/{total} · Review & save",
        "init.backend_port": "Backend port",
        "init.frontend_port": "Frontend port",
        "init.llm_section": "LLM provider",
        "init.pick_provider": "Pick an LLM provider",
        "init.pick_embedding_provider": "Pick an embedding provider",
        "init.show_all": "Show all providers",
        "init.custom_provider": "Custom / Other",
        "init.skip_step": "Skip / configure later",
        "init.back": "Back",
        "init.skipped": "Skipped — you can configure this later in Web Settings.",
        "init.binding": "Binding",
        "init.base_url": "Base URL",
        "init.api_key": "API key",
        "init.api_key_env_detected": "Detected {env_var}={masked} in your environment. Use it?",
        "init.api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.api_key_reuse_llm": "Reuse the LLM API key {masked}?",
        "init.edit_base_url": "Edit Base URL?",
        "init.new_base_url": "New Base URL",
        "init.model": "Model",
        "init.fetch_models": "Fetching available models from {url} ...",
        "init.fetch_models_ok": "Found {count} model(s).",
        "init.fetch_models_fail": "Could not list models ({error}). Using fallback list.",
        "init.pick_model": "Pick a model — or type {marker} to enter your own",
        "init.custom_model": "Custom model name",
        "init.embedding_section": "Embedding provider",
        "init.embedding_endpoint": "Embedding endpoint URL",
        "init.embedding_api_key": "Embedding API key",
        "init.embedding_model": "Embedding model",
        "init.embedding_dimension": "Embedding dimension (blank for auto)",
        "init.search_section": "Web search provider",
        "init.pick_search_provider": "Pick a web-search provider",
        "init.search_api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.search_base_url_prompt": "Base URL",
        "init.search_no_key_note": "{label} does not need an API key.",
        "init.search_disabled_note": "Web search will be disabled. Agents will skip search tools.",
        "init.review_search": "Search",
        "init.review_search_disabled": "disabled",
        "init.probe_offer": "Test connection now?",
        "init.probe_running": "Testing {what} ...",
        "init.probe_ok": "{what} OK  ·  {ms}ms",
        "init.probe_fail": "{what} failed: {error}",
        "init.probe_retry": "Re-enter API key and retry?",
        "init.copilot_reuse_login": "Reuse the GitHub Copilot login for {account}?",
        "init.copilot_login_start": "Starting GitHub device login ...",
        "init.copilot_login_ok": "GitHub Copilot login succeeded for {account}.",
        "init.copilot_login_fail": "GitHub Copilot login failed: {error}",
        "init.review_title": "Review",
        "init.review_llm": "LLM",
        "init.review_embedding": "Embedding",
        "init.review_ports": "Ports",
        "init.review_ports_value": "backend {backend}, frontend {frontend}",
        "init.confirm_save": "Save these settings?",
        "init.saved": "Settings saved. You can edit them later in the Web Settings page or data/user/settings/.",
        "init.next_step": f"Run `deeptutor start` to launch {PRODUCT_NAME}.",
        "init.choice": "Choice",
        "init.choice_invalid": "Invalid choice. Try again.",
        # start (launcher)
        "start.mode": "Launching backend + frontend",
        "start.backend": "Backend",
        "start.browser_api": "Browser API",
        "start.frontend": "Frontend",
        "start.workspace": "Workspace",
        "start.frontend_runtime": "Frontend runtime",
        "start.press_ctrl_c": "Press Ctrl+C to stop.",
        "start.detached_started": f"{PRODUCT_NAME} is starting in the background (launcher PID {{pid}}).",
        "start.detached_already_running": (
            f"A detached {PRODUCT_NAME} launcher is already running (PID {{pid}}). Log: {{log}}"
        ),
        "start.detached_log": "Log: {path}",
        "start.detached_stop_hint": 'Stop it with `deeptutor stop --home "{home}"`.',
        "start.starting_backend": "Starting backend ...",
        "start.starting_frontend": "Starting frontend ...",
        "start.reusing_frontend": "Reusing existing frontend at {url} (PID {pid}).",
        "start.restarting_frontend": (
            "Existing frontend at {url} is not responding; restarting it (PID {pid})."
        ),
        "start.frontend_restart_failed": (
            "Existing frontend at {url} is not responding and could not be stopped automatically. "
            "Stop PID {pid} and run `deeptutor start` again."
        ),
        "start.waiting_for": "Waiting for {name} at {url} ...",
        "start.ready": "{name} is ready.",
        "start.open_in_browser": "Open {url} in your browser.",
        "start.received_signal": "Received {signal}; shutting down ...",
        "start.stopping": "Stopping {name} (PID {pid})",
        "start.exited": "{name} exited with code {code}",
        "stop.not_running": f"No detached {PRODUCT_NAME} launcher is running.",
        "stop.requested": "Requested a graceful stop from launcher PID {pid}.",
        "stop.complete": f"{PRODUCT_NAME} stopped.",
        "stop.timeout": "Launcher PID {pid} did not stop in time. Check {log}.",
        "start.not_ready": (
            "{name} did not become ready within {timeout}s. "
            "Slow hardware or a workspace with data to migrate can need longer; "
            "set {env} to a larger number of seconds."
        ),
        "start.port_in_use": (
            f"{PRODUCT_NAME} cannot start because port(s) already in use: {{ports}}. "
            "Stop the existing process or change data/user/settings/system.json."
        ),
        "start.port_conflict_title": "Port conflict detected:",
        "start.port_conflict_line": "  {role} port {port} is in use by:",
        "start.port_conflict_proc": "    PID {pid} · {command}",
        "start.port_conflict_unknown_proc": "    (process info unavailable)",
        "start.port_option_change": "Change ports (saved to data/user/settings/system.json)",
        "start.port_option_kill": "Stop the occupying process(es) and continue",
        "start.port_invalid": "Invalid port: {value}. Enter a free port between 1 and 65535.",
        "start.port_saved": "Ports saved to {path}.",
        "start.port_killing": "Stopping PID {pid} ({command}) ...",
        "start.port_kill_failed": "Could not free port {port} (PID {pid}).",
        "start.port_freed": "Port {port} released.",
    },
    "de": {
        "tagline": "Agent-Native Personalized Tutoring",
        "lab": "Data Intelligence Lab @ HKU",
        # init
        "init.mode": "Workspace initializer",
        "init.workspace": "Workspace",
        "init.note_settings_dir": "Settings will be written under data/user/settings.",
        "init.cancelled": "Setup cancelled. Nothing was saved.",
        "init.step_ports": "Step {n}/{total} · Ports",
        "init.step_llm": "Step {n}/{total} · LLM provider",
        "init.step_embedding": "Step {n}/{total} · Embedding (RAG / Knowledge Base)",
        "init.step_search": "Step {n}/{total} · Web search",
        "init.step_review": "Step {n}/{total} · Review & save",
        "init.backend_port": "Backend port",
        "init.frontend_port": "Frontend port",
        "init.llm_section": "LLM provider",
        "init.pick_provider": "Pick an LLM provider",
        "init.pick_embedding_provider": "Pick an embedding provider",
        "init.show_all": "Show all providers",
        "init.custom_provider": "Custom / Other",
        "init.skip_step": "Skip / configure later",
        "init.back": "Back",
        "init.skipped": "Skipped — you can configure this later in Web Settings.",
        "init.binding": "Binding",
        "init.base_url": "Base URL",
        "init.api_key": "API key",
        "init.api_key_env_detected": "Detected {env_var}={masked} in your environment. Use it?",
        "init.api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.api_key_reuse_llm": "Reuse the LLM API key {masked}?",
        "init.edit_base_url": "Edit Base URL?",
        "init.new_base_url": "New Base URL",
        "init.model": "Model",
        "init.fetch_models": "Fetching available models from {url} ...",
        "init.fetch_models_ok": "Found {count} model(s).",
        "init.fetch_models_fail": "Could not list models ({error}). Using fallback list.",
        "init.pick_model": "Pick a model — or type {marker} to enter your own",
        "init.custom_model": "Custom model name",
        "init.embedding_section": "Embedding provider",
        "init.embedding_endpoint": "Embedding endpoint URL",
        "init.embedding_api_key": "Embedding API key",
        "init.embedding_model": "Embedding model",
        "init.embedding_dimension": "Embedding dimension (blank for auto)",
        "init.search_section": "Web search provider",
        "init.pick_search_provider": "Pick a web-search provider",
        "init.search_api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.search_base_url_prompt": "Base URL",
        "init.search_no_key_note": "{label} does not need an API key.",
        "init.search_disabled_note": "Web search will be disabled. Agents will skip search tools.",
        "init.review_search": "Search",
        "init.review_search_disabled": "disabled",
        "init.probe_offer": "Test connection now?",
        "init.probe_running": "Testing {what} ...",
        "init.probe_ok": "{what} OK  ·  {ms}ms",
        "init.probe_fail": "{what} failed: {error}",
        "init.probe_retry": "Re-enter API key and retry?",
        "init.copilot_reuse_login": "Reuse the GitHub Copilot login for {account}?",
        "init.copilot_login_start": "Starting GitHub device login ...",
        "init.copilot_login_ok": "GitHub Copilot login succeeded for {account}.",
        "init.copilot_login_fail": "GitHub Copilot login failed: {error}",
        "init.review_title": "Review",
        "init.review_llm": "LLM",
        "init.review_embedding": "Embedding",
        "init.review_ports": "Ports",
        "init.review_ports_value": "backend {backend}, frontend {frontend}",
        "init.confirm_save": "Save these settings?",
        "init.saved": "Settings saved. You can edit them later in the Web Settings page or data/user/settings/.",
        "init.next_step": f"Run `deeptutor start` to launch {PRODUCT_NAME}.",
        "init.choice": "Choice",
        "init.choice_invalid": "Invalid choice. Try again.",
        # start (launcher)
        "start.mode": "Launching backend + frontend",
        "start.backend": "Backend",
        "start.browser_api": "Browser API",
        "start.frontend": "Frontend",
        "start.workspace": "Workspace",
        "start.frontend_runtime": "Frontend runtime",
        "start.press_ctrl_c": "Press Ctrl+C to stop.",
        "start.detached_started": f"{PRODUCT_NAME} is starting in the background (launcher PID {{pid}}).",
        "start.detached_already_running": (
            f"A detached {PRODUCT_NAME} launcher is already running (PID {{pid}}). Log: {{log}}"
        ),
        "start.detached_log": "Log: {path}",
        "start.detached_stop_hint": 'Stop it with `deeptutor stop --home "{home}"`.',
        "start.starting_backend": "Starting backend ...",
        "start.starting_frontend": "Starting frontend ...",
        "start.reusing_frontend": "Reusing existing frontend at {url} (PID {pid}).",
        "start.restarting_frontend": (
            "Existing frontend at {url} is not responding; restarting it (PID {pid})."
        ),
        "start.frontend_restart_failed": (
            "Existing frontend at {url} is not responding and could not be stopped automatically. "
            "Stop PID {pid} and run `deeptutor start` again."
        ),
        "start.waiting_for": "Waiting for {name} at {url} ...",
        "start.ready": "{name} is ready.",
        "start.open_in_browser": "Open {url} in your browser.",
        "start.received_signal": "Received {signal}; shutting down ...",
        "start.stopping": "Stopping {name} (PID {pid})",
        "start.exited": "{name} exited with code {code}",
        "stop.not_running": f"No detached {PRODUCT_NAME} launcher is running.",
        "stop.requested": "Requested a graceful stop from launcher PID {pid}.",
        "stop.complete": f"{PRODUCT_NAME} stopped.",
        "stop.timeout": "Launcher PID {pid} did not stop in time. Check {log}.",
        "start.not_ready": (
            "{name} did not become ready within {timeout}s. "
            "Slow hardware or a workspace with data to migrate can need longer; "
            "set {env} to a larger number of seconds."
        ),
        "start.port_in_use": (
            f"{PRODUCT_NAME} cannot start because port(s) already in use: {{ports}}. "
            "Stop the existing process or change data/user/settings/system.json."
        ),
        "start.port_conflict_title": "Port conflict detected:",
        "start.port_conflict_line": "  {role} port {port} is in use by:",
        "start.port_conflict_proc": "    PID {pid} · {command}",
        "start.port_conflict_unknown_proc": "    (process info unavailable)",
        "start.port_option_change": "Change ports (saved to data/user/settings/system.json)",
        "start.port_option_kill": "Stop the occupying process(es) and continue",
        "start.port_invalid": "Invalid port: {value}. Enter a free port between 1 and 65535.",
        "start.port_saved": "Ports saved to {path}.",
        "start.port_killing": "Stopping PID {pid} ({command}) ...",
        "start.port_kill_failed": "Could not free port {port} (PID {pid}).",
        "start.port_freed": "Port {port} released.",
    },
    "uk": {
        "tagline": "Agent-Native Personalized Tutoring",
        "lab": "Data Intelligence Lab @ HKU",
        # init
        "init.mode": "Workspace initializer",
        "init.workspace": "Workspace",
        "init.note_settings_dir": "Settings will be written under data/user/settings.",
        "init.cancelled": "Setup cancelled. Nothing was saved.",
        "init.step_ports": "Step {n}/{total} · Ports",
        "init.step_llm": "Step {n}/{total} · LLM provider",
        "init.step_embedding": "Step {n}/{total} · Embedding (RAG / Knowledge Base)",
        "init.step_search": "Step {n}/{total} · Web search",
        "init.step_review": "Step {n}/{total} · Review & save",
        "init.backend_port": "Backend port",
        "init.frontend_port": "Frontend port",
        "init.llm_section": "LLM provider",
        "init.pick_provider": "Pick an LLM provider",
        "init.pick_embedding_provider": "Pick an embedding provider",
        "init.show_all": "Show all providers",
        "init.custom_provider": "Custom / Other",
        "init.skip_step": "Skip / configure later",
        "init.back": "Back",
        "init.skipped": "Skipped — you can configure this later in Web Settings.",
        "init.binding": "Binding",
        "init.base_url": "Base URL",
        "init.api_key": "API key",
        "init.api_key_env_detected": "Detected {env_var}={masked} in your environment. Use it?",
        "init.api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.api_key_reuse_llm": "Reuse the LLM API key {masked}?",
        "init.edit_base_url": "Edit Base URL?",
        "init.new_base_url": "New Base URL",
        "init.model": "Model",
        "init.fetch_models": "Fetching available models from {url} ...",
        "init.fetch_models_ok": "Found {count} model(s).",
        "init.fetch_models_fail": "Could not list models ({error}). Using fallback list.",
        "init.pick_model": "Pick a model — or type {marker} to enter your own",
        "init.custom_model": "Custom model name",
        "init.embedding_section": "Embedding provider",
        "init.embedding_endpoint": "Embedding endpoint URL",
        "init.embedding_api_key": "Embedding API key",
        "init.embedding_model": "Embedding model",
        "init.embedding_dimension": "Embedding dimension (blank for auto)",
        "init.search_section": "Web search provider",
        "init.pick_search_provider": "Pick a web-search provider",
        "init.search_api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.search_base_url_prompt": "Base URL",
        "init.search_no_key_note": "{label} does not need an API key.",
        "init.search_disabled_note": "Web search will be disabled. Agents will skip search tools.",
        "init.review_search": "Search",
        "init.review_search_disabled": "disabled",
        "init.probe_offer": "Test connection now?",
        "init.probe_running": "Testing {what} ...",
        "init.probe_ok": "{what} OK  ·  {ms}ms",
        "init.probe_fail": "{what} failed: {error}",
        "init.probe_retry": "Re-enter API key and retry?",
        "init.copilot_reuse_login": "Reuse the GitHub Copilot login for {account}?",
        "init.copilot_login_start": "Starting GitHub device login ...",
        "init.copilot_login_ok": "GitHub Copilot login succeeded for {account}.",
        "init.copilot_login_fail": "GitHub Copilot login failed: {error}",
        "init.review_title": "Review",
        "init.review_llm": "LLM",
        "init.review_embedding": "Embedding",
        "init.review_ports": "Ports",
        "init.review_ports_value": "backend {backend}, frontend {frontend}",
        "init.confirm_save": "Save these settings?",
        "init.saved": "Settings saved. You can edit them later in the Web Settings page or data/user/settings/.",
        "init.next_step": f"Run `deeptutor start` to launch {PRODUCT_NAME}.",
        "init.choice": "Choice",
        "init.choice_invalid": "Invalid choice. Try again.",
        # start (launcher)
        "start.mode": "Launching backend + frontend",
        "start.backend": "Backend",
        "start.browser_api": "Browser API",
        "start.frontend": "Frontend",
        "start.workspace": "Workspace",
        "start.frontend_runtime": "Frontend runtime",
        "start.press_ctrl_c": "Press Ctrl+C to stop.",
        "start.detached_started": f"{PRODUCT_NAME} is starting in the background (launcher PID {{pid}}).",
        "start.detached_already_running": (
            f"A detached {PRODUCT_NAME} launcher is already running (PID {{pid}}). Log: {{log}}"
        ),
        "start.detached_log": "Log: {path}",
        "start.detached_stop_hint": 'Stop it with `deeptutor stop --home "{home}"`.',
        "start.starting_backend": "Starting backend ...",
        "start.starting_frontend": "Starting frontend ...",
        "start.reusing_frontend": "Reusing existing frontend at {url} (PID {pid}).",
        "start.restarting_frontend": (
            "Existing frontend at {url} is not responding; restarting it (PID {pid})."
        ),
        "start.frontend_restart_failed": (
            "Existing frontend at {url} is not responding and could not be stopped automatically. "
            "Stop PID {pid} and run `deeptutor start` again."
        ),
        "start.waiting_for": "Waiting for {name} at {url} ...",
        "start.ready": "{name} is ready.",
        "start.open_in_browser": "Open {url} in your browser.",
        "start.received_signal": "Received {signal}; shutting down ...",
        "start.stopping": "Stopping {name} (PID {pid})",
        "start.exited": "{name} exited with code {code}",
        "stop.not_running": f"No detached {PRODUCT_NAME} launcher is running.",
        "stop.requested": "Requested a graceful stop from launcher PID {pid}.",
        "stop.complete": f"{PRODUCT_NAME} stopped.",
        "stop.timeout": "Launcher PID {pid} did not stop in time. Check {log}.",
        "start.not_ready": (
            "{name} did not become ready within {timeout}s. "
            "Slow hardware or a workspace with data to migrate can need longer; "
            "set {env} to a larger number of seconds."
        ),
        "start.port_in_use": (
            f"{PRODUCT_NAME} cannot start because port(s) already in use: {{ports}}. "
            "Stop the existing process or change data/user/settings/system.json."
        ),
        "start.port_conflict_title": "Port conflict detected:",
        "start.port_conflict_line": "  {role} port {port} is in use by:",
        "start.port_conflict_proc": "    PID {pid} · {command}",
        "start.port_conflict_unknown_proc": "    (process info unavailable)",
        "start.port_option_change": "Change ports (saved to data/user/settings/system.json)",
        "start.port_option_kill": "Stop the occupying process(es) and continue",
        "start.port_invalid": "Invalid port: {value}. Enter a free port between 1 and 65535.",
        "start.port_saved": "Ports saved to {path}.",
        "start.port_killing": "Stopping PID {pid} ({command}) ...",
        "start.port_kill_failed": "Could not free port {port} (PID {pid}).",
        "start.port_freed": "Port {port} released.",
    },
}


def _pick_language(language: str | None) -> str:
    if not language:
        return "en"
    code = str(language).lower().strip()
    if code in {"zh", "zh-cn", "zh-hans", "chinese", "cn"}:
        return "zh"
    if code in {"de", "de-de", "de-at", "de-ch", "german", "deutsch"}:
        return "de"
    if code in {"uk", "uk-ua", "ukrainian", "ua"}:
        return "uk"
    return "en"


def resolve_language(default: str = "en") -> str:
    """Read the saved UI language, falling back to ``default``.

    Safe to call before the runtime is fully initialized; any failure
    silently falls back to the default.
    """
    try:
        from deeptutor.services.settings.interface_settings import get_ui_language

        return _pick_language(get_ui_language(default))
    except Exception:
        return _pick_language(default)


def labels_for(language: str | None) -> dict[str, str]:
    return LABELS[_pick_language(language)]


def render_banner(language: str | None, *, mode_key: str | None = None) -> Panel:
    """Build the branded banner panel.

    Parameters
    ----------
    language:
        Language code (``"en"``/``"zh"``). Unknown values fall back to English.
    mode_key:
        Optional key into ``LABELS[lang]`` to display under the tagline
        (e.g. ``"start.mode"``, ``"init.mode"``).
    """

    lang = _pick_language(language)
    strings = LABELS[lang]

    logo = Text(_ASCII_LOGO, style="bold bright_cyan")
    tagline_line = f"{strings['tagline']}  ·  v{__version__}"

    body = Text()
    body.append(logo)
    body.append("\n\n")
    body.append(tagline_line, style="bold white")
    body.append("\n")
    body.append(strings["lab"], style="dim")
    if mode_key and mode_key in strings:
        body.append("\n")
        body.append(strings[mode_key], style="italic bright_magenta")

    return Panel(
        Align.left(body),
        title=f"[bold bright_cyan]{PRODUCT_NAME}[/]",
        border_style="bright_cyan",
        padding=(1, 2),
    )


def print_banner(
    console: Console | None = None,
    *,
    language: str | None = None,
    mode_key: str | None = None,
) -> None:
    """Print the branded banner to ``console`` (creates one if omitted)."""

    target = console or Console()
    target.print(render_banner(language, mode_key=mode_key))


__all__: tuple[str, ...] = (
    "LABELS",
    "labels_for",
    "print_banner",
    "render_banner",
    "resolve_language",
)
