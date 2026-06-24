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
        
        # Base64编码
        import base64
        signature_b64 = base64.b64encode(signature).decode("utf-8")
        
        # 构建Authorization头
        auth_header = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self.mch_id}",'
            f'nonce_str="{nonce}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{settings.WECHAT_CERT_SERIAL}",'
            f'signature="{signature_b64}"'
        )
        
        return auth_header

    async def _make_request(
        self,
        method: str,
        url: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict:
        """发送HTTP请求到微信支付API
        
        Args:
            method: HTTP方法
            url: 请求URL
            data: 请求体数据
            params: 查询参数
            
        Returns:
            响应数据字典
        """
        body = json.dumps(data, ensure_ascii=False) if data else ""
        
        headers = {
            "Authorization": self._build_signature(method, url, body),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"K12-Shengxuewa/{settings.APP_VERSION}"
        }
        
        try:
            if method.upper() == "GET":
                response = await self.client.get(
                    url,
                    headers=headers,
                    params=params
                )
            else:
                response = await self.client.post(
                    url,
                    headers=headers,
                    content=body
                )
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"微信支付API请求失败: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=502,
                detail=f"微信支付服务异常: {e.response.status_code}"
            )
        except httpx.RequestError as e:
            logger.error(f"微信支付API连接失败: {e}")
            raise HTTPException(
                status_code=502,
                detail="微信支付服务连接失败"
            )

    async def create_order(
        self,
        openid: str,
        description: str,
        amount: Decimal,
        out_trade_no: str,
        trade_type: str = TRADE_TYPE_JSAPI,
        attach: Optional[str] = None,
        goods_tag: Optional[str] = None
    ) -> Dict:
        """创建微信支付订单（统一下单）
        
        Args:
            openid: 用户微信OpenID
            description: 商品描述
            amount: 订单金额（元）
            out_trade_no: 商户订单号
            trade_type: 交易类型（默认JSAPI）
            attach: 附加数据
            goods_tag: 商品标记
            
        Returns:
            微信支付预支付信息
        """
        # 金额转换为分
        amount_fen = int(amount * 100)
        
        # 构建请求数据
        order_data = {
            "appid": self.app_id,
            "mchid": self.mch_id,
            "description": description,
            "out_trade_no": out_trade_no,
            "notify_url": self.notify_url,
            "amount": {
                "total": amount_fen,
                "currency": "CNY"
            },
            "payer": {
                "openid": openid
            },
            "scene_info": {
                "payer_client_ip": "127.0.0.1"  # 实际应传入客户端IP
            }
        }
        
        # 可选参数
        if attach:
            order_data["attach"] = attach
        if goods_tag:
            order_data["goods_tag"] = goods_tag
        
        # 根据交易类型添加不同参数
        if trade_type == TRADE_TYPE_NATIVE:
            order_data["scene_info"] = {
                "payer_client_ip": "127.0.0.1"
            }
        elif trade_type == TRADE_TYPE_MWEB:
            order_data["scene_info"] = {
                "payer_client_ip": "127.0.0.1",
                "h5_info": {
                    "type": "Wap"
                }
            }
        
        # 调用统一下单API
        result = await self._make_request(
            "POST",
            "/pay/transactions/jsapi" if trade_type == TRADE_TYPE_JSAPI else "/pay/transactions/native",
            order_data
        )
        
        # 如果是JSAPI，需要返回调起支付所需的参数
        if trade_type == TRADE_TYPE_JSAPI:
            prepay_id = result.get("prepay_id")
            if prepay_id:
                return self._build_jsapi_params(prepay_id)
        
        return result

    def _build_jsapi_params(self, prepay_id: str) -> Dict:
        """构建JSAPI调起支付参数
        
        Args:
            prepay_id: 预支付ID
            
        Returns:
            JSAPI调起支付参数
        """
        if self.private_key is None:
            raise ValueError("商户私钥未加载")
            
        nonce_str = self._generate_nonce_str()
        timestamp = self._generate_timestamp()
        package = f"prepay_id={prepay_id}"
        
        # 构建签名串
        sign_str = f"{self.app_id}\n{timestamp}\n{nonce_str}\n{package}\n"
        
        # 使用私钥签名
        import base64
        signature = self.private_key.sign(
            sign_str.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        pay_sign = base64.b64encode(signature).decode("utf-8")
        
        return {
            "appId": self.app_id,
            "timeStamp": timestamp,
            "nonceStr": nonce_str,
            "package": package,
            "signType": "RSA",
            "paySign": pay_sign
        }

    async def query_order(self, out_trade_no: str) -> Dict:
        """查询订单状态
        
        Args:
            out_trade_no: 商户订单号
            
        Returns:
            订单信息
        """
        url = f"/pay/transactions/out-trade-no/{out_trade_no}"
        params = {
            "mchid": self.mch_id
        }
        
        return await self._make_request("GET", url, params=params)

    async def close_order(self, out_trade_no: str) -> bool:
        """关闭订单
        
        Args:
            out_trade_no: 商户订单号
            
        Returns:
            是否成功
        """
        url = f"/pay/transactions/out-trade-no/{out_trade_no}/close"
        data = {
            "mchid": self.mch_id
        }
        
        try:
            await self._make_request("POST", url, data)
            return True
        except Exception as e:
            logger.error(f"关闭订单失败: {e}")
            return False

    async def refund_order(
        self,
        out_trade_no: str,
        refund_amount: Decimal,
        total_amount: Decimal,
        out_refund_no: str,
        reason: Optional[str] = None
    ) -> Dict:
        """申请退款
        
        Args:
            out_trade_no: 商户订单号
            refund_amount: 退款金额（元）
            total_amount: 订单总金额（元）
            out_refund_no: 商户退款单号
            reason: 退款原因
            
        Returns:
            退款信息
        """
        refund_data = {
            "out_trade_no": out_trade_no,
            "out_refund_no": out_refund_no,
            "amount": {
                "refund": int(refund_amount * 100),
                "total": int(total_amount * 100),
                "currency": "CNY"
            }
        }
        
        if reason:
            refund_data["reason"] = reason
        
        if self.refund_notify_url:
            refund_data["notify_url"] = self.refund_notify_url
        
        return await self._make_request("POST", "/refund/domestic/refunds", refund_data)

    async def verify_notification(self, request: Request) -> Dict:
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
            raise HTTPException(status_code=400, detail="缺少必要的回调验证参数")
        
        # 读取请求体
        body = await request.body()
        body_str = body.decode("utf-8")
        
        # 验证签名
        if not self._verify_callback_signature(
            wechatpay_signature,
            wechatpay_serial,
            wechatpay_timestamp,
            wechatpay_nonce,
            body_str
        ):
            raise HTTPException(status_code=401, detail="回调签名验证失败")
        
        # 解密数据
        return self._decrypt_callback_data(body_str)

    def _verify_callback_signature(
        self,
        signature: str,
        serial: str,
        timestamp: str,
        nonce: str,
        body: str
    ) -> bool:
        """验证回调签名
        
        Args:
            signature: 签名
            serial: 证书序列号
            timestamp: 时间戳
            nonce: 随机字符串
            body: 请求体
            
        Returns:
            是否验证通过
        """
        try:
            # 获取微信平台证书
            cert = self._get_wechat_platform_cert(serial)
            if not cert:
                logger.error(f"未找到序列号为 {serial} 的平台证书")
                return False
            
            # 构建签名串
            sign_str = f"{timestamp}\n{nonce}\n{body}\n"
            
            # 验证签名
            import base64
            cert.public_key().verify(
                base64.b64decode(signature),
                sign_str.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True
            
        except Exception as e:
            logger.error(f"回调签名验证失败: {e}")
            return False

    def _get_wechat_platform_cert(self, serial: str):
        """获取微信平台证书
        
        Args:
            serial: 证书序列号
            
        Returns:
            证书对象
        """
        # 从缓存或数据库获取平台证书
        # 实际项目中应定期更新平台证书
        try:
            cert_path = settings.WECHAT_PLATFORM_CERT_PATH
            if not os.path.exists(cert_path):
                logger.warning("微信平台证书文件不存在")
                return None
            
            with open(cert_path, "rb") as f:
                cert_data = f.read()
            
            from cryptography import x509
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
            
            # 验证证书序列号
            cert_serial = format(cert.serial_number, "x")
            if cert_serial != serial:
                logger.warning(f"证书序列号不匹配: {cert_serial} != {serial}")
                return None
            
            return cert
            
        except Exception as e:
            logger.error(f"加载微信平台证书失败: {e}")
            return None

    def _decrypt_callback_data(self, encrypted_data: str) -> Dict:
        """解密回调数据
        
        Args:
            encrypted_data: 加密的JSON字符串
            
        Returns:
            解密后的数据
        """
        try:
            data = json.loads(encrypted_data)
            resource = data.get("resource", {})
            
            # 获取解密参数
            algorithm = resource.get("algorithm")
            ciphertext = resource.get("ciphertext")
            associated_data = resource.get("associated_data", "")
            nonce = resource.get("nonce")
            
            if algorithm != "AEAD_AES_256_GCM":
                raise ValueError(f"不支持的加密算法: {algorithm}")
            
            # 解密
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            # 将APIv3密钥转换为AES密钥
            key = self.api_v3_key.encode("utf-8")
            aesgcm = AESGCM(key)
            
            # 解密数据
            ciphertext_bytes = bytes.fromhex(ciphertext)
            nonce_bytes = nonce.encode("utf-8")
            aad_bytes = associated_data.encode("utf-8") if associated_data else None
            
            plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, aad_bytes)
            
            return json.loads(plaintext.decode("utf-8"))
            
        except Exception as e:
            logger.error(f"解密回调数据失败: {e}")
            raise HTTPException(status_code=400, detail="回调数据解密失败")

    async def process_payment_callback(self, callback_data: Dict) -> Tuple[bool, str]:
        """处理支付回调
        
        Args:
            callback_data: 回调数据
            
        Returns:
            (是否成功, 订单号)
        """
        try:
            # 获取订单信息
            out_trade_no = callback_data.get("out_trade_no")
            trade_state = callback_data.get("trade_state")
            transaction_id = callback_data.get("transaction_id")
            
            if not out_trade_no:
                logger.error("回调数据缺少订单号")
                return False, ""
            
            # 查询订单状态
            if trade_state == "SUCCESS":
                # 更新订单状态
                await self._update_order_status(
                    out_trade_no,
                    PAY_STATUS_SUCCESS,
                    transaction_id
                )
                
                # 处理credits充值
                await self._process_credits_recharge(out_trade_no)
                
                logger.info(f"订单 {out_trade_no} 支付成功")
                return True, out_trade_no
                
            elif trade_state == "REFUND":
                # 处理退款
                await self._update_order_status(
                    out_trade_no,
                    PAY_STATUS_REFUND,
                    transaction_id
                )
                logger.info(f"订单 {out_trade_no} 已退款")
                return True, out_trade_no
                
            else:
                logger.warning(f"订单 {out_trade_no} 状态: {trade_state}")
                return False, out_trade_no
                
        except Exception as e:
            logger.error(f"处理支付回调失败: {e}")
            return False, ""

    async def _update_order_status(
        self,
        out_trade_no: str,
        status: str,
        transaction_id: Optional[str] = None
    ):
        """更新订单状态
        
        Args:
            out_trade_no: 商户订单号
            status: 订单状态
            transaction_id: 微信支付交易号
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            update_fields = ["status = ?", "updated_at = ?"]
            params = [status, datetime.now()]
            
            if transaction_id:
                update_fields.append("transaction_id = ?")
                params.append(transaction_id)
            
            params.append(out_trade_no)
            
            cursor.execute(
                f"UPDATE payment_orders SET {', '.join(update_fields)} WHERE out_trade_no = ?",
                params
            )
            conn.commit()
            
        except Exception as e:
            logger.error(f"更新订单状态失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    async def _process_credits_recharge(self, out_trade_no: str):
        """处理credits充值
        
        Args:
            out_trade_no: 商户订单号
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 查询订单信息
            cursor.execute(
                "SELECT user_id, amount FROM payment_orders WHERE out_trade_no = ?",
                (out_trade_no,)
            )
            order = cursor.fetchone()
            
            if not order:
                logger.error(f"订单 {out_trade_no} 不存在")
                return
            
            user_id = order["user_id"]
            amount = Decimal(str(order["amount"]))
            
            # 计算应获得的credits数量
            credits_to_add = int(amount / DIAGNOSIS_PRICE) * CREDITS_PER_PAY
            
            if credits_to_add <= 0:
                logger.warning(f"订单 {out_trade_no} 金额不足以获得credits")
                return
            
            # 更新用户credits
            cursor.execute(
                "UPDATE users SET credits = credits + ? WHERE id = ?",
                (credits_to_add, user_id)
            )
            
            # 记录credits交易
            cursor.execute(
                """INSERT INTO credit_transactions 
                   (user_id, amount, type, description, reference_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    credits_to_add,
                    "recharge",
                    f"微信支付充值 {amount} 元，获得 {credits_to_add} credits",
                    out_trade_no,
                    datetime.now()
                )
            )
            
            conn.commit()
            logger.info(f"用户 {user_id} 充值 {credits_to_add} credits 成功")
            
        except Exception as e:
            logger.error(f"处理credits充值失败: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    async def get_user_credits(self, user_id: int) -> int:
        """获取用户credits余额
        
        Args:
            user_id: 用户ID
            
        Returns:
            credits余额
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT credits FROM users WHERE id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return result["credits"] if result else 0
        finally:
            conn.close()

    async def deduct_credits(self, user_id: int, amount: int = DIAGNOSIS_CREDITS) -> bool:
        """扣除用户credits
        
        Args:
            user_id: 用户ID
            amount: 扣除数量（默认1次诊断）
            
        Returns:
            是否扣除成功
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 检查余额
            cursor.execute(
                "SELECT credits FROM users WHERE id = ?",
                (user_id,)
            )
            user = cursor.fetchone()
            
            if not user or user["credits"] < amount:
                logger.warning(f"用户 {user_id} credits不足")
                return False
            
            # 扣除credits
            cursor.execute(
                "UPDATE users SET credits = credits - ? WHERE id = ?",
                (amount, user_id)
            )
            
            # 记录交易
            cursor.execute(
                """INSERT INTO credit_transactions 
                   (user_id, amount, type, description, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    user_id,
                    -amount,
                    "deduction",
                    f"诊断消耗 {amount} credits",
                    datetime.now()
                )
            )
            
            conn.commit()
            logger.info(f"用户 {user_id} 扣除 {amount} credits 成功")
            return True
            
        except Exception as e:
            logger.error(f"扣除credits失败: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    async def get_payment_history(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20
    ) -> Dict:
        """获取用户支付历史
        
        Args:
            user_id: 用户ID
            page: 页码
            page_size: 每页数量
            
        Returns:
            支付历史数据
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 计算偏移量
            offset = (page - 1) * page_size
            
            # 查询总数
            cursor.execute(
                "SELECT COUNT(*) as total FROM payment_orders WHERE user_id = ?",
                (user_id,)
            )
            total = cursor.fetchone()["total"]
            
            # 查询分页数据
            cursor.execute(
                """SELECT * FROM payment_orders 
                   WHERE user_id = ? 
                   ORDER BY created_at DESC 
                   LIMIT ? OFFSET ?""",
                (user_id, page_size, offset)
            )
            orders = cursor.fetchall()
            
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
                "orders": [dict(order) for order in orders]
            }
            
        finally:
            conn.close()

    async def get_credit_transactions(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20
    ) -> Dict:
        """获取用户credits交易记录
        
        Args:
            user_id: 用户ID
            page: 页码
            page_size: 每页数量
            
        Returns:
            credits交易记录
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # 计算偏移量
            offset = (page - 1) * page_size
            
            # 查询总数
            cursor.execute(
                "SELECT COUNT(*) as total FROM credit_transactions WHERE user_id = ?",
                (user_id,)
            )
            total = cursor.fetchone()["total"]
            
            # 查询分页数据
            cursor.execute(
                """SELECT * FROM credit_transactions 
                   WHERE user_id = ? 
                   ORDER BY created_at DESC 
                   LIMIT ? OFFSET ?""",
                (user_id, page_size, offset)
            )
            transactions = cursor.fetchall()
            
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
                "transactions": [dict(t) for t in transactions]
            }
            
        finally:
            conn.close()


# ============================================================
# 单例模式
# ============================================================
payment_service = WeChatPayV3Service()


async def get_payment_service() -> WeChatPayV3Service:
    """获取支付服务实例"""
    return payment_service