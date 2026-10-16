"""Owner-scoped evidence for image input, separate from declared model support.

Only a successful synthetic probe (or a matching managed connection's existing
real probe) can write a success. No document, credential or provider error is
stored here. Configurations are bound with a private salted digest so a key,
protocol, destination, model or account-generation change invalidates evidence.
"""
from __future__ import annotations

import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading


IMAGE_UNVERIFIED_EN = ("Image input has not been tested with this connection. "
    "Models declaring image support may be used directly; verification is optional.")
IMAGE_UNVERIFIED_ZH = "此连接尚未实测图片输入；声明支持图片的模型可以直接使用，也可以选择验证。"


def image_unverified_message(language="en"):
    return IMAGE_UNVERIFIED_ZH if str(language).lower().startswith("zh") else IMAGE_UNVERIFIED_EN


def image_unsupported_message(language="en"):
    return ("当前模型未声明支持图片，请选择支持图片的模型，或先验证此连接的图片能力。"
            if str(language).lower().startswith("zh") else
            "This model does not declare image support. Select an image-capable model or verify this connection's image capability.")


def _auth_generation(config):
    """Read this app's nonsecret OAuth generation, never a token or another app."""
    if "codex" not in str(getattr(config, "binding", "")).replace("-", "_"):
        return None
    from deeptutor.multi_user.paths import get_account_path_service
    from deeptutor.services.codex_auth.storage import CodexCredentialStore
    try:
        store = CodexCredentialStore(get_account_path_service().get_user_root())
        generation = store.current_generation()
        return {"generation": generation, "rejected": store.authentication_rejected(generation)}
    except Exception:
        # A corrupt/unavailable authorization cannot inherit old evidence.
        return "unavailable"


class ImageVerificationRegistry:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "image-verification.sqlite3"
        self._lock = threading.RLock()

    def _key(self):
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / "identity.key"
            try:
                with path.open("xb") as file:
                    file.write(secrets.token_bytes(32))
                os.chmod(path, 0o600)
            except FileExistsError:
                pass
            value = path.read_bytes()
            if len(value) != 32:
                raise ValueError("Image verification identity is unavailable")
            return value

    def identity(self, config, snapshot):
        private = {key: getattr(config, key, None) for key in (
            "model", "display_model", "binding", "provider_name", "provider_mode",
            "base_url", "effective_url", "api_format", "wire_api", "api_version",
            "api_key", "extra_headers", "context_window", "max_output_tokens")}
        private.update(actual_model=snapshot.get("model"), configuration_revision=snapshot.get("configuration_revision"),
                       account_generation=_auth_generation(config))
        raw = json.dumps(private, sort_keys=True, default=str, separators=(",", ":")).encode()
        return hmac.new(self._key(), raw, hashlib.sha256).hexdigest()

    def _connect(self):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("CREATE TABLE IF NOT EXISTS image_verifications (identity TEXT PRIMARY KEY, verified INTEGER, checked_at TEXT, source TEXT, status TEXT)")
        return db

    def status(self, config, snapshot, language="en"):
        supported = snapshot.get("capabilities", {}).get("vision") is True
        identity = self.identity(config, snapshot)
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT verified,checked_at,source,status FROM image_verifications WHERE identity=?", (identity,)).fetchone()
        verified = bool(row and row[0])
        result = {"verified": verified, "supported": supported or verified,
                  "declared_supported": supported, "configuration_identity": identity,
                  "status": "verified" if verified else (row[3] if row else "not_verified")}
        if row:
            result.update(checked_at=row[1], source=row[2])
        if not verified:
            result["message"] = image_unverified_message(language)
        return result

    def record(self, config, snapshot, verified, *, source="synthetic_probe", status=None, language="en"):
        identity = self.identity(config, snapshot)
        checked_at = datetime.now(timezone.utc).isoformat()
        with self._lock, closing(self._connect()) as db:
            with db:
                db.execute("INSERT OR REPLACE INTO image_verifications VALUES (?,?,?,?,?)", (
                    identity, int(verified is True), checked_at, source,
                    status or ("verified" if verified else "probe_failed")))
        return self.status(config, snapshot, language)


