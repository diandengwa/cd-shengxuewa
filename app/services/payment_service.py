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
        
        # 返回签名信息
        return {
            "signature": base64.b64encode(signature).decode("utf-8"),
            "nonce": nonce,
            "timestamp": timestamp,
            "serial_no": self._get_cert_serial_no()
        }

    def _get_cert_serial_no(self) -> str:
        """获取证书序列号"""
        if self.certificate is None:
            raise ValueError("商户证书未加载")
        
        from cryptography.x509 import load_pem_x509_certificate
        cert = load_pem_x509_certificate(self.certificate, default_backend())
        return cert.serial_number

    async def _make_request(self, method: str, url: str, body: Optional[Dict] = None) -> Dict:
        """发送HTTP请求到微信支付API
        
        Args:
            method: HTTP方法
            url: 请求URL
            body: 请求体
            
        Returns:
            响应数据
        """
        body_str = json.dumps(body, ensure_ascii=False) if body else ""
        sign_info = self._build_signature(method, url, body_str)
        
        headers = {
            "Authorization": f'WECHATPAY2-SHA256-RSA2048 mchid="{self.mch_id}",nonce_str="{sign_info["nonce"]}",timestamp="{sign_info["timestamp"]}",serial_no="{sign_info["serial_no"]}",signature="{sign_info["signature"]}"',
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "K12-Shengxuewa/2.0"
        }
        
        try:
            response = await self.client.request(
                method=method,
                url=url,
                headers=headers,
                content=body_str.encode("utf-8") if body_str else None
            )
            
            if response.status_code == 204:
                return {}
            
            response_data = response.json()
            
            if response.status_code >= 400:
                logger.error(f"微信支付API请求失败: {response.status_code} {response_data}")
                raise HTTPException(
                    status_code=500,
                    detail=f"微信支付API请求失败: {response_data.get('message', '未知错误')}"
                )
            
            return response_data
            
        except httpx.TimeoutException:
            logger.error("微信支付API请求超时")
            raise HTTPException(status_code=500, detail="微信支付API请求超时")
        except httpx.RequestError as e:
            logger.error(f"微信支付API请求异常: {e}")
            raise HTTPException(status_code=500, detail=f"微信支付API请求异常: {str(e)}")

    async def create_jsapi_order(self, openid: str, out_trade_no: str, total_fee: int, description: str) -> Dict:
        """创建JSAPI支付订单
        
        Args:
            openid: 用户微信openid
            out_trade_no: 商户订单号
            total_fee: 订单金额（分）
            description: 商品描述
            
        Returns:
            支付参数
        """
        url = f"{WECHAT_PAY_API_BASE}/transactions/jsapi"
        
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
        
        result = await self._make_request("POST", url, body)
        
        # 生成JSAPI调起支付参数
        prepay_id = result.get("prepay_id")
        if not prepay_id:
            raise HTTPException(status_code=500, detail="获取prepay_id失败")
        
        pay_params = self._generate_jsapi_pay_params(prepay_id)
        return pay_params

    def _generate_jsapi_pay_params(self, prepay_id: str) -> Dict:
        """生成JSAPI调起支付参数
        
        Args:
            prepay_id: 预支付ID
            
        Returns:
            JSAPI支付参数
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

    async def query_order(self, out_trade_no: str) -> Dict:
        """查询订单状态
        
        Args:
            out_trade_no: 商户订单号
            
        Returns:
            订单信息
        """
        url = f"{WECHAT_PAY_API_BASE}/transactions/out-trade-no/{out_trade_no}?mchid={self.mch_id}"
        return await self._make_request("GET", url)

    async def close_order(self, out_trade_no: str) -> None:
        """关闭订单
        
        Args:
            out_trade_no: 商户订单号
        """
        url = f"{WECHAT_PAY_API_BASE}/transactions/out-trade-no/{out_trade_no}/close"
        body = {
            "mchid": self.mch_id
        }
        await self._make_request("POST", url, body)

    async def refund_order(self, out_trade_no: str, refund_amount: int, total_amount: int, reason: str = "") -> Dict:
        """申请退款
        
        Args:
            out_trade_no: 商户订单号
            refund_amount: 退款金额（分）
            total_amount: 原订单金额（分）
            reason: 退款原因
            
        Returns:
            退款信息
        """
        url = f"{WECHAT_REFUND_API_BASE}/domestic/refunds"
        
        body = {
            "out_trade_no": out_trade_no,
            "out_refund_no": f"REFUND_{out_trade_no}_{int(time.time())}",
            "reason": reason,
            "notify_url": self.refund_notify_url,
            "amount": {
                "refund": refund_amount,
                "total": total_amount,
                "currency": "CNY"
            }
        }
        
        return await self._make_request("POST", url, body)

    async def verify_payment_notification(self, request: Request) -> Dict:
        """验证支付回调通知
        
        Args:
            request: FastAPI请求对象
            
        Returns:
            解密后的回调数据
        """
        # 获取请求头
        wechatpay_signature = request.headers.get("Wechatpay-Signature")
        wechatpay_timestamp = request.headers.get("Wechatpay-Timestamp")
        wechatpay_nonce = request.headers.get("Wechatpay-Nonce")
        wechatpay_serial = request.headers.get("Wechatpay-Serial")
        
        if not all([wechatpay_signature, wechatpay_timestamp, wechatpay_nonce, wechatpay_serial]):
            raise HTTPException(status_code=400, detail="缺少必要的回调验证头")
        
        # 读取请求体
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # 构建验签名串
        sign_str = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body_str}\n"
        
        # 获取平台证书
        platform_cert = await self._get_platform_certificate(wechatpay_serial)
        if not platform_cert:
            raise HTTPException(status_code=400, detail="无法获取平台证书")
        
        # 验证签名
        try:
            platform_cert.public_key().verify(
                base64.b64decode(wechatpay_signature),
                sign_str.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception as e:
            logger.error(f"回调签名验证失败: {e}")
            raise HTTPException(status_code=400, detail="回调签名验证失败")
        
        # 解密数据
        return self._decrypt_notification_data(body_str)

    async def _get_platform_certificate(self, serial_no: str):
        """获取微信支付平台证书
        
        Args:
            serial_no: 证书序列号
            
        Returns:
            平台证书对象
        """
        # 先从缓存获取
        cert = self._get_cached_certificate(serial_no)
        if cert:
            return cert
        
        # 从微信支付API获取
        url = f"{WECHAT_API_BASE}/certificates"
        result = await self._make_request("GET", url)
        
        for cert_info in result.get("data", []):
            if cert_info.get("serial_no") == serial_no:
                # 解密证书内容
                encrypted_cert = cert_info.get("encrypt_certificate")
                if encrypted_cert:
                    cert_pem = self._decrypt_certificate(encrypted_cert)
                    from cryptography.x509 import load_pem_x509_certificate
                    cert = load_pem_x509_certificate(cert_pem.encode("utf-8"), default_backend())
                    self._cache_certificate(serial_no, cert)
                    return cert
        
        return None

    def _get_cached_certificate(self, serial_no: str):
        """从缓存获取平台证书"""
        # TODO: 实现证书缓存逻辑
        return None

    def _cache_certificate(self, serial_no: str, cert):
        """缓存平台证书"""
        # TODO: 实现证书缓存逻辑
        pass

    def _decrypt_certificate(self, encrypted_cert: Dict) -> str:
        """解密平台证书
        
        Args:
            encrypted_cert: 加密的证书信息
            
        Returns:
            解密后的证书PEM内容
        """
        algorithm = encrypted_cert.get("algorithm")
        nonce = encrypted_cert.get("nonce")
        associated_data = encrypted_cert.get("associated_data")
        ciphertext = encrypted_cert.get("ciphertext")
        
        if algorithm != "AEAD_AES_256_GCM":
            raise ValueError(f"不支持的加密算法: {algorithm}")
        
        # 使用APIv3密钥解密
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = self.api_v3_key.encode("utf-8")
        aesgcm = AESGCM(key)
        
        # 组合nonce和密文
        ciphertext_bytes = base64.b64decode(ciphertext)
        nonce_bytes = nonce.encode("utf-8")
        associated_data_bytes = associated_data.encode("utf-8") if associated_data else None
        
        plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
        return plaintext.decode("utf-8")

    def _decrypt_notification_data(self, body_str: str) -> Dict:
        """解密回调通知数据
        
        Args:
            body_str: 回调请求体字符串
            
        Returns:
            解密后的数据
        """
        body = json.loads(body_str)
        resource = body.get("resource")
        if not resource:
            raise ValueError("回调数据中缺少resource字段")
        
        algorithm = resource.get("algorithm")
        ciphertext = resource.get("ciphertext")
        nonce = resource.get("nonce")
        associated_data = resource.get("associated_data")
        
        if algorithm != "AEAD_AES_256_GCM":
            raise ValueError(f"不支持的加密算法: {algorithm}")
        
        # 使用APIv3密钥解密
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = self.api_v3_key.encode("utf-8")
        aesgcm = AESGCM(key)
        
        ciphertext_bytes = base64.b64decode(ciphertext)
        nonce_bytes = nonce.encode("utf-8")
        associated_data_bytes = associated_data.encode("utf-8") if associated_data else None
        
        plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
        return json.loads(plaintext.decode("utf-8"))

    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


class PaymentService:
    """支付服务类：处理credits管理、支付记录、业务逻辑"""

    def __init__(self):
        self.wechat_pay = WeChatPayV3Service()

    async def create_diagnosis_payment(self, user_id: int, openid: str) -> Dict:
        """创建诊断支付订单
        
        Args:
            user_id: 用户ID
            openid: 用户微信openid
            
        Returns:
            支付参数
        """
        # 生成商户订单号
        out_trade_no = self._generate_order_no(user_id)
        
        # 计算金额（元转分）
        total_fee = int(DIAGNOSIS_PRICE * 100)
        
        # 创建支付订单记录
        order = await self._create_payment_order(
            user_id=user_id,
            out_trade_no=out_trade_no,
            total_fee=total_fee,
            description="K12升学诊断服务"
        )
        
        # 调用微信支付创建订单
        pay_params = await self.wechat_pay.create_jsapi_order(
            openid=openid,
            out_trade_no=out_trade_no,
            total_fee=total_fee,
            description="K12升学诊断服务"
        )
        
        return {
            "order_id": order.id,
            "out_trade_no": out_trade_no,
            "pay_params": pay_params
        }

    async def handle_payment_notification(self, request: Request) -> Dict:
        """处理支付回调通知
        
        Args:
            request: FastAPI请求对象
            
        Returns:
            处理结果
        """
        try:
            # 验证并解密回调数据
            notification_data = await self.wechat_pay.verify_payment_notification(request)
            
            # 获取订单信息
            out_trade_no = notification_data.get("out_trade_no")
            transaction_id = notification_data.get("transaction_id")
            trade_state = notification_data.get("trade_state")
            
            if not out_trade_no or not transaction_id:
                logger.error("回调数据缺少必要字段")
                return {"code": "FAIL", "message": "参数错误"}
            
            # 查询订单
            order = await self._get_order_by_out_trade_no(out_trade_no)
            if not order:
                logger.error(f"订单不存在: {out_trade_no}")
                return {"code": "FAIL", "message": "订单不存在"}
            
            # 检查订单状态
            if order.status == PAY_STATUS_SUCCESS:
                logger.warning(f"订单已处理: {out_trade_no}")
                return {"code": "SUCCESS", "message": "已处理"}
            
            # 处理支付成功
            if trade_state == "SUCCESS":
                await self._process_successful_payment(order, transaction_id)
            elif trade_state in ["CLOSED", "REVOKED"]:
                await self._process_failed_payment(order, trade_state)
            
            return {"code": "SUCCESS", "message": "处理成功"}
            
        except Exception as e:
            logger.error(f"处理支付回调失败: {e}")
            return {"code": "FAIL", "message": str(e)}

    async def _process_successful_payment(self, order: PaymentOrder, transaction_id: str):
        """处理支付成功
        
        Args:
            order: 支付订单
            transaction_id: 微信支付交易号
        """
        conn = get_db_connection()
        try:
            # 更新订单状态
            conn.execute(
                """UPDATE payment_orders 
                   SET status = ?, transaction_id = ?, paid_at = ?, updated_at = ?
                   WHERE id = ?""",
                (PAY_STATUS_SUCCESS, transaction_id, datetime.now(), datetime.now(), order.id)
            )
            
            # 创建支付记录
            conn.execute(
                """INSERT INTO payment_records 
                   (user_id, order_id, amount, payment_method, transaction_id, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order.user_id, order.id, order.total_fee, "wechat", transaction_id, PAY_STATUS_SUCCESS, datetime.now())
            )
            
            # 为用户添加credits
            conn.execute(
                """UPDATE users SET credits = credits + ? WHERE id = ?""",
                (CREDITS_PER_PAY, order.user_id)
            )
            
            # 创建credits交易记录
            conn.execute(
                """INSERT INTO credit_transactions 
                   (user_id, amount, transaction_type, description, reference_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (order.user_id, CREDITS_PER_PAY, "recharge", "诊断服务支付", order.id, datetime.now())
            )
            
            conn.commit()
            logger.info(f"支付成功处理完成: order={order.out_trade_no}, transaction={transaction_id}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"处理支付成功失败: {e}")
            raise
        finally:
            conn.close()

    async def _process_failed_payment(self, order: PaymentOrder, trade_state: str):
        """处理支付失败
        
        Args:
            order: 支付订单
            trade_state: 交易状态
        """
        conn = get_db_connection()
        try:
            conn.execute(
                """UPDATE payment_orders 
                   SET status = ?, updated_at = ?
                   WHERE id = ?""",
                (PAY_STATUS_FAILED, datetime.now(), order.id)
            )
            conn.commit()
            logger.info(f"支付失败处理完成: order={order.out_trade_no}, state={trade_state}")
        except Exception as e:
            conn.rollback()
            logger.error(f"处理支付失败失败: {e}")
            raise
        finally:
            conn.close()

    async def check_user_credits(self, user_id: int) -> Tuple[bool, int]:
        """检查用户credits是否足够
        
        Args:
            user_id: 用户ID
            
        Returns:
            (是否足够, 当前credits数量)
        """
        conn = get_db_connection()
        try:
            cursor = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return False, 0
            
            credits = row["credits"]
            return credits >= DIAGNOSIS_CREDITS, credits
        finally:
            conn.close()

    async def deduct_credits(self, user_id: int, diagnosis_id: int) -> bool:
        """扣除诊断credits
        
        Args:
            user_id: 用户ID
            diagnosis_id: 诊断记录ID
            
        Returns:
            是否扣除成功
        """
        conn = get_db_connection()
        try:
            # 检查credits是否足够
            cursor = conn.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if not row or row["credits"] < DIAGNOSIS_CREDITS:
                return False
            
            # 扣除credits
            conn.execute(
                """UPDATE users SET credits = credits - ? WHERE id = ?""",
                (DIAGNOSIS_CREDITS, user_id)
            )
            
            # 创建credits交易记录
            conn.execute(
                """INSERT INTO credit_transactions 
                   (user_id, amount, transaction_type, description, reference_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, -DIAGNOSIS_CREDITS, "consume", "诊断服务使用", diagnosis_id, datetime.now())
            )
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"扣除credits失败: {e}")
            return False
        finally:
            conn.close()

    async def get_user_credits_history(self, user_id: int, page: int = 1, page_size: int = 20) -> Dict:
        """获取用户credits历史记录
        
        Args:
            user_id: 用户ID
            page: 页码
            page_size: 每页数量
            
        Returns:
            历史记录
        """
        conn = get_db_connection()
        try:
            offset = (page - 1) * page_size
            
            # 查询总数
            cursor = conn.execute(
                "SELECT COUNT(*) as total FROM credit_transactions WHERE user_id = ?",
                (user_id,)
            )
            total = cursor.fetchone()["total"]
            
            # 查询记录
            cursor = conn.execute(
                """SELECT * FROM credit_transactions 
                   WHERE user_id = ? 
                   ORDER BY created_at DESC 
                   LIMIT ? OFFSET ?""",
                (user_id, page_size, offset)
            )
            records = cursor.fetchall()
            
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "records": [dict(r) for r in records]
            }
        finally:
            conn.close()

    def _generate_order_no(self, user_id: int) -> str:
        """生成商户订单号
        
        Args:
            user_id: 用户ID
            
        Returns:
            订单号
        """
        timestamp = int(time.time())
        random_str = secrets.token_hex(4)
        return f"DX{timestamp}{user_id:06d}{random_str}"

    async def _create_payment_order(self, user_id: int, out_trade_no: str, total_fee: int, description: str) -> PaymentOrder:
        """创建支付订单记录
        
        Args:
            user_id: 用户ID
            out_trade_no: 商户订单号
            total_fee: 订单金额（分）
            description: 商品描述
            
        Returns:
            支付订单对象
        """
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO payment_orders 
                   (user_id, out_trade_no, total_fee, description, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, out_trade_no, total_fee, description, PAY_STATUS_PENDING, datetime.now(), datetime.now())
            )
            conn.commit()
            
            order_id = cursor.lastrowid
            return PaymentOrder(
                id=order_id,
                user_id=user_id,
                out_trade_no=out_trade_no,
                total_fee=total_fee,
                description=description,
                status=PAY_STATUS_PENDING
            )
        finally:
            conn.close()

    async def _get_order_by_out_trade_no(self, out_trade_no: str) -> Optional[PaymentOrder]:
        """根据商户订单号查询订单
        
        Args:
            out_trade_no: 商户订单号
            
        Returns:
            支付订单对象
        """
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM payment_orders WHERE out_trade_no = ?",
                (out_trade_no,)
            )
            row = cursor.fetchone()
            if row:
                return PaymentOrder(**dict(row))
            return None
        finally:
            conn.close()

    async def close(self):
        """关闭服务"""
        await self.wechat_pay.close()


# 创建全局支付服务实例
payment_service = PaymentService()