import base64
import contextlib
import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from fanzadl_webui.store.base import try_write

logger = logging.getLogger(__name__)

_HKDF_INFO = b"fanzadl-webui session store"
_HKDF_SALT = b"fanzadl-webui-session-store-salt-v1"


def _derive_key(key: bytes) -> bytes:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(key)
    return base64.urlsafe_b64encode(derived)


def save_sessions(path: Path, key: bytes, sessions: dict[str, datetime]) -> None:
    now = datetime.now(UTC)
    active = {
        token: expiry.isoformat() for token, expiry in sessions.items() if expiry > now
    }
    data = json.dumps(active).encode()
    encrypted = Fernet(_derive_key(key)).encrypt(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)
    try_write(
        encrypted, descriptor=fd, temp_path=tmp_path, orig_path=path, set_chmod=True
    )


def load_sessions(path: Path, key: bytes) -> dict[str, datetime]:
    try:
        encrypted = path.read_bytes()
        data = Fernet(_derive_key(key)).decrypt(encrypted)
        payload = json.loads(data)
        now = datetime.now(UTC)
        result: dict[str, datetime] = {}
        for token, iso in payload.items():
            try:
                expiry = datetime.fromisoformat(iso)
                if expiry > now:
                    result[token] = expiry
            except (ValueError, TypeError):
                continue
        return result
    except FileNotFoundError:
        return {}
    except (InvalidToken, json.JSONDecodeError):
        logger.warning(
            "Session store is corrupted or was encrypted with a different key; ignoring"
        )
        return {}


def delete_sessions(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
