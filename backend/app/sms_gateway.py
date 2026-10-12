"""Minimal SMS export, ACS3 signing, a single send attempt and explicit unknown outcomes."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.config import Settings
from app.domain import now


@dataclass(frozen=True)
class Delivery:
    state: Literal["sent", "rejected", "unknown"]
    receipt: str = ""


class SmsGateway(Protocol):
    def send(self, phone: str, code: str, reference: str) -> Delivery: ...


def signed_headers(
    params: dict[str, str],
    access_key: str,
    secret: str,
    date: str,
    nonce: str,
    action: str = "SendSms",
    version: str = "2017-05-25",
    host: str = "dysmsapi.aliyuncs.com",
) -> dict[str, str]:
    headers = {
        "host": host,
        "x-acs-action": action,
        "x-acs-version": version,
        "x-acs-date": date,
        "x-acs-signature-nonce": nonce,
        "x-acs-content-sha256": hashlib.sha256(b"").hexdigest(),
    }
    query = "&".join(
        f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in sorted(params.items())
    )
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in sorted(headers.items()))
    signed = ";".join(sorted(headers))
    canonical = "\n".join(
        ("POST", "/", query, canonical_headers, signed, headers["x-acs-content-sha256"])
    )
    to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(canonical.encode()).hexdigest()
    signature = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = (
        f"ACS3-HMAC-SHA256 Credential={access_key},SignedHeaders={signed},Signature={signature}"
    )
    return headers


class AliyunSmsGateway:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings, self.client = settings, client

    def send(self, phone: str, code: str, reference: str) -> Delivery:
        params = {
            "PhoneNumbers": phone,
            "SignName": self.settings.sms_sign_name,
            "TemplateCode": self.settings.sms_template_code,
            "TemplateParam": json.dumps({"code": code}, separators=(",", ":")),
            "OutId": reference,
        }
        headers = signed_headers(
            params,
            self.settings.sms_access_key_id.get_secret_value(),
            self.settings.sms_access_key_secret.get_secret_value(),
            now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            str(uuid4()),
        )
        client = self.client or httpx.Client(timeout=8, follow_redirects=False)
        try:
            response = client.post(
                "https://dysmsapi.aliyuncs.com/", params=params, headers=headers, content=b""
            )
            if response.status_code != 200:
                return Delivery("unknown")
            data = response.json()
            if data.get("Code") == "OK" and isinstance(data.get("BizId"), str):
                return Delivery("sent", data["BizId"][:100])
            return (
                Delivery("rejected") if isinstance(data.get("Code"), str) else Delivery("unknown")
            )
        except (httpx.HTTPError, ValueError, AttributeError):
            return Delivery("unknown")
        finally:
            if self.client is None:
                client.close()


class SimulatedSmsGateway:
    def send(self, phone: str, code: str, reference: str) -> Delivery:
        return Delivery("sent", "simulated:" + reference)


def sms_gateway(settings: Settings) -> SmsGateway:
    if settings.booking_sms_provider == "simulated":
        return SimulatedSmsGateway()
    return AliyunSmsGateway(settings)
