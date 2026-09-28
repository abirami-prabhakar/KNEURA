"""Replaceable local identity provider; authorization remains in the API.

A hospital SSO adapter must return a server-verified account with the same
id/name/role/patient_id contract. Never trust a role supplied by the browser.
"""
import hashlib
import hmac
import time
from typing import Protocol


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 300000).hex()


class IdentityProvider(Protocol):
    def authenticate(self, conn, email: str, password: str, role: str): ...
    def resolve_session(self, conn, token: str): ...


class LocalIdentityProvider:
    def authenticate(self, conn, email, password, role):
        row = conn.execute('SELECT * FROM users WHERE email=?', (email.lower().strip(),)).fetchone()
        candidate = password_hash(password, row['salt'] if row else '00' * 16)
        if row and hmac.compare_digest(candidate, row['password']) and role == row['role']:
            return dict(row)
        return None

    def resolve_session(self, conn, token):
        row = conn.execute('SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=? AND s.expires>?',
                           (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(row) if row else None


identity_provider: IdentityProvider = LocalIdentityProvider()
