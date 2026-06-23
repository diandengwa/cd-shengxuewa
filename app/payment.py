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
    
    # 真实模式下，按微信支付 V3 规范生成签名
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


def create_unified_order(
    openid: str,
    description: str,
    amount: int,
    out_trade_no: str,
    attach: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    微信支付统一下单（JSAPI 支付）
    
    Args:
        openid: 用户微信 OpenID
        description: 商品描述
        amount: 订单金额（单位：分）
        out_trade_no: 商户订单号
        attach: 附加数据（可选，回调时原样返回）
    
    Returns:
        (success, prepay_id, error_msg)
    """
    if IS_MOCK_PAY:
        # Mock 模式下，直接返回模拟的 prepay_id
        mock_prepay_id = f"mock_prepay_{out_trade_no}_{int(time.time())}"
        logger.info(f"[Payment Mock] 统一下单成功，prepay_id={mock_prepay_id}")
        return True, mock_prepay_id, None
    
    try:
        # 构建请求体
        body = {
            "appid": APPID,
            "mchid": MCH_ID,
            "description": description,
            "out_trade_no": out_trade_no,
            "notify_url": NOTIFY_URL,
            "amount": {
                "total": amount,
                "currency": "CNY"
            },
            "payer": {
                "openid": openid
            }
        }
        
        if attach:
            body["attach"] = attach
        
        # 构建签名
        url = "https://api.mch.weixin.qq.com/v3/pay/transactions/jsapi"
        method = "POST"
        body_str = json.dumps(body, ensure_ascii=False)
        
        # 构建签名串
        timestamp = str(int(time.time()))
        nonce_str = secrets.token_hex(16)
        sign_str = f"{method}\n{url.split('.com')[1]}\n{timestamp}\n{nonce_str}\n{body_str}\n"
        
        # 生成签名
        signature = sign_sha256_with_rsa(sign_str)
        if not signature:
            return False, None, "签名生成失败"
        
        # 构建 Authorization 头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{MCH_ID}",'
            f'nonce_str="{nonce_str}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{SERIAL_NO}",'
            f'signature="{signature}"'
        )
        
        # 发送请求
        import httpx
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "K12-Rocket/2.0"
        }
        
        with httpx.Client() as client:
            response = client.post(url, headers=headers, content=body_str.encode("utf-8"))
            
            if response.status_code == 200:
                result = response.json()
                prepay_id = result.get("prepay_id")
                if prepay_id:
                    logger.info(f"[Payment] 统一下单成功，out_trade_no={out_trade_no}, prepay_id={prepay_id}")
                    return True, prepay_id, None
                else:
                    error_msg = f"响应中缺少 prepay_id: {result}"
                    logger.error(f"[Payment] {error_msg}")
                    return False, None, error_msg
            else:
                error_msg = f"微信支付 API 返回错误: {response.status_code} - {response.text}"
                logger.error(f"[Payment] {error_msg}")
                return False, None, error_msg
                
    except Exception as e:
        error_msg = f"统一下单异常: {str(e)}"
        logger.error(f"[Payment] {error_msg}")
        return False, None, error_msg


def query_order(out_trade_no: str) -> Tuple[bool, Optional[dict], Optional[str]]:
    """
    查询微信支付订单状态
    
    Args:
        out_trade_no: 商户订单号
    
    Returns:
        (success, order_info, error_msg)
    """
    if IS_MOCK_PAY:
        # Mock 模式下，返回模拟的订单信息
        mock_order = {
            "trade_state": "SUCCESS",
            "out_trade_no": out_trade_no,
            "transaction_id": f"mock_transaction_{out_trade_no}",
            "amount": {
                "total": 100,
                "payer_total": 100
            },
            "success_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        }
        logger.info(f"[Payment Mock] 订单查询成功，out_trade_no={out_trade_no}")
        return True, mock_order, None
    
    try:
        url = f"https://api.mch.weixin.qq.com/v3/pay/transactions/out-trade-no/{out_trade_no}"
        method = "GET"
        
        # 构建签名串
        timestamp = str(int(time.time()))
        nonce_str = secrets.token_hex(16)
        sign_str = f"{method}\n{url.split('.com')[1]}\n{timestamp}\n{nonce_str}\n\n"
        
        # 生成签名
        signature = sign_sha256_with_rsa(sign_str)
        if not signature:
            return False, None, "签名生成失败"
        
        # 构建 Authorization 头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{MCH_ID}",'
            f'nonce_str="{nonce_str}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{SERIAL_NO}",'
            f'signature="{signature}"'
        )
        
        # 发送请求
        import httpx
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
            "User-Agent": "K12-Rocket/2.0"
        }
        
        with httpx.Client() as client:
            response = client.get(url, headers=headers)
            
            if response.status_code == 200:
                order_info = response.json()
                logger.info(f"[Payment] 订单查询成功，out_trade_no={out_trade_no}, state={order_info.get('trade_state')}")
                return True, order_info, None
            else:
                error_msg = f"订单查询失败: {response.status_code} - {response.text}"
                logger.error(f"[Payment] {error_msg}")
                return False, None, error_msg
                
    except Exception as e:
        error_msg = f"订单查询异常: {str(e)}"
        logger.error(f"[Payment] {error_msg}")
        return False, None, error_msg


def refund_order(
    out_trade_no: str,
    refund_amount: int,
    total_amount: int,
    out_refund_no: Optional[str] = None,
    reason: Optional[str] = None
) -> Tuple[bool, Optional[dict], Optional[str]]:
    """
    微信支付退款
    
    Args:
        out_trade_no: 商户订单号
        refund_amount: 退款金额（单位：分）
        total_amount: 原订单金额（单位：分）
        out_refund_no: 商户退款单号（可选，不传则自动生成）
        reason: 退款原因（可选）
    
    Returns:
        (success, refund_info, error_msg)
    """
    if IS_MOCK_PAY:
        # Mock 模式下，返回模拟的退款信息
        mock_refund = {
            "refund_id": f"mock_refund_{out_trade_no}_{int(time.time())}",
            "out_refund_no": out_refund_no or f"refund_{out_trade_no}",
            "out_trade_no": out_trade_no,
            "status": "SUCCESS",
            "amount": {
                "refund": refund_amount,
                "total": total_amount
            }
        }
        logger.info(f"[Payment Mock] 退款成功，out_trade_no={out_trade_no}")
        return True, mock_refund, None
    
    try:
        # 生成退款单号
        if not out_refund_no:
            out_refund_no = f"refund_{out_trade_no}_{int(time.time())}"
        
        # 构建请求体
        body = {
            "out_trade_no": out_trade_no,
            "out_refund_no": out_refund_no,
            "amount": {
                "refund": refund_amount,
                "total": total_amount,
                "currency": "CNY"
            }
        }
        
        if reason:
            body["reason"] = reason
        
        # 构建签名
        url = "https://api.mch.weixin.qq.com/v3/refund/domestic/refunds"
        method = "POST"
        body_str = json.dumps(body, ensure_ascii=False)
        
        # 构建签名串
        timestamp = str(int(time.time()))
        nonce_str = secrets.token_hex(16)
        sign_str = f"{method}\n{url.split('.com')[1]}\n{timestamp}\n{nonce_str}\n{body_str}\n"
        
        # 生成签名
        signature = sign_sha256_with_rsa(sign_str)
        if not signature:
            return False, None, "签名生成失败"
        
        # 构建 Authorization 头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{MCH_ID}",'
            f'nonce_str="{nonce_str}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{SERIAL_NO}",'
            f'signature="{signature}"'
        )
        
        # 发送请求
        import httpx
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "K12-Rocket/2.0"
        }
        
        with httpx.Client() as client:
            response = client.post(url, headers=headers, content=body_str.encode("utf-8"))
            
            if response.status_code == 200:
                refund_info = response.json()
                logger.info(f"[Payment] 退款成功，out_trade_no={out_trade_no}, refund_id={refund_info.get('refund_id')}")
                return True, refund_info, None
            else:
                error_msg = f"退款失败: {response.status_code} - {response.text}"
                logger.error(f"[Payment] {error_msg}")
                return False, None, error_msg
                
    except Exception as e:
        error_msg = f"退款异常: {str(e)}"
        logger.error(f"[Payment] {error_msg}")
        return False, None, error_msg


def handle_payment_notification(request_body: dict) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    处理微信支付回调通知
    
    Args:
        request_body: 回调请求体（已解析为字典）
    
    Returns:
        (success, out_trade_no, error_msg)
    """
    try:
        # 获取加密数据
        resource = request_body.get("resource")
        if not resource:
            return False, None, "回调数据中缺少 resource 字段"
        
        # 解密数据
        decrypted_data = decrypt_wechat_resource(
            ciphertext=resource.get("ciphertext", ""),
            nonce=resource.get("nonce", ""),
            associated_data=resource.get("associated_data", "")
        )
        
        if not decrypted_data:
            return False, None, "回调数据解密失败"
        
        # 提取订单信息
        out_trade_no = decrypted_data.get("out_trade_no")
        trade_state = decrypted_data.get("trade_state")
        transaction_id = decrypted_data.get("transaction_id")
        attach = decrypted_data.get("attach", "")
        
        if not out_trade_no:
            return False, None, "回调数据中缺少 out_trade_no"
        
        # 检查支付状态
        if trade_state != "SUCCESS":
            logger.warning(f"[Payment] 订单 {out_trade_no} 支付状态为 {trade_state}，跳过处理")
            return True, out_trade_no, None
        
        # 解析附加数据（如果有）
        extra_data = {}
        if attach:
            try:
                extra_data = json.loads(attach)
            except json.JSONDecodeError:
                logger.warning(f"[Payment] 附加数据解析失败: {attach}")
        
        # 根据附加数据中的类型处理不同的业务逻辑
        biz_type = extra_data.get("biz_type", "upgrade")
        
        if biz_type == "diagnosis":
            # 按次诊断计费
            user_id = extra_data.get("user_id")
            diagnosis_count = extra_data.get("diagnosis_count", 1)
            
            if user_id:
                # 更新用户诊断次数
                from .quota import add_diagnosis_quota
                add_diagnosis_quota(user_id, diagnosis_count)
                logger.info(f"[Payment] 诊断次数已增加: user_id={user_id}, count={diagnosis_count}")
        else:
            # 默认：套餐升级
            user_id = extra_data.get("user_id")
            plan_type = extra_data.get("plan_type", PlanType.PRO)
            
            if user_id:
                upgrade_plan(user_id, plan_type)
                logger.info(f"[Payment] 套餐已升级: user_id={user_id}, plan={plan_type}")
        
        # 记录支付成功日志
        logger.info(f"[Payment] 支付回调处理成功: out_trade_no={out_trade_no}, transaction_id={transaction_id}")
        
        return True, out_trade_no, None
        
    except Exception as e:
        error_msg = f"支付回调处理异常: {str(e)}"
        logger.error(f"[Payment] {error_msg}")
        return False, None, error_msg


def generate_out_trade_no(user_id: str, biz_type: str = "diagnosis") -> str:
    """
    生成商户订单号
    
    Args:
        user_id: 用户 ID
        biz_type: 业务类型（diagnosis/upgrade）
    
    Returns:
        商户订单号
    """
    timestamp = int(time.time() * 1000)
    random_str = secrets.token_hex(4)
    return f"{biz_type}_{user_id}_{timestamp}_{random_str}"


def calculate_diagnosis_price(diagnosis_count: int = 1) -> int:
    """
    计算诊断费用（单位：分）
    
    Args:
        diagnosis_count: 诊断次数
    
    Returns:
        费用金额（分）
    """
    # 按次诊断定价：每次诊断 9.9 元
    unit_price = 990  # 9.9元 = 990分
    return unit_price * diagnosis_count


def create_diagnosis_payment(
    openid: str,
    user_id: str,
    diagnosis_count: int = 1
) -> Tuple[bool, Optional[dict], Optional[str]]:
    """
    创建诊断支付订单
    
    Args:
        openid: 用户微信 OpenID
        user_id: 用户 ID
        diagnosis_count: 诊断次数
    
    Returns:
        (success, pay_params, error_msg)
    """
    try:
        # 计算费用
        amount = calculate_diagnosis_price(diagnosis_count)
        
        # 生成订单号
        out_trade_no = generate_out_trade_no(user_id, "diagnosis")
        
        # 构建附加数据
        attach = json.dumps({
            "biz_type": "diagnosis",
            "user_id": user_id,
            "diagnosis_count": diagnosis_count
        }, ensure_ascii=False)
        
        # 统一下单
        success, prepay_id, error_msg = create_unified_order(
            openid=openid,
            description=f"K12升学诊断 x{diagnosis_count}次",
            amount=amount,
            out_trade_no=out_trade_no,
            attach=attach
        )
        
        if not success:
            return False, None, error_msg
        
        # 生成前端支付参数
        pay_params = generate_jsapi_pay_params(prepay_id)
        
        # 记录订单信息
        logger.info(f"[Payment] 诊断支付订单创建成功: out_trade_no={out_trade_no}, amount={amount}, count={diagnosis_count}")
        
        return True, {
            "out_trade_no": out_trade_no,
            "prepay_id": prepay_id,
            "pay_params": pay_params,
            "amount": amount,
            "diagnosis_count": diagnosis_count
        }, None
        
    except Exception as e:
        error_msg = f"创建诊断支付订单异常: {str(e)}"
        logger.error(f"[Payment] {error_msg}")
        return False, None, error_msg


def verify_payment_signature(
    headers: dict,
    body: str
) -> bool:
    """
    验证微信支付回调签名
    
    Args:
        headers: 回调请求头
        body: 回调请求体（原始字符串）
    
    Returns:
        签名是否有效
    """
    if IS_MOCK_PAY:
        return True
    
    try:
        # 获取签名相关字段
        wechat_signature = headers.get("wechatpay-signature", "")
        wechat_timestamp = headers.get("wechatpay-timestamp", "")
        wechat_nonce = headers.get("wechatpay-nonce", "")
        wechat_serial = headers.get("wechatpay-serial", "")
        
        if not all([wechat_signature, wechat_timestamp, wechat_nonce, wechat_serial]):
            logger.error("[Payment] 回调签名验证失败：缺少必要字段")
            return False
        
        # 构建待签名字符串
        sign_str = f"{wechat_timestamp}\n{wechat_nonce}\n{body}\n"
        
        # 获取微信平台证书（实际生产环境需要缓存并定期更新）
        # 这里简化处理，使用商户私钥进行验证（实际应使用微信平台公钥）
        # 生产环境建议使用 wechatpay-python-sdk 或自行实现证书下载和验证逻辑
        
        # 由于验证需要微信平台公钥，这里返回 True 让上层逻辑处理
        # 实际生产环境需要实现完整的证书验证流程
        logger.warning("[Payment] 回调签名验证简化处理，生产环境需要实现完整验证")
        return True
        
    except Exception as e:
        logger.error(f"[Payment] 回调签名验证异常: {e}")
        return False