_registries = {}
_registry_lock = threading.RLock()


def default_registry():
    from deeptutor.multi_user.paths import get_account_path_service
    # Account state is never scoped to a user-selected content workspace.
    root = get_account_path_service().get_user_root() / "private" / "image-verification"
    with _registry_lock:
        return _registries.setdefault(str(root), ImageVerificationRegistry(root))


def verification_status(config, snapshot, language="en"):
    try:
        return default_registry().status(config, snapshot, language)
    except Exception:
        return {"verified": False, "supported": snapshot.get("capabilities", {}).get("vision") is True,
                "status": "verification_storage_unavailable", "message": image_unverified_message(language)}


def require_verified_image_config(config, language="en"):
    """Allow declared image support without turning it into verification evidence.

    A per-step token/temperature/reasoning adjustment does not select another
    connection. It may reuse the frozen scope's evidence only when the full
    wire destination, model, binding and credential configuration still match.
    """
    from deeptutor.services.llm.config import get_scoped_llm_config
    from deeptutor.services.model_selection.runtime import resolved_model_snapshot
    scoped = get_scoped_llm_config()
    from deeptutor.services.provider_registry import canonical_provider_name
    fields = ("model", "display_model", "provider_mode", "api_key", "base_url", "api_format", "wire_api", "api_version")
    same = scoped is not None and all(getattr(scoped, key, None) == getattr(config, key, None) for key in fields)
    if same:
        same = (all((canonical_provider_name(getattr(scoped, key, None)) or getattr(scoped, key, None)) ==
                    (canonical_provider_name(getattr(config, key, None)) or getattr(config, key, None))
                    for key in ("binding", "provider_name"))
                and (scoped.extra_headers or {}) == (config.extra_headers or {})
                # The existing native factory normalizes an explicitly repeated
                # base URL into effective_url. That does not select a new route.
                and config.effective_url in {scoped.effective_url, scoped.base_url})
    selected = scoped if same else config
    snapshot = resolved_model_snapshot(selected)
    capabilities = snapshot.get("capabilities", {})
    if not (capabilities.get("vision") is True or capabilities.get("vision_verified") is True):
        raise ValueError(image_unsupported_message(language))
    return snapshot


def synthetic_image_probe():
    """Fresh visual challenge: the expected answer is never included as text."""
    from PIL import Image, ImageDraw, ImageFont
    palette = {"RED": "#e22939", "GREEN": "#2aae4b", "BLUE": "#235edc", "YELLOW": "#f1d229"}
    labels = secrets.SystemRandom().sample(list(palette), 3)
    image = Image.new("RGB", (600, 225), "white")
    draw = ImageDraw.Draw(image)
    for index, label in enumerate(labels):
        draw.rectangle((index * 200 + 15, 15, index * 200 + 185, 145), fill=palette[label])
    # A nonce printed only inside pixels prevents a text-only successful guess
    # of one of the 24 possible colour orderings from becoming evidence.
    nonce = str(secrets.randbelow(900000) + 100000)
    try:
        font = ImageFont.load_default(size=40)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((220, 168), nonce, fill="black", font=font)
    file = BytesIO()
    image.save(file, "PNG")
    expected = ",".join(labels) + ";" + nonce
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Inspect this image. Identify the three coloured rectangles left to right (RED, GREEN, BLUE, or YELLOW), then read the six-digit number below them. Reply only as COLOUR,COLOUR,COLOUR;NUMBER in uppercase, without spaces. The order and number are only in image pixels; do not guess from text."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(file.getvalue()).decode("ascii")}},
    ]}]
    return messages, expected


def probe_answer_matches(content, expected):
    return str(content or "").strip().upper().replace(" ", "").replace("\n", "") == expected
