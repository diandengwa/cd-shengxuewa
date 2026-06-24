#!/usr/bin/env python3
"""
支付服务层：微信支付V3统一下单、回调处理、订单查询、credits充值逻辑
按次诊断计费方案 — 成都K12升学参谋
"""

import os
import json
import time
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import Request, HTTPException
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from app.core.config import settings
from app.core.database import get_db_connection
from app.models.payment import PaymentOrder, PaymentRecord, CreditTransaction

logger = logging.getLogger(__name__)

# ============================================================
# 微信支付V3 常量
# ============================================================
WECHAT_API_BASE = "https://api.mch.weixin.qq.com/v3"
WECHAT_PAY_API_BASE = "https://api.mch.weixin.qq.com/v3/pay"
WECHAT_REFUND_API_BASE = "https://api.mch.weixin.qq.com/v3/refund"

# 支付状态
PAY_STATUS_PENDING = "pending"
PAY_STATUS_SUCCESS = "success"
PAY_STATUS_FAILED = "failed"
PAY_STATUS_REFUND = "refund"

# 交易类型
TRADE_TYPE_JSAPI = "JSAPI"
TRADE_TYPE_NATIVE = "NATIVE"
TRADE_TYPE_APP = "APP"
TRADE_TYPE_MWEB = "MWEB"

# 计费方案常量
DIAGNOSIS_PRICE = Decimal("9.90")  # 单次诊断价格（元）
DIAGNOSIS_CREDITS = 1  # 每次诊断消耗的credits数量
CREDITS_PER_PAY = 1  # 每次支付获得的credits数量


