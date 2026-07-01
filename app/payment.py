"""
微信支付V3核心模块：统一下单、回调验签、订单查询、退款接口
复用现有wechat.py的OAuth能力，新增支付相关API
"""

import os
import time
import base64
import json
import secrets
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from fastapi import Request, HTTPException
from pydantic import BaseModel

from .models import PlanType
from .invite_codes import confirm_order
from .quota import upgrade_plan, get_or_create_user

logger = logging.getLogger("k12_rocket.payment")

# ============================================================
# 微信支付 V3 商户配置
# ============================================================
MCH_ID = os.getenv("WECHAT_MCH_ID", "")
SERIAL_NO = os.getenv("WECHAT_PAY_SERIAL_NO", "")
API_KEY = os.getenv("WECHAT_PAY_API_KEY", "")  # APIv3 密钥 (32字节)
PRIVATE_KEY_VAL = os.getenv("WECHAT_PAY_PRIVATE_KEY", "")  # 商户 API 私钥文本 (PEM)
NOTIFY_URL = os.getenv("WECHAT_PAY_NOTIFY_URL", "")
PLATFORM_CERT_SERIAL = os.getenv("WECHAT_PLATFORM_CERT_SERIAL", "")  # 平台证书序列号

# 判断是否启用 Mock 模式：若没有配置证书或私钥，系统自动进入 Mock 模式运行以供测试
IS_MOCK_PAY = (not MCH_ID or not SERIAL_NO or not API_KEY or not PRIVATE_KEY_VAL)

APPID = os.getenv("WECHAT_APPID", "")
if not APPID and not IS_MOCK_PAY:
    raise ValueError("CRITICAL: WECHAT_APPID environment variable is not set! Server refuses to start in real payment mode.")

if IS_MOCK_PAY:
    logger.warning("[Payment] 微信支付未配齐真实商户密钥，系统已进入 Mock 模式运行。")
else:
    logger.info("[Payment] 微信支付商户证书载入成功，以真实模式运行。")


# ============================================================
# 数据模型
# ============================================================
class UnifiedOrderRequest(BaseModel):
    """统一下单请求参数"""
    openid: str
    description: str
    amount: int  # 单位：分
    out_trade_no: str
    attach: Optional[str] = None
    goods_tag: Optional[str] = None


class RefundRequest(BaseModel):
    """退款请求参数"""
    out_trade_no: str
    out_refund_no: str
    amount: int  # 退款金额，单位：分
    total_amount: int  # 原订单金额，单位：分
    reason: Optional[str] = None


