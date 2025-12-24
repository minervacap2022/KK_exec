"""Credential encryption using Fernet symmetric encryption.

Provides authenticated encryption for credential data using the cryptography library.
All credential values are encrypted before storage and decrypted only when needed.

SECURITY NOTES:
- Uses Fernet (AES-128-CBC with HMAC-SHA256)
- Encryption key must be 32 url-safe base64-encoded bytes
- Never log decrypted credential values
- Clear decrypted values from memory as soon as possible
"""

import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
import structlog

logger = structlog.get_logger()


class EncryptionError(Exception):
    """Base exception for encryption operations."""

    pass


class EncryptionKeyError(EncryptionError):
    """Invalid or missing encryption key."""

    pass


class DecryptionError(EncryptionError):
    """Failed to decrypt data."""

    pass


class CredentialEncryption:
    """Fernet-based credential encryption.

    Thread-safe and stateless - can be shared across requests.

    Example usage:
        encryption = CredentialEncryption(key)
        encrypted = encryption.encrypt({"api_key": "sk-..."})
        decrypted = encryption.decrypt(encrypted)
    """

    def __init__(self, key: str) -> None:
        """Initialize with a Fernet key.

        Args:
            key: Fernet key (32 url-safe base64-encoded bytes)

        Raises:
            EncryptionKeyError: If key is invalid
        """
        try:
            # Validate key format by creating Fernet instance
            self._fernet = Fernet(key.encode())
            logger.debug("encryption_initialized")
        except Exception as e:
            logger.error("encryption_key_invalid", error=str(e))
            raise EncryptionKeyError(
                "Invalid encryption key format. "
                "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            ) from e

    def encrypt(self, data: dict[str, Any]) -> str:
        """Encrypt a dictionary of credential data.

        Args:
            data: Credential data to encrypt

        Returns:
            Fernet-encrypted string (url-safe base64)

        Raises:
            EncryptionError: If encryption fails
        """
        try:
            json_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
            encrypted = self._fernet.encrypt(json_bytes)
            return encrypted.decode("utf-8")
        except Exception as e:
            logger.error("encryption_failed", error_type=type(e).__name__)
            raise EncryptionError("Failed to encrypt credential data") from e

    def decrypt(self, encrypted_data: str) -> dict[str, Any]:
        """Decrypt credential data.

        Args:
            encrypted_data: Fernet-encrypted string

        Returns:
            Decrypted credential dictionary

        Raises:
            DecryptionError: If decryption fails (wrong key, corrupted data, etc.)
        """
        try:
            decrypted_bytes = self._fernet.decrypt(encrypted_data.encode("utf-8"))
            return json.loads(decrypted_bytes.decode("utf-8"))
        except InvalidToken as e:
            logger.warning("decryption_invalid_token")
            raise DecryptionError(
                "Failed to decrypt: invalid token (wrong key or corrupted data)"
            ) from e
        except json.JSONDecodeError as e:
            logger.error("decryption_invalid_json")
            raise DecryptionError("Decrypted data is not valid JSON") from e
        except Exception as e:
            logger.error("decryption_failed", error_type=type(e).__name__)
            raise DecryptionError("Failed to decrypt credential data") from e

    def rotate_key(
        self,
        encrypted_data: str,
        old_key: str,
        new_key: str,
    ) -> str:
        """Re-encrypt data with a new key.

        Used for key rotation without data loss.

        Args:
            encrypted_data: Data encrypted with old key
            old_key: Previous encryption key
            new_key: New encryption key

        Returns:
            Data encrypted with new key

        Raises:
            EncryptionError: If rotation fails
        """
        try:
            # Decrypt with old key
            old_fernet = Fernet(old_key.encode())
            decrypted = old_fernet.decrypt(encrypted_data.encode("utf-8"))

            # Encrypt with new key
            new_fernet = Fernet(new_key.encode())
            re_encrypted = new_fernet.encrypt(decrypted)

            logger.info("credential_key_rotated")
            return re_encrypted.decode("utf-8")
        except Exception as e:
            logger.error("key_rotation_failed", error_type=type(e).__name__)
            raise EncryptionError("Failed to rotate encryption key") from e

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet encryption key.

        Returns:
            New url-safe base64-encoded Fernet key
        """
        return Fernet.generate_key().decode("utf-8")

    @staticmethod
    def generate_random_string(length: int = 32) -> str:
        """Generate a cryptographically secure random string.

        Useful for generating API keys, tokens, etc.

        Args:
            length: Length of the string in bytes (will be longer in hex)

        Returns:
            Hex-encoded random string
        """
        return secrets.token_hex(length)

    @staticmethod
    def constant_time_compare(a: str, b: str) -> bool:
        """Compare two strings in constant time.

        Prevents timing attacks when comparing sensitive values.

        Args:
            a: First string
            b: Second string

        Returns:
            True if strings are equal
        """
        return secrets.compare_digest(a.encode(), b.encode())


def mask_credential_value(value: str, visible_chars: int = 4) -> str:
    """Mask a credential value for safe logging.

    Shows only the first few characters followed by asterisks.

    Args:
        value: Credential value to mask
        visible_chars: Number of visible characters

    Returns:
        Masked string like "sk-a***"
    """
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "*" * min(8, len(value) - visible_chars)
