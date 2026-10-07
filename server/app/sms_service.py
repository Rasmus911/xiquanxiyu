import json
import logging
import re

from flask import current_app

logger = logging.getLogger(__name__)


def _masked_phone(phone):
    value = str(phone or "")
    return f"{value[:3]}****{value[-4:]}" if len(value) == 11 else "****"


def _result(recipient, success, status, message, **extra):
    return {
        "recipient": recipient,
        "success": success,
        "status": status,
        "message": message,
        **extra,
    }


def send_template_sms(phone, template_code, template_params, recipient):
    if not current_app.config.get("SMS_ENABLED"):
        return _result(recipient, False, "disabled", "短信服务未启用")

    phone = str(phone or "").strip()
    if not re.fullmatch(r"1\d{10}", phone):
        return _result(recipient, False, "invalid_phone", "接收手机号无效")

    access_key_id = str(current_app.config.get("ALIBABA_CLOUD_ACCESS_KEY_ID") or "").strip()
    access_key_secret = str(current_app.config.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET") or "").strip()
    sign_name = str(current_app.config.get("SMS_SIGN_NAME") or "").strip()
    template_code = str(template_code or "").strip()
    if not all((access_key_id, access_key_secret, sign_name, template_code)):
        return _result(recipient, False, "not_configured", "阿里云短信参数未配置完整")

    try:
        from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
        from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_tea_util import models as util_models

        client_config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        client_config.endpoint = str(current_app.config.get("SMS_ENDPOINT") or "dysmsapi.aliyuncs.com").strip()
        client = DysmsapiClient(client_config)
        sms_request = dysmsapi_models.SendSmsRequest(
            phone_numbers=phone,
            sign_name=sign_name,
            template_code=template_code,
            template_param=json.dumps(template_params, ensure_ascii=False, separators=(",", ":")),
        )
        runtime = util_models.RuntimeOptions()
        runtime.connect_timeout = 5000
        runtime.read_timeout = 8000
        response = client.send_sms_with_options(sms_request, runtime)
        response_body = response.body
        code = str(getattr(response_body, "code", ""))
        message = str(getattr(response_body, "message", ""))
        request_id = str(getattr(response_body, "request_id", "") or "")
        biz_id = str(getattr(response_body, "biz_id", "") or "")
        success = code == "OK"
        if not success:
            logger.warning(
                "Alibaba Cloud SMS rejected recipient=%s code=%s message=%s request_id=%s",
                _masked_phone(phone),
                code,
                message,
                request_id,
            )
        return _result(
            recipient,
            success,
            "sent" if success else "rejected",
            "短信已提交运营商" if success else (message or "短信发送被拒绝"),
            provider_code=code,
            request_id=request_id,
            biz_id=biz_id,
        )
    except ImportError:
        logger.exception("Alibaba Cloud SMS SDK is not installed")
        return _result(recipient, False, "sdk_missing", "服务器未安装阿里云短信 SDK")
    except Exception as error:
        logger.exception("Alibaba Cloud SMS request failed recipient=%s", _masked_phone(phone))
        return _result(recipient, False, "failed", str(error)[:200] or "短信发送异常")


def notify_card_opened(member, employee, card_type, balance=None, remaining=None, total=None):
    if card_type == "stored":
        customer_template = current_app.config.get("SMS_STORED_CARD_TEMPLATE_CODE")
        customer_params = {"balance": str(balance)}
    elif card_type == "pass":
        customer_template = current_app.config.get("SMS_PASS_CARD_TEMPLATE_CODE")
        customer_params = {"remaining": str(remaining), "total": str(total)}
    else:
        raise ValueError("不支持的会员卡类型")

    member_label = member.name or member.phone
    employee_label = f"{employee.username}员工"
    results = [
        send_template_sms(member.phone, customer_template, customer_params, "member"),
    ]
    # 支持多个管理员手机号，用逗号分隔
    admin_phones = str(current_app.config.get("SMS_ADMIN_PHONE") or "").strip()
    for admin_phone in [p.strip() for p in admin_phones.split(",") if p.strip()]:
        results.append(
            send_template_sms(
                admin_phone,
                current_app.config.get("SMS_ADMIN_TEMPLATE_CODE"),
                {"employee": employee_label, "member": member_label},
                "admin",
            )
        )
    return results