class PaymentResult(BaseModel):
    """支付结果"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ============================================================
# 核心加密/签名工具函数
# ============================================================
def decrypt_wechat_resource(ciphertext: str, nonce: str, associated_data: str) -> Optional[dict]:
    """
    AES-256-GCM 密文解密（微信支付回调通知）
    """
    if not API_KEY:
        logger.error("[Payment] 未配置 API_KEY，无法解密")
        return None

    try:
        key_bytes = API_KEY.encode('utf-8')
        nonce_bytes = nonce.encode('utf-8')
        aad_bytes = associated_data.encode('utf-8') if associated_data else None
        raw_ciphertext = base64.b64decode(ciphertext)

        aesgcm = AESGCM(key_bytes)
        decrypted_bytes = aesgcm.decrypt(nonce_bytes, raw_ciphertext, aad_bytes)

        result_str = decrypted_bytes.decode('utf-8')
        return json.loads(result_str)
    except Exception as e:
        logger.error(f"[Payment] AESGCM 解密失败: {e}")
        return None


def _load_private_key():
    """从文本或文件路径加载商户私钥"""
    try:
        pem_content = PRIVATE_KEY_VAL
        # 如果是现有文件路径，则读取文件内容
        if pem_content and (pem_content.startswith("/") or pem_content.endswith(".pem") or os.path.exists(pem_content)):
            try:
                with open(pem_content, 'r', encoding='utf-8') as f:
                    pem_content = f.read()
            except IOError as e:
                logger.error(f"[Payment] 无法从文件 {pem_content} 读取私钥: {e}")

        pem_data = pem_content.replace("\\n", "\n").encode("utf-8")
        if not pem_data.startswith(b"-----BEGIN PRIVATE KEY-----"):
            # 如果没有包含头部，自动补齐
            pem_data = b"-----BEGIN PRIVATE KEY-----\n" + pem_data + b"\n-----END PRIVATE KEY-----"
        return serialization.load_pem_private_key(pem_data, password=None)
    except Exception as e:
        logger.error(f"[Payment] 商户私钥加载异常: {e}")
        return None


def sign_sha256_with_rsa(message: str) -> str:
    """使用商户私钥进行 SHA256withRSA 签名"""
    private_key = _load_private_key()
    if not private_key:
        return ""
    try:
        signature = private_key.sign(
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode("utf-8")
    except Exception as e:
        logger.error(f"[Payment] RSA 签名异常: {e}")
        return ""


def generate_jsapi_pay_params(prepay_id: str) -> dict:
    """
    根据 prepay_id 生成前端拉起 JSAPI 支付所需的参数包及签名
    """
    timestamp = str(int(time.time()))
    nonce_str = secrets.token_hex(16)
    package_val = f"prepay_id={prepay_id}"

    if IS_MOCK_PAY:
        # Mock 模式下，虚拟签名直接返回一段 Mock 串
        return {
            "appId": APPID,
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": package_val,
            "signType": "RSA",
            "paySign": f"MOCK_SIGN_FOR_PREPAY_{prepay_id}_{timestamp}"
        }

    # 构造签名串
    sign_str = f"{APPID}\n{timestamp}\n{nonce_str}\n{package_val}\n"
    pay_sign = sign_sha256_with_rsa(sign_str)

    return {
        "appId": APPID,
        "timeStamp": timestamp,
        "nonceStr": nonce_str,
        "package": package_val,
        "signType": "RSA",
        "paySign": pay_sign
    }


def build_authorization_header(method: str, url_path: str, body: str = "") -> str:
    """
    构建微信支付 V3 API 请求的 Authorization 头
    """
    if IS_MOCK_PAY:
        return "MOCK_AUTH_HEADER"

    timestamp = str(int(time.time()))
    nonce_str = secrets.token_hex(16)

    # 构造签名串
    sign_str = f"{method}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n"
    signature = sign_sha256_with_rsa(sign_str)

    if not signature:
        logger.error("[Payment] 生成签名失败，无法构建 Authorization 头")
        return ""

    return (
        f'WECHATPAY2-SHA256-RSA2048 '
        f'mchid="{MCH_ID}",'
        f'nonce_str="{nonce_str}",'
        f'signature="{signature}",'
        f'timestamp="{timestamp}",'
        f'serial_no="{SERIAL_NO}"'
    )


def verify_wechat_signature(request: Request, body: bytes) -> bool:
    """
    验证微信支付回调通知的签名
    返回 True 表示验签通过
    """
    if IS_MOCK_PAY:
        return True

    try:
        # 获取微信签名相关头
        wechat_signature = request.headers.get("Wechatpay-Signature", "")
        wechat_timestamp = request.headers.get("Wechatpay-Timestamp", "")
        wechat_nonce = request.headers.get("Wechatpay-Nonce", "")
        wechat_serial = request.headers.get("Wechatpay-Serial", "")

        if not all([wechat_signature, wechat_timestamp, wechat_nonce, wechat_serial]):
            logger.error("[Payment] 回调通知缺少必要的签名头")
            return False

        # 验证平台证书序列号（可选，建议验证）
        if PLATFORM_CERT_SERIAL and wechat_serial != PLATFORM_CERT_SERIAL:
            logger.error(f"[Payment] 平台证书序列号不匹配: {wechat_serial} != {PLATFORM_CERT_SERIAL}")
            return False

        # 构造验签串
        body_str = body.decode('utf-8') if body else ""
        sign_str = f"{wechat_timestamp}\n{wechat_nonce}\n{body_str}\n"

        # 加载平台证书公钥进行验签
        # 注意：实际生产环境应缓存平台证书，此处简化处理
        platform_cert_path = os.getenv("WECHAT_PLATFORM_CERT_PATH", "")
        if not platform_cert_path:
            logger.error("[Payment] 未配置平台证书路径，无法验签")
            return False

        with open(platform_cert_path, 'rb') as f:
            cert_data = f.read()

        from cryptography import x509
        cert = x509.load_pem_x509_certificate(cert_data)
        public_key = cert.public_key()

        # 验证签名
        signature_bytes = base64.b64decode(wechat_signature)
        public_key.verify(
            signature_bytes,
            sign_str.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return True

    except Exception as e:
        logger.error(f"[Payment] 验签失败: {e}")
        return False


# ============================================================
# HTTP 请求工具
# ============================================================
async def _make_wechat_api_request(
    method: str,
    url_path: str,
    body: Optional[dict] = None
) -> Tuple[int, dict]:
    """
    发送微信支付 API 请求
    返回 (状态码, 响应数据)
    """
    if IS_MOCK_PAY:
        # Mock 模式返回模拟数据
        return _mock_api_response(method, url_path, body)

    base_url = "https://api.mch.weixin.qq.com"
    url = f"{base_url}{url_path}"

    body_str = json.dumps(body, ensure_ascii=False) if body else ""
    auth_header = build_authorization_header(method, url_path, body_str)

    if not auth_header:
        return 500, {"code": "SIGN_FAILED", "message": "签名生成失败"}

    headers = {
        "Authorization": auth_header,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "K12-Rocket/2.0"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, headers=headers, content=body_str)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                return 405, {"code": "METHOD_NOT_ALLOWED", "message": f"不支持的请求方法: {method}"}

            status_code = response.status_code
            try:
                resp_data = response.json()
            except json.JSONDecodeError:
                resp_data = {"raw_response": response.text}

            return status_code, resp_data

        except httpx.TimeoutException:
            logger.error(f"[Payment] 请求微信API超时: {method} {url_path}")
            return 504, {"code": "TIMEOUT", "message": "请求微信支付API超时"}
        except Exception as e:
            logger.error(f"[Payment] 请求微信API异常: {method} {url_path} - {e}")
            return 500, {"code": "REQUEST_FAILED", "message": str(e)}


def _mock_api_response(method: str, url_path: str, body: Optional[dict] = None) -> Tuple[int, dict]:
    """
    Mock 模式下模拟微信支付 API 响应
    """
    logger.info(f"[Payment Mock] {method} {url_path} - body: {body}")

    if "transactions/jsapi" in url_path and method == "POST":
        # 统一下单 Mock 响应
        prepay_id = f"mock_prepay_{secrets.token_hex(8)}"
        return 200, {
            "prepay_id": prepay_id,
            "code": "SUCCESS",
            "message": "模拟下单成功"
        }

    elif "refund" in url_path and method == "POST":
        # 退款 Mock 响应
        return 200, {
            "refund_id": f"mock_refund_{secrets.token_hex(8)}",
            "status": "SUCCESS",
            "code": "SUCCESS",
            "message": "模拟退款成功"
        }

    elif "out-trade-no" in url_path and method == "GET":
        # 订单查询 Mock 响应
        return 200, {
            "trade_state": "SUCCESS",
            "transaction_id": f"mock_trans_{secrets.token_hex(8)}",
            "code": "SUCCESS",
            "message": "模拟查询成功"
        }

    else:
        return 200, {
            "code": "SUCCESS",
            "message": "Mock 模式默认响应"
        }


# ============================================================
# 核心支付业务函数
# ============================================================
async def create_unified_order(order_req: UnifiedOrderRequest) -> PaymentResult:
    """
    微信支付统一下单（JSAPI）
    返回 prepay_id 及前端调起支付所需参数
    """
    try:
        # 构造请求参数
        body = {
            "appid": APPID,
            "mchid": MCH_ID,
            "description": order_req.description,
            "out_trade_no": order_req.out_trade_no,
            "notify_url": NOTIFY_URL,
            "amount": {
                "total": order_req.amount,
                "currency": "CNY"
            },
            "payer": {
                "openid": order_req.openid
            }
        }

        if order_req.attach:
            body["attach"] = order_req.attach
        if order_req.goods_tag:
            body["goods_tag"] = order_req.goods_tag

        # 调用微信支付 API
        status_code, resp_data = await _make_wechat_api_request("POST", "/v3/pay/transactions/jsapi", body)

        if status_code != 200:
            error_msg = resp_data.get("message", f"微信支付API返回异常状态码: {status_code}")
            logger.error(f"[Payment] 统一下单失败: {error_msg}")
            return PaymentResult(
                success=False,
                message=error_msg,
                data=resp_data
            )

        prepay_id = resp_data.get("prepay_id")
        if not prepay_id:
            logger.error(f"[Payment] 统一下单返回缺少 prepay_id: {resp_data}")
            return PaymentResult(
                success=False,
                message="统一下单返回缺少 prepay_id",
                data=resp_data
            )

        # 生成前端调起支付参数
        pay_params = generate_jsapi_pay_params(prepay_id)

        return PaymentResult(
            success=True,
            message="下单成功",
            data={
                "prepay_id": prepay_id,
                "pay_params": pay_params,
                "out_trade_no": order_req.out_trade_no
            }
        )

    except Exception as e:
        logger.error(f"[Payment] 统一下单异常: {e}")
        return PaymentResult(
            success=False,
            message=f"统一下单异常: {str(e)}"
        )


async def query_order(out_trade_no: str) -> PaymentResult:
    """
    查询订单支付状态
    """
    try:
        url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={MCH_ID}"
        status_code, resp_data = await _make_wechat_api_request("GET", url_path)

        if status_code != 200:
            error_msg = resp_data.get("message", f"订单查询返回异常状态码: {status_code}")
            logger.error(f"[Payment] 订单查询失败: {error_msg}")
            return PaymentResult(
                success=False,
                message=error_msg,
                data=resp_data
            )

        trade_state = resp_data.get("trade_state", "")
        trade_state_desc = resp_data.get("trade_state_desc", "")

        return PaymentResult(
            success=True,
            message="查询成功",
            data={
                "out_trade_no": out_trade_no,
                "trade_state": trade_state,
                "trade_state_desc": trade_state_desc,
                "transaction_id": resp_data.get("transaction_id", ""),
                "amount": resp_data.get("amount", {}).get("total", 0),
                "payer_total": resp_data.get("amount", {}).get("payer_total", 0),
                "success_time": resp_data.get("success_time", "")
            }
        )

    except Exception as e:
        logger.error(f"[Payment] 订单查询异常: {e}")
        return PaymentResult(
            success=False,
            message=f"订单查询异常: {str(e)}"
        )


async def close_order(out_trade_no: str) -> PaymentResult:
    """
    关闭订单
    """
    try:
        body = {
            "mchid": MCH_ID
        }
        url_path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}/close"
        status_code, resp_data = await _make_wechat_api_request("POST", url_path, body)

        if status_code not in [200, 204]:
            error_msg = resp_data.get("message", f"关闭订单返回异常状态码: {status_code}")
            logger.error(f"[Payment] 关闭订单失败: {error_msg}")
            return PaymentResult(
                success=False,
                message=error_msg,
                data=resp_data
            )

        return PaymentResult(
            success=True,
            message="订单关闭成功",
            data={"out_trade_no": out_trade_no}
        )

    except Exception as e:
        logger.error(f"[Payment] 关闭订单异常: {e}")
        return PaymentResult(
            success=False,
            message=f"关闭订单异常: {str(e)}"
        )


async def create_refund(refund_req: RefundRequest) -> PaymentResult:
    """
    申请退款
    """
    try:
        body = {
            "out_trade_no": refund_req.out_trade_no,
            "out_refund_no": refund_req.out_refund_no,
            "amount": {
                "refund": refund_req.amount,
                "total": refund_req.total_amount,
                "currency": "CNY"
            }
        }

        if refund_req.reason:
            body["reason"] = refund_req.reason

        status_code, resp_data = await _make_wechat_api_request("POST", "/v3/refund/domestic/refunds", body)

        if status_code != 200:
            error_msg = resp_data.get("message", f"申请退款返回异常状态码: {status_code}")
            logger.error(f"[Payment] 申请退款失败: {error_msg}")
            return PaymentResult(
                success=False,
                message=error_msg,
                data=resp_data
            )

        refund_status = resp_data.get("status", "")
        return PaymentResult(
            success=True,
            message="退款申请成功",
            data={
                "refund_id": resp_data.get("refund_id", ""),
                "out_refund_no": refund_req.out_refund_no,
                "status": refund_status,
                "amount": refund_req.amount
            }
        )

    except Exception as e:
        logger.error(f"[Payment] 申请退款异常: {e}")
        return PaymentResult(
            success=False,
            message=f"申请退款异常: {str(e)}"
        )


async def query_refund(out_refund_no: str) -> PaymentResult:
    """
    查询退款状态
    """
    try:
        url_path = f"/v3/refund/domestic/refunds/{out_refund_no}"
        status_code, resp_data = await _make_wechat_api_request("GET", url_path)

        if status_code != 200:
            error_msg = resp_data.get("message", f"查询退款返回异常状态码: {status_code}")
            logger.error(f"[Payment] 查询退款失败: {error_msg}")
            return PaymentResult(
                success=False,
                message=error_msg,
                data=resp_data
            )

        return PaymentResult(
            success=True,
            message="查询退款成功",
            data={
                "refund_id": resp_data.get("refund_id", ""),
                "out_refund_no": out_refund_no,
                "status": resp_data.get("status", ""),
                "amount": resp_data.get("amount", {}).get("refund", 0),
                "total_amount": resp_data.get("amount", {}).get("total", 0),
                "success_time": resp_data.get("success_time", "")
            }
        )

    except Exception as e:
        logger.error(f"[Payment] 查询退款异常: {e}")
        return PaymentResult(
            success=False,
            message=f"查询退款异常: {str(e)}"
        )


# ============================================================
# 回调通知处理
# ============================================================
async def handle_payment_notification(request: Request) -> Tuple[bool, dict]:
    """
    处理微信支付回调通知
    返回 (是否成功, 解析后的支付结果数据)
    """
    try:
        # 读取请求体
        body = await request.body()

        # 验证签名
        if not verify_wechat_signature(request, body):
            logger.error("[Payment] 回调通知验签失败")
            return False, {"code": "SIGN_VERIFY_FAILED", "message": "验签失败"}

        # 解析回调数据
        callback_data = json.loads(body.decode('utf-8'))

        # 解密 resource 字段
        resource = callback_data.get("resource", {})
        ciphertext = resource.get("ciphertext", "")
        nonce = resource.get("nonce", "")
        associated_data = resource.get("associated_data", "")

        if not ciphertext or not nonce:
            logger.error(f"[Payment] 回调通知缺少加密数据: {callback_data}")
            return False, {"code": "INVALID_RESOURCE", "message": "缺少加密数据"}

        decrypted_data = decrypt_wechat_resource(ciphertext, nonce, associated_data)
        if not decrypted_data:
            logger.error("[Payment] 回调通知解密失败")
            return False, {"code": "DECRYPT_FAILED", "message": "解密失败"}

        # 提取支付结果
        trade_state = decrypted_data.get("trade_state", "")
        out_trade_no = decrypted_data.get("out_trade_no", "")
        transaction_id = decrypted_data.get("transaction_id", "")
        success_time = decrypted_data.get("success_time", "")
        amount = decrypted_data.get("amount", {}).get("total", 0)
        payer_total = decrypted_data.get("amount", {}).get("payer_total", 0)
        attach = decrypted_data.get("attach", "")

        logger.info(f"[Payment] 收到支付回调: out_trade_no={out_trade_no}, trade_state={trade_state}")

        # 处理支付成功逻辑
        if trade_state == "SUCCESS":
            # 这里可以调用业务逻辑处理，如更新订单状态、增加用户配额等
            # 具体业务逻辑由调用方实现
            pass

        return True, {
            "out_trade_no": out_trade_no,
            "transaction_id": transaction_id,
            "trade_state": trade_state,
            "success_time": success_time,
            "amount": amount,
            "payer_total": payer_total,
            "attach": attach,
            "raw_data": decrypted_data
        }

    except json.JSONDecodeError as e:
        logger.error(f"[Payment] 回调通知JSON解析失败: {e}")
        return False, {"code": "JSON_PARSE_ERROR", "message": "JSON解析失败"}
    except Exception as e:
        logger.error(f"[Payment] 处理回调通知异常: {e}")
        return False, {"code": "PROCESS_ERROR", "message": str(e)}


# ============================================================
# 工具函数
# ============================================================
def generate_out_trade_no(prefix: str = "K12") -> str:
    """
    生成商户订单号
    格式: 前缀 + 时间戳 + 随机字符串
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = secrets.token_hex(4).upper()
    return f"{prefix}{timestamp}{random_str}"


