"""口令哈希（scrypt）与旧明文兼容校验。

从 ConfigService 抽出：纯函数、无状态、可独立测试。
"""
import hashlib
import hmac
import secrets

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_PASSWORD_PREFIX = "scrypt$"


def hash_password(password: str) -> str:
    """口令哈希（scrypt + 随机盐），返回自描述格式 `scrypt$N$r$p$salt_hex$hash_hex`。

    自描述是为了将来调参时仍能校验旧口令；salt 每条独立，杜绝彩虹表。
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN)
    return f"{_PASSWORD_PREFIX}{_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验口令：兼容旧明文（自动视为通过并提示迁移）与新 scrypt 格式。"""
    if not stored:
        return False
    if stored.startswith(_PASSWORD_PREFIX):
        try:
            _, n, r, p, salt_hex, hash_hex = stored.split("$")
            salt = bytes.fromhex(salt_hex)
            expect = bytes.fromhex(hash_hex)
            dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                n=int(n), r=int(r), p=int(p), dklen=_SCRYPT_DKLEN)
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(dk, expect)
    # 旧明文：常量时间比较（避免长度泄露）
    return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))


def is_hashed_password(stored: str) -> bool:
    """是否已是 scrypt 哈希（用于旧明文自动迁移判断）。"""
    return bool(stored) and stored.startswith(_PASSWORD_PREFIX)
