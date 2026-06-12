import os
import time
import base64
import json
import secrets
import logging
from typing import Optional, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from .models import PlanType
from .invite_codes import confirm_order
from .quota import upgrade_plan, get_or_create_user

logger = logging.getLogger("k12_rocket.payment")

# 微信支付 V3 商户配置
MCH_ID = os.getenv("WECHAT_MCH_ID", "")
SERIAL_NO = os.getenv("WECHAT_PAY_SERIAL_NO", "")
API_KEY = os.getenv("WECHAT_PAY_API_KEY", "")  # APIv3 密钥 (32字节)
PRIVATE_KEY_VAL = os.getenv("WECHAT_PAY_PRIVATE_KEY", "") # 商户 API 私钥文本 (PEM)
NOTIFY_URL = os.getenv("WECHAT_PAY_NOTIFY_URL", "")

# 判断是否启用 Mock 模式：若没有配置证书或私钥，系统自动进入 Mock 模式运行以供测试
IS_MOCK_PAY = (not MCH_ID or not SERIAL_NO or not API_KEY or not PRIVATE_KEY_VAL)

APPID = os.getenv("WECHAT_APPID", "")
if not APPID and not IS_MOCK_PAY:
    raise ValueError("CRITICAL: WECHAT_APPID environment variable is not set! Server refuses to start in real payment mode.")

if IS_MOCK_PAY:
    logger.warning("[Payment] 微信支付未配齐真实商户密钥，系统已进入 Mock 模式运行。")
else:
    logger.info("[Payment] 微信支付商户证书载入成功，以真实模式运行。")


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
    """从文本加载商户私钥"""
    try:
        pem_data = PRIVATE_KEY_VAL.replace("\\n", "\n").encode("utf-8")
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
            "paySign": f"MOCK_SIGN_FOR_PREPAY_{prepay_id}_{timestamp}",
            "is_mock": True
        }
        
    # 真实模式：计算签名
    message = f"{APPID}\n{timestamp}\n{nonce_str}\n{package_val}\n"
    pay_sign = sign_sha256_with_rsa(message)
    
    return {
        "appId": APPID,
        "timeStamp": timestamp,
        "nonceStr": nonce_str,
        "package": package_val,
        "signType": "RSA",
        "paySign": pay_sign,
        "is_mock": False
    }


async def wechat_prepay_order(order_id: str, plan_val: str, amount_yuan: float, openid: str) -> Tuple[bool, dict]:
    """
    向微信支付创建预支付交易（如果 Mock 模式则直接生成并返回 Mock 参数）
    """
    if IS_MOCK_PAY:
        prepay_id = f"prepay_{secrets.token_hex(8)}"
        pay_params = generate_jsapi_pay_params(prepay_id)
        return True, {
            "prepay_id": prepay_id,
            "pay_params": pay_params,
            "order_id": order_id,
            "amount": amount_yuan,
            "is_mock": True
        }
        
    # 真实下单逻辑
    import httpx
    amount_fen = int(amount_yuan * 100)
    url = "https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi"
    
    payload = {
        "appid": APPID,
        "mchid": MCH_ID,
        "description": f"点灯蛙升学参谋 - {plan_val}版",
        "out_trade_no": order_id,
        "notify_url": NOTIFY_URL,
        "amount": {
            "total": amount_fen,
            "currency": "CNY"
        },
        "payer": {
            "openid": openid
        }
    }
    
    body_str = json.dumps(payload, ensure_ascii=False)
    timestamp = str(int(time.time()))
    nonce_str = secrets.token_hex(16)
    
    # 构造微信支付 V3 请求签名
    # 格式：Method\nPath+Query\nTimestamp\nNonce\nBody\n
    path_query = "/v3/pay/transactions/jsapi"
    message = f"POST\n{path_query}\n{timestamp}\n{nonce_str}\n{body_str}\n"
    signature = sign_sha256_with_rsa(message)
    
    if not signature:
        logger.error("[Payment] 下单签名计算失败，回退为 Mock 参数")
        prepay_id = f"prepay_err_mock_{secrets.token_hex(8)}"
        return False, {"prepay_id": prepay_id, "pay_params": generate_jsapi_pay_params(prepay_id), "is_mock": True}
        
    auth_header = f'WECHATPAY2-SHA256-RSA2048 mchid="{MCH_ID}",nonce_str="{nonce_str}",signature="{signature}",timestamp="{timestamp}",serial_no="{SERIAL_NO}"'
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                content=body_str,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "FastAPI-WeChatPay-V2.0"
                }
            )
            
            data = resp.json()
            if resp.status_code == 200 and "prepay_id" in data:
                prepay_id = data["prepay_id"]
                pay_params = generate_jsapi_pay_params(prepay_id)
                logger.info(f"[Payment] 微信下单成功: order_id={order_id}, prepay_id={prepay_id}")
                return True, {
                    "prepay_id": prepay_id,
                    "pay_params": pay_params,
                    "order_id": order_id,
                    "amount": amount_yuan,
                    "is_mock": False
                }
            else:
                logger.error(f"[Payment] 微信下单失败: status={resp.status_code}, data={data}")
                return False, {"message": f"微信下单错误: {data.get('message', '未知错误')}"}
    except Exception as e:
        logger.error(f"[Payment] 微信下单接口请求异常: {e}")
        return False, {"message": f"连接微信接口异常: {str(e)}"}


def handle_payment_success(order_id: str, transaction_id: str) -> Tuple[bool, str]:
    """
    处理付款成功：标记订单已付款 → 并直接在后台升级用户套餐（自动化发货）
    """
    # 1. 确认付款（会在订单中生成邀请码）
    success, msg, invite_code = confirm_order(order_id, admin_note=f"微信支付流水:{transaction_id}")
    if not success:
        logger.warning(f"[Payment] confirm_order 失败: order_id={order_id}, msg={msg}")
        return False, msg
        
    # 2. 读取订单的 openid 与 plan，自动发货升级
    from .invite_codes import _load_orders
    orders = _load_orders()
    order = orders.get(order_id)
    if not order:
        return False, "订单未找到"
        
    openid = order.get("openid")
    plan_str = order.get("plan")
    
    if openid and plan_str:
        try:
            plan = PlanType(plan_str)
            upgrade_plan(openid, plan)
            logger.info(f"[Payment] 【自动化发货成功】已为用户 {openid[:8]}... 升级套餐至 {plan.value}，订单={order_id}")
            return True, f"支付确认成功且自动发货升级完成，套餐={plan.value}"
        except Exception as e:
            logger.error(f"[Payment] 自动发货升级 Plan 发生异常: {e}")
            return True, f"支付确认成功，但自动升级 Plan 失败，请用户凭邀请码 {invite_code} 手动激活: {str(e)}"
            
    return True, f"支付确认成功，邀请码已生成: {invite_code}（但未绑定openid）"
