"""Tests for credential encryption."""

import pytest
from hypothesis import given, strategies as st

from src.core.encryption import (
    CredentialEncryption,
    DecryptionError,
    EncryptionKeyError,
    mask_credential_value,
)


class TestCredentialEncryption:
    """Tests for CredentialEncryption class."""

    def test_encrypt_decrypt_roundtrip(self, encryption: CredentialEncryption):
        """Test that encryption/decryption is reversible."""
        original = {"api_key": "sk-test123", "secret": "mysecret"}
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)

        assert decrypted == original

    def test_encrypted_data_is_different(self, encryption: CredentialEncryption):
        """Test that encrypted data differs from original."""
        original = {"api_key": "sk-test123"}
        encrypted = encryption.encrypt(original)

        assert "sk-test123" not in encrypted
        assert encrypted != str(original)

    def test_decrypt_invalid_data_raises_error(self, encryption: CredentialEncryption):
        """Test that decrypting invalid data raises error."""
        with pytest.raises(DecryptionError):
            encryption.decrypt("invalid-encrypted-data")

    def test_invalid_key_raises_error(self):
        """Test that invalid key raises error."""
        with pytest.raises(EncryptionKeyError):
            CredentialEncryption("invalid-key")

    def test_generate_key_format(self):
        """Test that generated key has correct format."""
        key = CredentialEncryption.generate_key()

        # Should be url-safe base64
        assert isinstance(key, str)
        assert len(key) == 44  # Fernet key length

        # Should be usable
        enc = CredentialEncryption(key)
        assert enc is not None

    @given(st.text(min_size=1))
    def test_encrypt_arbitrary_strings(self, encryption: CredentialEncryption, value: str):
        """Property test: any string value should encrypt/decrypt correctly."""
        original = {"value": value}
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)

        assert decrypted == original

    def test_key_rotation(self):
        """Test key rotation preserves data."""
        old_key = CredentialEncryption.generate_key()
        new_key = CredentialEncryption.generate_key()

        old_enc = CredentialEncryption(old_key)
        new_enc = CredentialEncryption(new_key)

        original = {"api_key": "secret123"}
        old_encrypted = old_enc.encrypt(original)

        # Rotate to new key
        new_encrypted = old_enc.rotate_key(old_encrypted, old_key, new_key)

        # Verify new encryption works
        decrypted = new_enc.decrypt(new_encrypted)
        assert decrypted == original


class TestMaskCredentialValue:
    """Tests for mask_credential_value function."""

    def test_mask_api_key(self):
        """Test masking an API key."""
        masked = mask_credential_value("sk-abc123xyz")
        assert masked == "sk-a********"

    def test_mask_short_value(self):
        """Test masking a short value."""
        masked = mask_credential_value("abc")
        assert masked == "***"

    def test_mask_exact_length(self):
        """Test masking value at exact visible length."""
        masked = mask_credential_value("abcd", visible_chars=4)
        assert masked == "****"

    def test_mask_custom_visible(self):
        """Test custom visible characters."""
        masked = mask_credential_value("sk-abc123xyz", visible_chars=8)
        assert masked == "sk-abc12********"
