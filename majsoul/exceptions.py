"""Custom exceptions for Majsoul client"""


class MajsoulError(Exception):
    """Base exception for Majsoul client"""
    pass


class ConnectionError(MajsoulError):
    """Failed to connect to server"""
    pass


class AuthenticationError(MajsoulError):
    """Authentication failed"""
    pass


class TimeoutError(MajsoulError):
    """Request timeout"""
    pass


class MessageError(MajsoulError):
    """Message encoding/decoding error"""
    pass

