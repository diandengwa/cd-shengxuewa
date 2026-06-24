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
            "timestamp": timestamp
        }

    async def _make_request(self, method: str, path: str, body: Optional[Dict] = None) -> Dict:
        """发送HTTP请求到微信支付API
        
        Args:
            method: HTTP方法
            path: API路径
            body: 请求体
            
        Returns:
            响应数据
        """
        url = f"{WECHAT_API_BASE}{path}"
        body_str = json.dumps(body, ensure_ascii=False) if body else ""
        
        # 构建签名
        sign_info = self._build_signature(method, path, body_str)
        
        # 构建请求头
        headers = {
            "Authorization": f'WECHATPAY2-SHA256-RSA2048 mchid="{self.mch_id}",'
                           f'nonce_str="{sign_info["nonce"]}",'
                           f'timestamp="{sign_info["timestamp"]}",'
                           f'serial_no="{self._get_cert_serial_no()}",'
                           f'signature="{sign_info["signature"]}"',
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "K12-Shengxuewa/2.0"
        }
        
        try:
            if method == "GET":
                response = await self.client.get(url, headers=headers)
            elif method == "POST":
                response = await self.client.post(url, headers=headers, content=body_str)
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"微信支付API请求失败: {e.response.text}")
            raise HTTPException(status_code=500, detail="支付服务异常")
        except Exception as e:
            logger.error(f"微信支付API请求异常: {e}")
            raise HTTPException(status_code=500, detail="支付服务异常")

    def _get_cert_serial_no(self) -> str:
        """获取证书序列号"""
        if self.certificate is None:
            raise ValueError("商户证书未加载")
        
        from cryptography.x509 import load_pem_x509_certificate
        cert = load_pem_x509_certificate(self.certificate, default_backend())
        return format(cert.serial_number, 'x')

    async def create_jsapi_order(self, openid: str, amount: Decimal, description: str) -> Dict:
        """创建JSAPI支付订单
        
        Args:
            openid: 用户微信openid
            amount: 订单金额（元）
            description: 订单描述
            
        Returns:
            包含prepay_id的订单信息
        """
        # 生成订单号
        order_id = self._generate_order_id()
        
        # 转换金额为分
        amount_fen = int(amount * 100)
        
        # 构建请求参数
        params = {
            "appid": self.app_id,
            "mchid": self.mch_id,
            "description": description,
            "out_trade_no": order_id,
            "notify_url": self.notify_url,
            "amount": {
                "total": amount_fen,
                "currency": "CNY"
            },
            "payer": {
                "openid": openid
            }
        }
        
        # 调用微信支付统一下单接口
        result = await self._make_request("POST", "/pay/transactions/jsapi", params)
        
        # 保存订单信息到数据库
        await self._save_order(order_id, openid, amount, description, result["prepay_id"])
        
        # 构建前端调起支付所需的参数
        pay_params = self._build_jsapi_pay_params(result["prepay_id"])
        
        return {
            "order_id": order_id,
            "prepay_id": result["prepay_id"],
            "pay_params": pay_params
        }

    def _generate_order_id(self) -> str:
        """生成唯一订单号"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_str = secrets.token_hex(4)
        return f"K12{timestamp}{random_str}"

    async def _save_order(self, order_id: str, openid: str, amount: Decimal, 
                         description: str, prepay_id: str):
        """保存订单到数据库
        
        Args:
            order_id: 订单号
            openid: 用户openid
            amount: 订单金额
            description: 订单描述
            prepay_id: 微信预支付ID
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO payment_orders 
                (order_id, openid, amount, description, prepay_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                order_id,
                openid,
                str(amount),
                description,
                prepay_id,
                PAY_STATUS_PENDING,
                datetime.now().isoformat()
            ))
            conn.commit()
            logger.info(f"订单保存成功: {order_id}")
        except Exception as e:
            logger.error(f"保存订单失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def _build_jsapi_pay_params(self, prepay_id: str) -> Dict:
        """构建JSAPI调起支付参数
        
        Args:
            prepay_id: 微信预支付ID
            
        Returns:
            前端调起支付所需的参数
        """
        app_id = self.app_id
        time_stamp = self._generate_timestamp()
        nonce_str = self._generate_nonce_str()
        package = f"prepay_id={prepay_id}"
        
        # 构建签名串
        sign_str = f"{app_id}\n{time_stamp}\n{nonce_str}\n{package}\n"
        
        # 使用私钥签名
        signature = self.private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        return {
            "appId": app_id,
            "timeStamp": time_stamp,
            "nonceStr": nonce_str,
            "package": package,
            "signType": "RSA",
            "paySign": base64.b64encode(signature).decode("utf-8")
        }

    async def handle_payment_notify(self, request: Request) -> Dict:
        """处理微信支付回调通知
        
        Args:
            request: FastAPI请求对象
            
        Returns:
            处理结果
        """
        # 获取请求体
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # 验证签名
        if not self._verify_notify_signature(request.headers, body_str):
            logger.error("支付回调签名验证失败")
            raise HTTPException(status_code=401, detail="签名验证失败")
        
        # 解析回调数据
        notify_data = json.loads(body_str)
        resource = notify_data.get("resource", {})
        
        # 解密资源数据
        decrypted_data = self._decrypt_resource(resource)
        
        # 处理订单状态更新
        order_id = decrypted_data.get("out_trade_no")
        transaction_id = decrypted_data.get("transaction_id")
        trade_state = decrypted_data.get("trade_state")
        
        if trade_state == "SUCCESS":
            # 更新订单状态
            await self._update_order_status(order_id, PAY_STATUS_SUCCESS, transaction_id)
            
            # 增加用户credits
            await self._add_credits_for_order(order_id)
            
            logger.info(f"订单支付成功: {order_id}, 交易号: {transaction_id}")
        else:
            logger.warning(f"订单支付失败: {order_id}, 状态: {trade_state}")
            await self._update_order_status(order_id, PAY_STATUS_FAILED, transaction_id)
        
        return {
            "code": "SUCCESS",
            "message": "成功"
        }

    def _verify_notify_signature(self, headers: Dict, body: str) -> bool:
        """验证回调签名
        
        Args:
            headers: 请求头
            body: 请求体
            
        Returns:
            签名是否有效
        """
        try:
            # 获取签名相关头信息
            wechatpay_signature = headers.get("wechatpay-signature")
            wechatpay_timestamp = headers.get("wechatpay-timestamp")
            wechatpay_nonce = headers.get("wechatpay-nonce")
            wechatpay_serial = headers.get("wechatpay-serial")
            
            if not all([wechatpay_signature, wechatpay_timestamp, wechatpay_nonce, wechatpay_serial]):
                logger.error("缺少必要的签名头信息")
                return False
            
            # 构建验签串
            sign_str = f"{wechatpay_timestamp}\n{wechatpay_nonce}\n{body}\n"
            
            # 获取平台证书
            platform_cert = self._get_platform_certificate(wechatpay_serial)
            if platform_cert is None:
                logger.error("获取平台证书失败")
                return False
            
            # 验证签名
            try:
                platform_cert.public_key().verify(
                    base64.b64decode(wechatpay_signature),
                    sign_str.encode("utf-8"),
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
                return True
            except Exception as e:
                logger.error(f"签名验证失败: {e}")
                return False
                
        except Exception as e:
            logger.error(f"验证回调签名异常: {e}")
            return False

    def _get_platform_certificate(self, serial_no: str) -> Optional[Any]:
        """获取微信支付平台证书
        
        Args:
            serial_no: 证书序列号
            
        Returns:
            证书对象
        """
        # 从缓存或数据库获取平台证书
        # 实际项目中应该缓存证书并定期更新
        try:
            # 调用微信支付API获取平台证书
            # 这里简化处理，实际应该实现证书缓存机制
            cert_path = settings.WECHAT_PLATFORM_CERT_PATH
            if cert_path and os.path.exists(cert_path):
                with open(cert_path, "rb") as f:
                    from cryptography.x509 import load_pem_x509_certificate
                    return load_pem_x509_certificate(f.read(), default_backend())
            return None
        except Exception as e:
            logger.error(f"获取平台证书失败: {e}")
            return None

    def _decrypt_resource(self, resource: Dict) -> Dict:
        """解密回调资源数据
        
        Args:
            resource: 加密的资源数据
            
        Returns:
            解密后的数据
        """
        algorithm = resource.get("algorithm")
        ciphertext = resource.get("ciphertext")
        associated_data = resource.get("associated_data", "")
        nonce = resource.get("nonce")
        
        if algorithm != "AEAD_AES_256_GCM":
            raise ValueError(f"不支持的加密算法: {algorithm}")
        
        # 使用API V3密钥解密
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        
        key = self.api_v3_key.encode("utf-8")
        aesgcm = AESGCM(key)
        
        # 组合认证数据
        ciphertext_bytes = base64.b64decode(ciphertext)
        nonce_bytes = nonce.encode("utf-8")
        associated_data_bytes = associated_data.encode("utf-8")
        
        # 解密
        decrypted_data = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
        
        return json.loads(decrypted_data.decode("utf-8"))

    async def _update_order_status(self, order_id: str, status: str, transaction_id: Optional[str] = None):
        """更新订单状态
        
        Args:
            order_id: 订单号
            status: 新状态
            transaction_id: 微信支付交易号
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            update_fields = ["status = ?", "updated_at = ?"]
            params = [status, datetime.now().isoformat()]
            
            if transaction_id:
                update_fields.append("transaction_id = ?")
                params.append(transaction_id)
            
            params.append(order_id)
            
            cursor.execute(f"""
                UPDATE payment_orders 
                SET {', '.join(update_fields)}
                WHERE order_id = ?
            """, params)
            conn.commit()
            logger.info(f"订单状态更新成功: {order_id} -> {status}")
        except Exception as e:
            logger.error(f"更新订单状态失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    async def _add_credits_for_order(self, order_id: str):
        """为订单增加用户credits
        
        Args:
            order_id: 订单号
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 获取订单信息
            cursor.execute("SELECT openid, amount FROM payment_orders WHERE order_id = ?", (order_id,))
            order = cursor.fetchone()
            
            if not order:
                logger.error(f"订单不存在: {order_id}")
                return
            
            openid = order["openid"]
            amount = Decimal(order["amount"])
            
            # 计算应获得的credits数量
            # 按次诊断计费：每次支付获得1个credits
            credits_to_add = CREDITS_PER_PAY
            
            # 更新用户credits余额
            cursor.execute("""
                UPDATE users 
                SET credits = credits + ?,
                    total_credits = total_credits + ?,
                    updated_at = ?
                WHERE openid = ?
            """, (credits_to_add, credits_to_add, datetime.now().isoformat(), openid))
            
            # 记录credits交易
            cursor.execute("""
                INSERT INTO credit_transactions 
                (openid, amount, transaction_type, order_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                openid,
                credits_to_add,
                "purchase",
                order_id,
                f"购买诊断次数 {credits_to_add} 次",
                datetime.now().isoformat()
            ))
            
            conn.commit()
            logger.info(f"用户 {openid} 增加 {credits_to_add} credits 成功")
            
        except Exception as e:
            logger.error(f"增加credits失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    async def query_order(self, order_id: str) -> Optional[Dict]:
        """查询订单状态
        
        Args:
            order_id: 订单号
            
        Returns:
            订单信息
        """
        # 从数据库查询
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM payment_orders WHERE order_id = ?
            """, (order_id,))
            order = cursor.fetchone()
            
            if order:
                return dict(order)
            return None
        finally:
            conn.close()

    async def close_order(self, order_id: str) -> bool:
        """关闭订单
        
        Args:
            order_id: 订单号
            
        Returns:
            是否成功
        """
        try:
            # 调用微信支付API关闭订单
            await self._make_request("POST", f"/pay/transactions/out-trade-no/{order_id}/close", {})
            
            # 更新本地订单状态
            await self._update_order_status(order_id, PAY_STATUS_FAILED)
            
            return True
        except Exception as e:
            logger.error(f"关闭订单失败: {e}")
            return False

    async def refund_order(self, order_id: str, refund_amount: Optional[Decimal] = None) -> Dict:
        """退款
        
        Args:
            order_id: 订单号
            refund_amount: 退款金额（可选，默认全额退款）
            
        Returns:
            退款结果
        """
        # 获取订单信息
        order = await self.query_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        
        if order["status"] != PAY_STATUS_SUCCESS:
            raise HTTPException(status_code=400, detail="订单状态不允许退款")
        
        # 生成退款单号
        refund_id = f"RF{self._generate_order_id()}"
        
        # 计算退款金额
        amount = refund_amount if refund_amount else Decimal(order["amount"])
        amount_fen = int(amount * 100)
        
        # 构建退款参数
        params = {
            "out_trade_no": order_id,
            "out_refund_no": refund_id,
            "amount": {
                "refund": amount_fen,
                "total": int(Decimal(order["amount"]) * 100),
                "currency": "CNY"
            },
            "notify_url": self.refund_notify_url
        }
        
        # 调用退款API
        result = await self._make_request("POST", "/refund/domestic/refunds", params)
        
        # 更新订单状态
        await self._update_order_status(order_id, PAY_STATUS_REFUND)
        
        # 扣除用户credits
        await self._deduct_credits_for_refund(order_id)
        
        return {
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": amount,
            "status": "processing"
        }

    async def _deduct_credits_for_refund(self, order_id: str):
        """退款时扣除用户credits
        
        Args:
            order_id: 订单号
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 获取订单信息
            cursor.execute("SELECT openid FROM payment_orders WHERE order_id = ?", (order_id,))
            order = cursor.fetchone()
            
            if not order:
                logger.error(f"订单不存在: {order_id}")
                return
            
            openid = order["openid"]
            
            # 扣除credits
            cursor.execute("""
                UPDATE users 
                SET credits = credits - ?,
                    updated_at = ?
                WHERE openid = ? AND credits >= ?
            """, (CREDITS_PER_PAY, datetime.now().isoformat(), openid, CREDITS_PER_PAY))
            
            # 记录credits交易
            cursor.execute("""
                INSERT INTO credit_transactions 
                (openid, amount, transaction_type, order_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                openid,
                -CREDITS_PER_PAY,
                "refund",
                order_id,
                f"退款扣除诊断次数 {CREDITS_PER_PAY} 次",
                datetime.now().isoformat()
            ))
            
            conn.commit()
            logger.info(f"用户 {openid} 扣除 {CREDITS_PER_PAY} credits 成功")
            
        except Exception as e:
            logger.error(f"扣除credits失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    async def get_user_credits(self, openid: str) -> int:
        """获取用户credits余额
        
        Args:
            openid: 用户openid
            
        Returns:
            credits余额
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT credits FROM users WHERE openid = ?", (openid,))
            user = cursor.fetchone()
            
            if user:
                return user["credits"]
            return 0
        finally:
            conn.close()

    async def deduct_credits_for_diagnosis(self, openid: str) -> bool:
        """扣除诊断所需的credits
        
        Args:
            openid: 用户openid
            
        Returns:
            是否扣除成功
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 检查用户credits是否足够
            cursor.execute("SELECT credits FROM users WHERE openid = ?", (openid,))
            user = cursor.fetchone()
            
            if not user or user["credits"] < DIAGNOSIS_CREDITS:
                logger.warning(f"用户 {openid} credits不足")
                return False
            
            # 扣除credits
            cursor.execute("""
                UPDATE users 
                SET credits = credits - ?,
                    total_diagnosis = total_diagnosis + 1,
                    updated_at = ?
                WHERE openid = ? AND credits >= ?
            """, (DIAGNOSIS_CREDITS, datetime.now().isoformat(), openid, DIAGNOSIS_CREDITS))
            
            # 记录credits交易
            cursor.execute("""
                INSERT INTO credit_transactions 
                (openid, amount, transaction_type, description, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                openid,
                -DIAGNOSIS_CREDITS,
                "diagnosis",
                f"诊断消耗 {DIAGNOSIS_CREDITS} 次",
                datetime.now().isoformat()
            ))
            
            conn.commit()
            logger.info(f"用户 {openid} 扣除 {DIAGNOSIS_CREDITS} credits 用于诊断")
            return True
            
        except Exception as e:
            logger.error(f"扣除诊断credits失败: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    async def get_credit_transactions(self, openid: str, limit: int = 20, offset: int = 0) -> Dict:
        """获取用户credits交易记录
        
        Args:
            openid: 用户openid
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            交易记录列表和总数
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询总数
            cursor.execute("""
                SELECT COUNT(*) as total FROM credit_transactions WHERE openid = ?
            """, (openid,))
            total = cursor.fetchone()["total"]
            
            # 查询记录
            cursor.execute("""
                SELECT * FROM credit_transactions 
                WHERE openid = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (openid, limit, offset))
            
            transactions = [dict(row) for row in cursor.fetchall()]
            
            return {
                "total": total,
                "transactions": transactions,
                "limit": limit,
                "offset": offset
            }
        finally:
            conn.close()


# 创建全局支付服务实例
payment_service = WeChatPayV3Service()