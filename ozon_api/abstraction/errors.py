from __future__ import annotations


class AppError(Exception):
    code = "app_error"
    default_message = "Application error"

    def __init__(self, message: str | None = None, *, details: dict | None = None) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "type": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class VPNError(AppError):
    code = "vpn_error"
    default_message = "IP адресс определен как VPN, Ozon отверг запрос."
