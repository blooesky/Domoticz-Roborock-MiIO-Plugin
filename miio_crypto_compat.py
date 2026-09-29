#!/usr/bin/env python3
"""Stable AES-CBC backend for python-miio's legacy local protocol.

python-miio 0.5.12 normally encrypts miIO packets through
cryptography/OpenSSL. In long-running Domoticz installations with several
Python plugins, incompatible cryptography/OpenSSL modules can occasionally
be loaded into the same process, producing:

    UnsupportedAlgorithm: cipher AES in CBC mode is not supported

This module replaces only python-miio's two miIO payload helpers with the
equivalent PyCryptodomeX implementation. The wire format remains identical:
AES-128-CBC with the key and IV derived from the 16-byte device token and
PKCS#7 padding.
"""

from __future__ import annotations

import hashlib
from typing import Any

CRYPTO_BACKEND = "PyCryptodomeX AES-128-CBC"
_PATCHED = False


def _verify_token(token: bytes) -> None:
    if not isinstance(token, bytes):
        raise TypeError("Token must be bytes")
    if len(token) != 16:
        raise ValueError("Wrong token length")


def _key_iv(token: bytes) -> tuple[bytes, bytes]:
    _verify_token(token)
    key = hashlib.md5(token).digest()  # miIO protocol requirement
    iv = hashlib.md5(key + token).digest()  # miIO protocol requirement
    return key, iv


def _encrypt(plaintext: bytes, token: bytes) -> bytes:
    if not isinstance(plaintext, bytes):
        raise TypeError("plaintext requires bytes")

    from Cryptodome.Cipher import AES
    from Cryptodome.Util.Padding import pad

    key, iv = _key_iv(token)
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    return cipher.encrypt(pad(plaintext, AES.block_size, style="pkcs7"))


def _decrypt(ciphertext: bytes, token: bytes) -> bytes:
    if not isinstance(ciphertext, bytes):
        raise TypeError("ciphertext requires bytes")

    from Cryptodome.Cipher import AES
    from Cryptodome.Util.Padding import unpad

    key, iv = _key_iv(token)
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    padded = cipher.decrypt(ciphertext)
    return unpad(padded, AES.block_size, style="pkcs7")


def install_miio_crypto_patch() -> str:
    """Install the replacement once and return the active backend name."""
    global _PATCHED

    if _PATCHED:
        return CRYPTO_BACKEND

    # Importing miio.protocol may import cryptography, but no cipher object
    # is created at import time. Replacing Utils.encrypt/decrypt here ensures
    # all later Message.build/Message.parse operations use PyCryptodomeX.
    from miio import protocol as miio_protocol

    miio_protocol.Utils.encrypt = staticmethod(_encrypt)
    miio_protocol.Utils.decrypt = staticmethod(_decrypt)
    _PATCHED = True
    return CRYPTO_BACKEND


def self_test() -> None:
    """Verify encryption/decryption without contacting the vacuum."""
    install_miio_crypto_patch()

    from miio.protocol import Utils

    token = bytes.fromhex("00112233445566778899aabbccddeeff")
    plaintext = b'{"id":1,"method":"get_status","params":[]}\x00'
    encrypted = Utils.encrypt(plaintext, token)
    decrypted = Utils.decrypt(encrypted, token)

    if decrypted != plaintext:
        raise RuntimeError("miIO AES-CBC compatibility self-test failed")