def generate_refund_no(prefix: str = "RF") -> str:
    """
    生成退款单号
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = secrets.token_hex(4).upper()
    return f"{prefix}{timestamp}{random_str}"


def calculate_amount_by_plan(plan_type: PlanType) -> int:
    """
    根据套餐类型计算支付金额（单位：分）
    """
    price_map = {
        PlanType.FREE: 0,
        PlanType.BASIC: 9900,  # 99元
        PlanType.PREMIUM: 29900,  # 299元
        PlanType.ENTERPRISE: 99900,  # 999元
    }
    return price_map.get(plan_type, 0)


def calculate_amount_by_diagnosis_count(count: int) -> int:
    """
    根据诊断次数计算支付金额（单位：分）
    按次诊断计费方案
    """
    if count <= 0:
        return 0

    # 单价：每次诊断 9.9 元
    unit_price = 990  # 9.9元 = 990分

    # 阶梯优惠
    if count >= 50:
        # 50次以上 8折
        unit_price = int(unit_price * 0.8)
    elif count >= 20:
        # 20次以上 9折
        unit_price = int(unit_price * 0.9)
    elif count >= 10:
        # 10次以上 95折
        unit_price = int(unit_price * 0.95)

    return count * unit_price

# ============================================================
# 微信支付V3回调辅助接口 (对接 wechat_router.py)
# ============================================================

PAYMENT_SUCCESS = "SUCCESS"
PAYMENT_FAILED = "FAIL"

def verify_payment_signature(body: str, signature: str, timestamp: str, nonce: str, serial_no: str) -> bool:
    """验证微信支付回调的签名"""
    headers = {
        "Wechatpay-Signature": signature,
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": nonce,
        "Wechatpay-Serial": serial_no
    }
    from .wechat import _verify_v3_callback_signature
    return _verify_v3_callback_signature(headers, body)

def get_payment_config() -> dict:
    """获取微信支付配置"""
    return {
        "appId": os.getenv("WECHAT_APPID", ""),
        "mchId": os.getenv("WECHAT_MCHID", ""),
        "notifyUrl": os.getenv("WECHAT_NOTIFY_URL", "")
    }

def process_payment_notification(callback_data: dict) -> dict:
    """处理微信支付回调通知并更新数据库"""
    try:
        resource = callback_data.get("resource", {})
        ciphertext = resource.get("ciphertext", "")
        nonce = resource.get("nonce", "")
        associated_data = resource.get("associated_data", "")
        
        if not ciphertext or not nonce:
            logger.error("[Payment] Callback data missing resource/ciphertext/nonce")
            return {"status": PAYMENT_FAILED, "message": "Missing resource parameters"}
            
        decrypted = decrypt_wechat_resource(ciphertext, nonce, associated_data)
        if not decrypted:
            logger.error("[Payment] Failed to decrypt callback resource")
            return {"status": PAYMENT_FAILED, "message": "Decryption failed"}
            
        trade_state = decrypted.get("trade_state", "")
        out_trade_no = decrypted.get("out_trade_no", "")
        transaction_id = decrypted.get("transaction_id", "")
        
        logger.info(f"[Payment] Decrypted callback: out_trade_no={out_trade_no}, state={trade_state}")
        
        if trade_state == "SUCCESS" and out_trade_no:
            import sqlite3
            from pathlib import Path
            db_path = Path(__file__).parent.parent / "data" / "shengxuewa.db"
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            try:
                # 更新 orders 表
                cursor.execute("""
                    UPDATE orders 
                    SET status = 'paid', 
                        transaction_id = ?,
                        paid_at = CURRENT_TIMESTAMP
                    WHERE order_id = ? AND status = 'pending'
                """, (transaction_id, out_trade_no))
                
                # 如果没有更新到，可能是在 diagnosis_purchases 表中
                if cursor.rowcount == 0:
                    cursor.execute("""
                        UPDATE diagnosis_purchases 
                        SET status = 'paid', 
                            transaction_id = ?,
                            paid_at = CURRENT_TIMESTAMP
                        WHERE order_id = ? AND status = 'pending'
                    """, (transaction_id, out_trade_no))
                
                # 关联更新用户的额度 (增加用户的诊断次数)
                cursor.execute("SELECT user_id, diagnoses_count, valid_days FROM diagnosis_purchases WHERE order_id = ?", (out_trade_no,))
                row = cursor.fetchone()
                if row:
                    user_id, count, valid_days = row
                    cursor.execute("SELECT diagnoses_remaining FROM user_diagnoses WHERE user_id = ?", (user_id,))
                    diag_row = cursor.fetchone()
                    if diag_row:
                        cursor.execute("""
                            UPDATE user_diagnoses 
                            SET diagnoses_remaining = diagnoses_remaining + ?,
                                diagnoses_total = diagnoses_total + ?,
                                expires_at = date('now', '+' || ? || ' days')
                            WHERE user_id = ?
                        """, (count, count, valid_days, user_id))
                    else:
                        cursor.execute("""
                            INSERT INTO user_diagnoses (user_id, diagnoses_remaining, diagnoses_total, diagnoses_used, expires_at)
                            VALUES (?, ?, ?, 0, date('now', '+' || ? || ' days'))
                        """, (user_id, count, count, valid_days))
                
                conn.commit()
                logger.info(f"[Payment] Successfully processed payment for order {out_trade_no}")
                return {"status": PAYMENT_SUCCESS, "message": "Payment success processed"}
            except Exception as e:
                conn.rollback()
                logger.error(f"[Payment] Database error updating order {out_trade_no}: {e}")
                return {"status": PAYMENT_FAILED, "message": f"Database error: {e}"}
            finally:
                conn.close()
        else:
            logger.warning(f"[Payment] Callback status is not SUCCESS: {trade_state}")
            return {"status": PAYMENT_FAILED, "message": f"Trade state: {trade_state}"}
            
    except Exception as e:
        logger.error(f"[Payment] Error processing callback notify: {e}")
        return {"status": PAYMENT_FAILED, "message": str(e)}

