import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.sms_gateway import AliyunSmsGateway, signed_headers

KEY = "ZGV2LXRlc3QtZW5jcnlwdGlvbi1rZXktMzJieXRlcyE="


def configured(**changes: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://unused",
        environment="production",
        allowed_origins=["https://example.test"],
        milvus_uri="https://milvus.example.test",
        milvus_read_token="synthetic-reader",
        milvus_write_token="synthetic-worker",
        booking_sms_provider="aliyun",
        booking_encryption_key=KEY,
        booking_hmac_key="synthetic-test-hmac-key-with-32-characters",
        sms_access_key_id="synthetic-access-key",
        sms_access_key_secret="synthetic-secret",
        sms_sign_name="合成测试签名",
        sms_template_code="SMS_SYNTHETIC",
        **changes,
    )


def test_acs3_signature_matches_official_golden_vector() -> None:
    headers = signed_headers(
        {
            "ImageId": "win2019_1809_x64_dtc_zh-cn_40G_alibase_20230811.vhd",
            "RegionId": "cn-shanghai",
        },
        "YourAccessKeyId",
        "YourAccessKeySecret",
        "2023-10-26T10:22:32Z",
        "3156853299f313e23d1673dc12e1703d",
        "RunInstances",
        "2014-05-26",
        "ecs.cn-shanghai.aliyuncs.com",
    )
    assert headers["authorization"].endswith(
        "Signature=06563a9e1b43f5dfe96b81484da74bceab24a1d853912eee15083a6f0f3283c0"
    )


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("ok", "sent"),
        ("rejected", "rejected"),
        ("timeout", "unknown"),
        ("redirect", "unknown"),
        ("bad_json", "unknown"),
    ],
)
def test_real_adapter_fixed_destination_minimal_export_and_no_retry(
    outcome: str, expected: str
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "dysmsapi.aliyuncs.com" and request.url.scheme == "https"
        assert request.method == "POST" and request.content == b""
        params = dict(request.url.params)
        assert set(params) == {"PhoneNumbers", "SignName", "TemplateCode", "TemplateParam", "OutId"}
        assert json.loads(params["TemplateParam"]) == {"code": "123456"}
        assert request.headers["x-acs-action"] == "SendSms"
        if outcome == "timeout":
            raise httpx.ReadTimeout("synthetic-sensitive-body", request=request)
        if outcome == "redirect":
            return httpx.Response(302, headers={"Location": "https://untrusted.example.test"})
        if outcome == "bad_json":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(
            200,
            json={"Code": "OK", "BizId": "synthetic-biz"}
            if outcome == "ok"
            else {"Code": "isv.SYNTHETIC_REJECTION", "Message": "synthetic-sensitive-body"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False) as client:
        result = AliyunSmsGateway(configured(), client).send(
            "19900000001", "123456", "synthetic-reference"
        )
    assert result.state == expected and len(requests) == 1
    assert "sensitive" not in str(result)


@pytest.mark.parametrize(
    "change",
    [
        {"booking_sms_provider": "simulated"},
        {"booking_sms_provider": "disabled"},
        {"sms_access_key_secret": ""},
        {"booking_hmac_key": "short"},
        {"booking_encryption_key": "bad-key"},
    ],
)
def test_production_rejects_simulation_disabled_missing_credentials_and_invalid_keys(
    change: dict[str, Any],
) -> None:
    # model_dump excludes the synthetic credentials from output; validation is performed anew.
    values = configured().model_dump()
    values.update(change)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_production_real_provider_and_secret_repr() -> None:
    settings = configured()
    assert settings.booking_sms_provider == "aliyun"
    assert "synthetic-secret" not in str(settings) and KEY not in str(settings)
