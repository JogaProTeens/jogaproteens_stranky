"""Login for the editor: one password, stored only as an Argon2 hash.

Create the two secrets the editor needs with:
    python -m editor.auth
and put the printed lines into .env (on your Mac) or into Render's
environment settings (online). The password itself is never stored.
"""
from __future__ import annotations

import getpass
import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MAX_FAILURES = 5                  # wrong passwords in a row...
LOCK_SECONDS = 15 * 60            # ...lock that device out for 15 minutes
GLOBAL_MAX_FAILURES = 20          # wrong passwords from all devices together
SESSION_DAYS = 30                 # stay logged in this long

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_ok(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def session_tag(password_hash: str) -> str:
    """Stored in the login cookie. A new password gives a new tag, so
    changing the password logs out every device automatically."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


class LoginGuard:
    """Counts wrong passwords and locks login for a while after too many.

    Per device (IP address): 5 wrong in a row lock that device.
    Overall: 20 wrong from anywhere within the lock period lock everyone,
    so changing IP addresses does not help someone guessing.
    Kept in memory, which is enough for one small editor.
    """

    def __init__(self, max_failures: int = MAX_FAILURES, lock_seconds: int = LOCK_SECONDS,
                 global_max: int = GLOBAL_MAX_FAILURES, clock=time.monotonic):
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self.global_max = global_max
        self.clock = clock
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}
        self._recent: list[float] = []            # times of recent failures, any device

    def seconds_locked(self, ip: str) -> int:
        until = max(self._locked_until.get(ip, 0), self._locked_until.get("*", 0))
        return max(0, int(until - self.clock() + 0.999))

    def failed(self, ip: str) -> None:
        now = self.clock()
        count = self._failures.get(ip, 0) + 1
        if count >= self.max_failures:
            self._locked_until[ip] = now + self.lock_seconds
            count = 0
        self._failures[ip] = count
        self._recent = [t for t in self._recent if now - t < self.lock_seconds] + [now]
        if len(self._recent) >= self.global_max:
            self._locked_until["*"] = now + self.lock_seconds
            self._recent = []

    def succeeded(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._locked_until.pop(ip, None)


def main() -> None:
    print("Nové heslo do editoru (při psaní se nezobrazuje).")
    while True:
        first = getpass.getpass("Heslo: ")
        if len(first) < 10:
            print("Použijte aspoň 10 znaků.")
            continue
        if getpass.getpass("Znovu pro kontrolu: ") != first:
            print("Hesla se neshodují, zkuste to znovu.")
            continue
        break
    print("\nZkopírujte tyto dva řádky (do .env nebo do Renderu):\n")
    print(f"EDITOR_PASSWORD_HASH={hash_password(first)}")
    print(f"SESSION_SECRET={secrets.token_urlsafe(32)}")


if __name__ == "__main__":
    main()