class WeChatPayV3Service:
    """微信支付V3服务类"""

    def __init__(self):
        """初始化微信支付V3配置"""
        self.app_id = settings.WECHAT_APP_ID
        self.mch_id = settings.WECHAT_MCH_ID
        self.api_key = settings.WECHAT_API_KEY
        self.api_v3_key = settings.WECHAT_API_V3_KEY
        self.notify_url = settings.WECHAT_NOTIFY_URL
        self.refund_notify_url = settings.WECHAT_REFUND_NOTIFY_URL
        
        # 加载商户证书
        self._load_certificates()
        
        # 初始化HTTP客户端
        self.client = httpx.AsyncClient(
            base_url=WECHAT_API_BASE,
            timeout=30.0,
            verify=True
        )

    def _load_certificates(self):
        """加载微信支付商户证书"""
        try:
            cert_path = settings.WECHAT_CERT_PATH
            key_path = settings.WECHAT_KEY_PATH
            
            if not os.path.exists(cert_path) or not os.path.exists(key_path):
                logger.warning("微信支付证书文件不存在，请检查配置")
                self.private_key = None
                self.certificate = None
                return
            
            with open(key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None,
                    backend=default_backend()
                )
            
            with open(cert_path, "rb") as f:
                self.certificate = f.read()
                
            logger.info("微信支付证书加载成功")
        except Exception as e:
            logger.error(f"加载微信支付证书失败: {e}")
            self.private_key = None
            self.certificate = None

    def _generate_nonce_str(self) -> str:
        """生成随机字符串"""
        return secrets.token_hex(16)

    def _generate_timestamp(self) -> str:
        """生成时间戳"""
        return str(int(time.time()))

    def _build_signature(self, method: str, url: str, body: str = "") -> str:
        """构建签名
        
        Args:
            method: HTTP方法（GET/POST）
            url: 请求URL（不含base_url）
            body: 请求体JSON字符串
            
        Returns:
            签名字符串
        """
        if self.private_key is None:
            raise ValueError("商户私钥未加载")
            
        nonce = self._generate_nonce_str()
        timestamp = self._generate_timestamp()
        
        # 构建签名串
        sign_str = f"{method}\n{url}\n{timestamp}\n{nonce}\n{body}\n"
        
        # 使用私钥签名
        signature = self.private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        return base64.b64encode(signature).decode("utf-8")

    def _build_authorization_header(self, method: str, url: str, body: str = "") -> Dict[str, str]:
        """构建请求头中的Authorization
        
        Args:
            method: HTTP方法
            url: 请求URL
            body: 请求体
            
        Returns:
            包含Authorization的请求头字典
        """
        nonce = self._generate_nonce_str()
        timestamp = self._generate_timestamp()
        signature = self._build_signature(method, url, body)
        
        auth_str = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self.mch_id}",'
            f'nonce_str="{nonce}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self._get_cert_serial_no()}",'
            f'signature="{signature}"'
        )
        
        return {
            "Authorization": auth_str,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _get_cert_serial_no(self) -> str:
        """获取证书序列号"""
        if self.certificate is None:
            raise ValueError("商户证书未加载")
        
        from cryptography.x509 import load_pem_x509_certificate
        cert = load_pem_x509_certificate(self.certificate, default_backend())
        return format(cert.serial_number, 'x')

    async def create_jsapi_order(self, openid: str, out_trade_no: str, total_fee: int, description: str) -> Dict[str, Any]:
        """创建JSAPI支付订单
        
        Args:
            openid: 用户微信openid
            out_trade_no: 商户订单号
            total_fee: 订单金额（分）
            description: 商品描述
            
        Returns:
            包含prepay_id的响应数据
        """
        url = "/pay/transactions/jsapi"
        body = {
            "appid": self.app_id,
            "mchid": self.mch_id,
            "description": description,
            "out_trade_no": out_trade_no,
            "notify_url": self.notify_url,
            "amount": {
                "total": total_fee,
                "currency": "CNY"
            },
            "payer": {
                "openid": openid
            }
        }
        
        body_str = json.dumps(body, ensure_ascii=False)
        headers = self._build_authorization_header("POST", url, body_str)
        
        try:
            response = await self.client.post(url, headers=headers, content=body_str)
            response.raise_for_status()
            result = response.json()
            logger.info(f"创建JSAPI订单成功: {out_trade_no}")
            return result
        except httpx.HTTPError as e:
            logger.error(f"创建JSAPI订单失败: {e}")
            raise HTTPException(status_code=500, detail="创建支付订单失败")

    async def create_native_order(self, out_trade_no: str, total_fee: int, description: str) -> Dict[str, Any]:
        """创建NATIVE支付订单（扫码支付）
        
        Args:
            out_trade_no: 商户订单号
            total_fee: 订单金额（分）
            description: 商品描述
            
        Returns:
            包含code_url的响应数据
        """
        url = "/pay/transactions/native"
        body = {
            "appid": self.app_id,
            "mchid": self.mch_id,
            "description": description,
            "out_trade_no": out_trade_no,
            "notify_url": self.notify_url,
            "amount": {
                "total": total_fee,
                "currency": "CNY"
            }
        }
        
        body_str = json.dumps(body, ensure_ascii=False)
        headers = self._build_authorization_header("POST", url, body_str)
        
        try:
            response = await self.client.post(url, headers=headers, content=body_str)
            response.raise_for_status()
            result = response.json()
            logger.info(f"创建NATIVE订单成功: {out_trade_no}")
            return result
        except httpx.HTTPError as e:
            logger.error(f"创建NATIVE订单失败: {e}")
            raise HTTPException(status_code=500, detail="创建支付订单失败")

    async def query_order(self, out_trade_no: str) -> Dict[str, Any]:
        """查询订单状态
        
        Args:
            out_trade_no: 商户订单号
            
        Returns:
            订单查询结果
        """
        url = f"/pay/transactions/out-trade-no/{out_trade_no}?mchid={self.mch_id}"
        headers = self._build_authorization_header("GET", url)
        
        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"查询订单失败: {e}")
            raise HTTPException(status_code=500, detail="查询订单失败")

    async def close_order(self, out_trade_no: str) -> bool:
        """关闭订单
        
        Args:
            out_trade_no: 商户订单号
            
        Returns:
            是否关闭成功
        """
        url = f"/pay/transactions/out-trade-no/{out_trade_no}/close"
        body = {
            "mchid": self.mch_id
        }
        
        body_str = json.dumps(body)
        headers = self._build_authorization_header("POST", url, body_str)
        
        try:
            response = await self.client.post(url, headers=headers, content=body_str)
            response.raise_for_status()
            logger.info(f"关闭订单成功: {out_trade_no}")
            return True
        except httpx.HTTPError as e:
            logger.error(f"关闭订单失败: {e}")
            return False

    async def refund_order(self, out_trade_no: str, refund_no: str, refund_fee: int, total_fee: int, reason: str = "") -> Dict[str, Any]:
        """申请退款
        
        Args:
            out_trade_no: 商户订单号
            refund_no: 商户退款单号
            refund_fee: 退款金额（分）
            total_fee: 原订单金额（分）
            reason: 退款原因
            
        Returns:
            退款申请结果
        """
        url = "/refund/domestic/refunds"
        body = {
            "out_trade_no": out_trade_no,
            "out_refund_no": refund_no,
            "reason": reason,
            "notify_url": self.refund_notify_url,
            "amount": {
                "refund": refund_fee,
                "total": total_fee,
                "currency": "CNY"
            }
        }
        
        body_str = json.dumps(body, ensure_ascii=False)
        headers = self._build_authorization_header("POST", url, body_str)
        
        try:
            response = await self.client.post(url, headers=headers, content=body_str)
            response.raise_for_status()
            result = response.json()
            logger.info(f"申请退款成功: {refund_no}")
            return result
        except httpx.HTTPError as e:
            logger.error(f"申请退款失败: {e}")
            raise HTTPException(status_code=500, detail="申请退款失败")

    async def verify_payment_notification(self, request: Request) -> Dict[str, Any]:
        """验证支付回调通知
        
        Args:
            request: FastAPI请求对象
            
        Returns:
            解密后的回调数据
        """
        # 获取请求头中的签名信息
        wechatpay_signature = request.headers.get("Wechatpay-Signature")
        wechatpay_serial = request.headers.get("Wechatpay-Serial")
        wechatpay_timestamp = request.headers.get("Wechatpay-Timestamp")
        wechatpay_nonce = request.headers.get("Wechatpay-Nonce")
        
        if not all([wechatpay_signature, wechatpay_serial, wechatpay_timestamp, wechatpay_nonce]):
            raise HTTPException(status_code=400, detail="缺少必要的回调签名信息")
        
        # 读取请求体
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # 构建验签串
        sign_str = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body_str}\n"
        
        # 获取平台证书
        platform_cert = await self._get_platform_certificate(wechatpay_serial)
        if platform_cert is None:
            raise HTTPException(status_code=400, detail="无法获取平台证书")
        
        # 验证签名
        try:
            from cryptography.x509 import load_pem_x509_certificate
            cert = load_pem_x509_certificate(platform_cert.encode("utf-8"), default_backend())
            public_key = cert.public_key()
            
            public_key.verify(
                base64.b64decode(wechatpay_signature),
                sign_str.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception as e:
            logger.error(f"回调签名验证失败: {e}")
            raise HTTPException(status_code=400, detail="回调签名验证失败")
        
        # 解密数据
        try:
            decrypted_data = self._decrypt_notification_data(json.loads(body_str))
            return decrypted_data
        except Exception as e:
            logger.error(f"回调数据解密失败: {e}")
            raise HTTPException(status_code=400, detail="回调数据解密失败")

    async def _get_platform_certificate(self, serial_no: str) -> Optional[str]:
        """获取微信支付平台证书
        
        Args:
            serial_no: 证书序列号
            
        Returns:
            证书内容
        """
        # 先从缓存获取
        cert_cache = getattr(self, '_cert_cache', {})
        if serial_no in cert_cache:
            return cert_cache[serial_no]
        
        # 从微信服务器获取
        url = "/certificates"
        headers = self._build_authorization_header("GET", url)
        
        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            for cert_info in result.get("data", []):
                if cert_info.get("serial_no") == serial_no:
                    # 解密证书内容
                    encrypted_cert = cert_info.get("encrypt_certificate", {})
                    cert_content = self._decrypt_certificate(encrypted_cert)
                    
                    # 缓存证书
                    if not hasattr(self, '_cert_cache'):
                        self._cert_cache = {}
                    self._cert_cache[serial_no] = cert_content
                    
                    return cert_content
            
            logger.warning(f"未找到序列号为 {serial_no} 的平台证书")
            return None
        except httpx.HTTPError as e:
            logger.error(f"获取平台证书失败: {e}")
            return None

    def _decrypt_certificate(self, encrypted_cert: Dict[str, str]) -> str:
        """解密平台证书
        
        Args:
            encrypted_cert: 加密的证书信息
            
        Returns:
            解密后的证书内容
        """
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        algorithm = encrypted_cert.get("algorithm", "AEAD_AES_256_GCM")
        nonce = encrypted_cert.get("nonce", "")
        associated_data = encrypted_cert.get("associated_data", "")
        ciphertext = encrypted_cert.get("ciphertext", "")
        
        if algorithm != "AEAD_AES_256_GCM":
            raise ValueError(f"不支持的加密算法: {algorithm}")
        
        # 使用API v3密钥解密
        key = self.api_v3_key.encode("utf-8")
        if len(key) != 32:
            key = hashlib.sha256(key).digest()
        
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(
            base64.b64decode(nonce),
            base64.b64decode(ciphertext) + base64.b64decode(associated_data),
            associated_data.encode("utf-8")
        )
        
        return plaintext.decode("utf-8")

    def _decrypt_notification_data(self, notification: Dict[str, Any]) -> Dict[str, Any]:
        """解密回调通知中的敏感数据
        
        Args:
            notification: 回调通知数据
            
        Returns:
            解密后的数据
        """
        resource = notification.get("resource", {})
        algorithm = resource.get("algorithm", "AEAD_AES_256_GCM")
        nonce = resource.get("nonce", "")
        associated_data = resource.get("associated_data", "")
        ciphertext = resource.get("ciphertext", "")
        
        if algorithm != "AEAD_AES_256_GCM":
            raise ValueError(f"不支持的加密算法: {algorithm}")
        
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        # 使用API v3密钥解密
        key = self.api_v3_key.encode("utf-8")
        if len(key) != 32:
            key = hashlib.sha256(key).digest()
        
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(
            base64.b64decode(nonce),
            base64.b64decode(ciphertext) + base64.b64decode(associated_data),
            associated_data.encode("utf-8")
        )
        
        return json.loads(plaintext.decode("utf-8"))

    async def process_payment_success(self, out_trade_no: str, transaction_id: str, total_fee: int, payer_openid: str) -> bool:
        """处理支付成功逻辑
        
        Args:
            out_trade_no: 商户订单号
            transaction_id: 微信支付订单号
            total_fee: 支付金额（分）
            payer_openid: 支付者openid
            
        Returns:
            是否处理成功
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询订单
            cursor.execute(
                "SELECT id, user_id, status, amount, credits FROM payment_orders WHERE out_trade_no = ?",
                (out_trade_no,)
            )
            order = cursor.fetchone()
            
            if not order:
                logger.error(f"订单不存在: {out_trade_no}")
                return False
            
            if order["status"] == PAY_STATUS_SUCCESS:
                logger.warning(f"订单已支付成功: {out_trade_no}")
                return True
            
            # 更新订单状态
            cursor.execute(
                """UPDATE payment_orders 
                   SET status = ?, transaction_id = ?, pay_time = ?, updated_at = ?
                   WHERE out_trade_no = ?""",
                (PAY_STATUS_SUCCESS, transaction_id, datetime.now(), datetime.now(), out_trade_no)
            )
            
            # 记录支付记录
            cursor.execute(
                """INSERT INTO payment_records 
                   (order_id, user_id, transaction_id, total_fee, payer_openid, trade_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order["id"], order["user_id"], transaction_id, total_fee, payer_openid, "JSAPI", datetime.now())
            )
            
            # 增加用户credits
            credits_to_add = order["credits"]
            cursor.execute(
                "UPDATE users SET credits = credits + ? WHERE id = ?",
                (credits_to_add, order["user_id"])
            )
            
            # 记录credits交易
            cursor.execute(
                """INSERT INTO credit_transactions 
                   (user_id, amount, balance_before, balance_after, transaction_type, reference_id, description, created_at)
                   VALUES (?, ?, 
                           (SELECT credits FROM users WHERE id = ?),
                           (SELECT credits FROM users WHERE id = ?),
                           ?, ?, ?, ?)""",
                (order["user_id"], credits_to_add, order["user_id"], order["user_id"],
                 "recharge", out_trade_no, f"支付成功，获得{credits_to_add}个credits", datetime.now())
            )
            
            conn.commit()
            logger.info(f"支付成功处理完成: {out_trade_no}, 用户: {order['user_id']}, 增加credits: {credits_to_add}")
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"处理支付成功逻辑失败: {e}")
            return False
        finally:
            conn.close()

    async def process_refund_success(self, out_refund_no: str, refund_id: str, refund_fee: int) -> bool:
        """处理退款成功逻辑
        
        Args:
            out_refund_no: 商户退款单号
            refund_id: 微信退款单号
            refund_fee: 退款金额（分）
            
        Returns:
            是否处理成功
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询退款单
            cursor.execute(
                "SELECT id, order_id, user_id, status, refund_fee, credits_to_deduct FROM refund_orders WHERE out_refund_no = ?",
                (out_refund_no,)
            )
            refund = cursor.fetchone()
            
            if not refund:
                logger.error(f"退款单不存在: {out_refund_no}")
                return False
            
            if refund["status"] == PAY_STATUS_SUCCESS:
                logger.warning(f"退款单已处理: {out_refund_no}")
                return True
            
            # 更新退款单状态
            cursor.execute(
                """UPDATE refund_orders 
                   SET status = ?, refund_id = ?, success_time = ?, updated_at = ?
                   WHERE out_refund_no = ?""",
                (PAY_STATUS_SUCCESS, refund_id, datetime.now(), datetime.now(), out_refund_no)
            )
            
            # 更新原订单状态
            cursor.execute(
                "UPDATE payment_orders SET status = ? WHERE id = ?",
                (PAY_STATUS_REFUND, refund["order_id"])
            )
            
            # 扣除用户credits
            credits_to_deduct = refund["credits_to_deduct"]
            cursor.execute(
                "UPDATE users SET credits = credits - ? WHERE id = ?",
                (credits_to_deduct, refund["user_id"])
            )
            
            # 记录credits交易
            cursor.execute(
                """INSERT INTO credit_transactions 
                   (user_id, amount, balance_before, balance_after, transaction_type, reference_id, description, created_at)
                   VALUES (?, -?, 
                           (SELECT credits FROM users WHERE id = ?),
                           (SELECT credits FROM users WHERE id = ?),
                           ?, ?, ?, ?)""",
                (refund["user_id"], credits_to_deduct, refund["user_id"], refund["user_id"],
                 "refund", out_refund_no, f"退款成功，扣除{credits_to_deduct}个credits", datetime.now())
            )
            
            conn.commit()
            logger.info(f"退款成功处理完成: {out_refund_no}, 用户: {refund['user_id']}, 扣除credits: {credits_to_deduct}")
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"处理退款成功逻辑失败: {e}")
            return False
        finally:
            conn.close()

    async def create_diagnosis_order(self, user_id: int, openid: str) -> Dict[str, Any]:
        """创建诊断支付订单
        
        Args:
            user_id: 用户ID
            openid: 用户微信openid
            
        Returns:
            包含支付参数的订单信息
        """
        # 生成商户订单号
        out_trade_no = f"DX{datetime.now().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4).upper()}"
        
        # 计算金额（元转分）
        total_fee = int(DIAGNOSIS_PRICE * 100)
        
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 创建订单记录
            cursor.execute(
                """INSERT INTO payment_orders 
                   (user_id, out_trade_no, amount, credits, status, description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, out_trade_no, total_fee, CREDITS_PER_PAY, PAY_STATUS_PENDING, 
                 f"K12升学诊断服务（{DIAGNOSIS_PRICE}元）", datetime.now(), datetime.now())
            )
            conn.commit()
            
            # 调用微信支付创建订单
            pay_params = await self.create_jsapi_order(
                openid=openid,
                out_trade_no=out_trade_no,
                total_fee=total_fee,
                description=f"K12升学诊断服务-{out_trade_no}"
            )
            
            logger.info(f"创建诊断订单成功: {out_trade_no}, 用户: {user_id}")
            return {
                "out_trade_no": out_trade_no,
                "total_fee": total_fee,
                "prepay_id": pay_params.get("prepay_id"),
                "description": f"K12升学诊断服务（{DIAGNOSIS_PRICE}元）"
            }
            
        except Exception as e:
            conn.rollback()
            logger.error(f"创建诊断订单失败: {e}")
            raise HTTPException(status_code=500, detail="创建诊断订单失败")
        finally:
            conn.close()

    def generate_jsapi_pay_params(self, prepay_id: str) -> Dict[str, str]:
        """生成JSAPI调起支付参数
        
        Args:
            prepay_id: 预支付ID
            
        Returns:
            调起支付所需的参数
        """
        nonce_str = self._generate_nonce_str()
        timestamp = self._generate_timestamp()
        package = f"prepay_id={prepay_id}"
        
        # 构建签名串
        sign_str = f"{self.app_id}\n{timestamp}\n{nonce_str}\n{package}\n"
        
        # 使用私钥签名
        signature = self.private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        return {
            "appId": self.app_id,
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": package,
            "signType": "RSA",
            "paySign": base64.b64encode(signature).decode("utf-8")
        }

    async def check_user_credits(self, user_id: int) -> Tuple[bool, int]:
        """检查用户credits是否足够进行诊断
        
        Args:
            user_id: 用户ID
            
        Returns:
            (是否足够, 当前credits数量)
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            
            if not user:
                return False, 0
            
            current_credits = user["credits"]
            return current_credits >= DIAGNOSIS_CREDITS, current_credits
            
        except Exception as e:
            logger.error(f"检查用户credits失败: {e}")
            return False, 0
        finally:
            conn.close()

    async def deduct_credits_for_diagnosis(self, user_id: int, diagnosis_id: int) -> bool:
        """扣除诊断所需的credits
        
        Args:
            user_id: 用户ID
            diagnosis_id: 诊断记录ID
            
        Returns:
            是否扣除成功
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 检查用户credits
            cursor.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            
            if not user or user["credits"] < DIAGNOSIS_CREDITS:
                logger.warning(f"用户credits不足: {user_id}")
                return False
            
            # 扣除credits
            cursor.execute(
                "UPDATE users SET credits = credits - ? WHERE id = ?",
                (DIAGNOSIS_CREDITS, user_id)
            )
            
            # 记录credits交易
            cursor.execute(
                """INSERT INTO credit_transactions 
                   (user_id, amount, balance_before, balance_after, transaction_type, reference_id, description, created_at)
                   VALUES (?, -?, 
                           (SELECT credits + ? FROM users WHERE id = ?),
                           (SELECT credits FROM users WHERE id = ?),
                           ?, ?, ?, ?)""",
                (user_id, DIAGNOSIS_CREDITS, DIAGNOSIS_CREDITS, user_id, user_id,
                 "diagnosis", f"DX{diagnosis_id}", f"诊断消耗{DIAGNOSIS_CREDITS}个credits", datetime.now())
            )
            
            conn.commit()
            logger.info(f"扣除诊断credits成功: 用户{user_id}, 诊断{diagnosis_id}")
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"扣除诊断credits失败: {e}")
            return False
        finally:
            conn.close()


# 创建全局支付服务实例
payment_service = WeChatPayV3Service()