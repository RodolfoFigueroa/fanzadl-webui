import base64
import contextlib
import json
import logging
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from fanzadl_webui.store.base import try_write

logger = logging.getLogger(__name__)

_HKDF_INFO = b"fanzadl-webui api key store"
_HKDF_SALT = b"fanzadl-webui-api-key-store-salt-v1"


def _derive_key(key: bytes) -> bytes:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(key)
    return base64.urlsafe_b64encode(derived)


def save_api_key(path: Path, key: bytes, api_key: str) -> None:
    data = json.dumps({"api_key": api_key}).encode()
    encrypted = Fernet(_derive_key(key)).encrypt(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)

    try_write(
        encrypted, descriptor=fd, temp_path=tmp_path, orig_path=path, set_chmod=True
    )


def load_api_key(path: Path, key: bytes) -> str | None:
    try:
        encrypted = path.read_bytes()
        data = Fernet(_derive_key(key)).decrypt(encrypted)
        payload = json.loads(data)
        return payload["api_key"]
    except FileNotFoundError:
        return None
    except (InvalidToken, KeyError, json.JSONDecodeError):
        logger.warning(
            "API key store is corrupted or was encrypted with a different key; ignoring"
        )
        return None


def delete_api_key(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
