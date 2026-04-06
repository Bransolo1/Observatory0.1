"""Tests for auth service utilities."""

from observatory.core.auth.service import AuthService


def test_password_hashing():
    password = "test-password-123"
    hashed = AuthService.hash_password(password)
    assert hashed != password
    assert AuthService.verify_password(password, hashed)


def test_password_verification_fails_for_wrong_password():
    hashed = AuthService.hash_password("correct-password")
    assert not AuthService.verify_password("wrong-password", hashed)
