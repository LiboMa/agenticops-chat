"""WeCom (企业微信) IM Gateway — callback with AES decryption."""

import base64
import hashlib
import logging
import struct
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, Optional

from agenticops.im.gateway import IMGateway, IMInboundMessage
from agenticops.notify.im_config import get_wecom_app

logger = logging.getLogger(__name__)


def _pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS#7 padding."""
    pad = data[-1]
    if pad < 1 or pad > 32:
        return data
    return data[:-pad]


class WeComGateway(IMGateway):
    """WeCom callback gateway with AES-256-CBC message decryption.

    Handles:
    - Callback URL verification (echostr decryption)
    - Text message decryption and parsing
    - msg_signature verification
    """

    platform = "wecom"

    def __init__(self, app_name: str = "default"):
        self.app_name = app_name
        self._app_config = get_wecom_app(app_name)

    def _get_aes_key(self) -> Optional[bytes]:
        """Decode the EncodingAESKey (Base64 → 32 bytes)."""
        if not self._app_config or not self._app_config.encoding_aes_key:
            return None
        return base64.b64decode(self._app_config.encoding_aes_key + "=")

    def verify_callback(self, request_body: bytes, headers: Dict[str, str]) -> bool:
        """Verify WeCom callback msg_signature.

        msg_signature = SHA1(sort(token, timestamp, nonce, msg_encrypt))
        If no callback_token is configured, skip verification.
        """
        if not self._app_config or not self._app_config.callback_token:
            return True

        # Parse msg_signature from query params (passed via headers dict)
        msg_signature = headers.get("msg_signature", "")
        timestamp = headers.get("timestamp", "")
        nonce = headers.get("nonce", "")

        if not msg_signature:
            return True  # Dev mode

        # Extract Encrypt from XML body
        try:
            root = ET.fromstring(request_body)
            encrypt = root.find("Encrypt")
            encrypt_text = encrypt.text if encrypt is not None else ""
        except ET.ParseError:
            return False

        sort_list = sorted([self._app_config.callback_token, timestamp, nonce, encrypt_text])
        sha1 = hashlib.sha1("".join(sort_list).encode()).hexdigest()
        return sha1 == msg_signature

    def _decrypt_message(self, encrypt_text: str) -> Optional[str]:
        """Decrypt WeCom AES-256-CBC encrypted message."""
        aes_key = self._get_aes_key()
        if not aes_key:
            logger.warning("WeCom AES key not configured, cannot decrypt")
            return None

        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend

            encrypted = base64.b64decode(encrypt_text)
            iv = aes_key[:16]
            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted) + decryptor.finalize()
            decrypted = _pkcs7_unpad(decrypted)

            # WeCom message format: random(16) + msg_len(4) + msg + corp_id
            msg_len = struct.unpack("!I", decrypted[16:20])[0]
            msg = decrypted[20:20 + msg_len].decode("utf-8")
            return msg
        except ImportError:
            logger.error("cryptography package required for WeCom AES decryption: pip install cryptography")
            return None
        except Exception as e:
            logger.error("WeCom message decryption failed: %s", e)
            return None

    def parse_message(self, payload: Dict[str, Any]) -> Optional[IMInboundMessage]:
        """Parse WeCom callback XML into IMInboundMessage.

        The payload dict should contain:
        - "xml_body": raw XML string from request body
        - "msg_signature", "timestamp", "nonce": from query params

        Returns None for non-text messages.
        """
        xml_body = payload.get("xml_body", "")
        if not xml_body:
            return None

        # Parse outer XML to get Encrypt element
        try:
            root = ET.fromstring(xml_body)
            encrypt_el = root.find("Encrypt")
            if encrypt_el is None or not encrypt_el.text:
                return None
        except ET.ParseError:
            logger.error("Failed to parse WeCom callback XML")
            return None

        # Decrypt the inner message
        decrypted_xml = self._decrypt_message(encrypt_el.text)
        if not decrypted_xml:
            return None

        # Parse the decrypted inner XML
        try:
            msg_root = ET.fromstring(decrypted_xml)
        except ET.ParseError:
            logger.error("Failed to parse decrypted WeCom message XML")
            return None

        msg_type = msg_root.findtext("MsgType", "")
        if msg_type != "text":
            logger.debug("Ignoring WeCom message type: %s", msg_type)
            return None

        content = msg_root.findtext("Content", "").strip()
        if not content:
            return None

        from_user = msg_root.findtext("FromUserName", "")
        msg_id = msg_root.findtext("MsgId", "")
        agent_id = msg_root.findtext("AgentID", "")

        return IMInboundMessage(
            platform="wecom",
            chat_id=agent_id,  # WeCom uses AgentID as the routing context
            sender_id=from_user,
            sender_name=from_user,
            content=content,
            message_id=msg_id,
            timestamp=datetime.utcnow(),
            is_group=False,  # WeCom app messages are typically user-to-app
            app_name=self.app_name,
        )

    def decrypt_echostr(self, echostr: str) -> Optional[str]:
        """Decrypt the echostr for callback URL verification."""
        result = self._decrypt_message(echostr)
        return result
