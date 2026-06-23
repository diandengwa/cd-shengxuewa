/**
 * payment.js - 微信支付交互脚本
 * 功能：唤起微信支付、轮询支付状态、显示支付结果
 * 项目：cd-shengxuewa（成都K12升学参谋）
 */

// ============================================================
// 配置
// ============================================================
const PAYMENT_CONFIG = {
    POLL_INTERVAL: 2000,      // 轮询间隔（毫秒）
    MAX_POLL_ATTEMPTS: 150,   // 最大轮询次数（5分钟）
    PAYMENT_API_BASE: '/api/v1/payment',
    WX_JSAPI_URL: '/api/v1/payment/wx-jsapi',
    POLL_URL: '/api/v1/payment/status',
    RESULT_URL: '/api/v1/payment/result'
};

// ============================================================
// 状态管理
// ============================================================
class PaymentState {
    constructor() {
        this.orderId = null;
        this.pollAttempts = 0;
        this.pollTimer = null;
        this.isPolling = false;
        this.isProcessing = false;
        this.callbacks = {
            onSuccess: null,
            onFail: null,
            onCancel: null,
            onProcessing: null
        };
    }

    reset() {
        this.orderId = null;
        this.pollAttempts = 0;
        this.isPolling = false;
        this.isProcessing = false;
        if (this.pollTimer) {
            clearTimeout(this.pollTimer);
            this.pollTimer = null;
        }
    }
}

// ============================================================
// 支付交互主类
// ============================================================
class PaymentHandler {
    constructor() {
        this.state = new PaymentState();
        this._initEventListeners();
    }

    /**
     * 初始化事件监听
     * @private
     */
    _initEventListeners() {
        // 监听所有支付按钮
        document.addEventListener('click', (e) => {
            const payBtn = e.target.closest('[data-pay-action]');
            if (payBtn) {
                e.preventDefault();
                const action = payBtn.dataset.payAction;
                const orderId = payBtn.dataset.orderId;
                const amount = payBtn.dataset.amount;
                const description = payBtn.dataset.description || '升学诊断服务';

                if (action === 'wxpay') {
                    this.initiateWxPay(orderId, amount, description);
                }
            }
        });
    }

    /**
     * 发起微信支付
     * @param {string} orderId - 订单ID
     * @param {number} amount - 支付金额（分）
     * @param {string} description - 商品描述
     */
    async initiateWxPay(orderId, amount, description) {
        if (this.state.isProcessing) {
            this._showToast('支付处理中，请稍候...', 'warning');
            return;
        }

        this.state.reset();
        this.state.orderId = orderId;
        this.state.isProcessing = true;

        try {
            // 显示加载状态
            this._showLoading(true);

            // 获取微信JSAPI参数
            const wxConfig = await this._getWxJsApiConfig(orderId, amount, description);
            
            if (!wxConfig || wxConfig.errcode !== 0) {
                throw new Error(wxConfig?.errmsg || '获取支付参数失败');
            }

            // 调用微信JSAPI支付
            await this._callWxJsApi(wxConfig.data);

        } catch (error) {
            console.error('支付初始化失败:', error);
            this._showToast(error.message || '支付初始化失败，请重试', 'error');
            this._onPaymentFail(error.message);
        } finally {
            this._showLoading(false);
            this.state.isProcessing = false;
        }
    }

    /**
     * 获取微信JSAPI支付参数
     * @param {string} orderId - 订单ID
     * @param {number} amount - 支付金额
     * @param {string} description - 商品描述
     * @returns {Promise<Object>} 微信支付参数
     * @private
     */
    async _getWxJsApiConfig(orderId, amount, description) {
        try {
            const response = await fetch(PAYMENT_CONFIG.WX_JSAPI_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    order_id: orderId,
                    total_fee: amount,
                    description: description,
                    trade_type: 'JSAPI'
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();

        } catch (error) {
            console.error('获取微信支付参数失败:', error);
            throw new Error('获取支付参数失败，请检查网络连接');
        }
    }

    /**
     * 调用微信JSAPI支付
     * @param {Object} wxConfig - 微信支付配置
     * @returns {Promise<void>}
     * @private
     */
    _callWxJsApi(wxConfig) {
        return new Promise((resolve, reject) => {
            if (typeof WeixinJSBridge === 'undefined') {
                // 微信浏览器环境检查
                if (typeof wx === 'undefined') {
                    reject(new Error('请在微信浏览器中打开'));
                    return;
                }
            }

            const payParams = {
                appId: wxConfig.appId,
                timeStamp: wxConfig.timeStamp,
                nonceStr: wxConfig.nonceStr,
                package: wxConfig.package,
                signType: wxConfig.signType,
                paySign: wxConfig.paySign
            };

            // 微信JSAPI支付调用
            const payFunction = () => {
                WeixinJSBridge.invoke('getBrandWCPayRequest', payParams, (res) => {
                    if (res.err_msg === 'get_brand_wcpay_request:ok') {
                        // 支付成功，开始轮询
                        this._startPolling();
                        resolve();
                    } else if (res.err_msg === 'get_brand_wcpay_request:cancel') {
                        // 用户取消支付
                        this._onPaymentCancel();
                        reject(new Error('用户取消支付'));
                    } else {
                        // 支付失败
                        this._onPaymentFail(res.err_msg || '支付失败');
                        reject(new Error(res.err_msg || '支付失败'));
                    }
                });
            };

            // 确保WeixinJSBridge已就绪
            if (typeof WeixinJSBridge === 'undefined') {
                document.addEventListener('WeixinJSBridgeReady', payFunction, false);
            } else {
                payFunction();
            }
        });
    }

    /**
     * 开始轮询支付状态
     * @private
     */
    _startPolling() {
        this.state.isPolling = true;
        this.state.pollAttempts = 0;
        this._showToast('支付处理中，请稍候...', 'info');
        this._pollPaymentStatus();
    }

    /**
     * 轮询支付状态
     * @private
     */
    async _pollPaymentStatus() {
        if (!this.state.isPolling) return;

        this.state.pollAttempts++;

        // 检查是否超过最大轮询次数
        if (this.state.pollAttempts > PAYMENT_CONFIG.MAX_POLL_ATTEMPTS) {
            this._stopPolling();
            this._showToast('支付状态查询超时，请联系客服', 'warning');
            this._onPaymentFail('支付状态查询超时');
            return;
        }

        try {
            const response = await fetch(`${PAYMENT_CONFIG.POLL_URL}/${this.state.orderId}`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            switch (data.status) {
                case 'success':
                    // 支付成功
                    this._stopPolling();
                    this._onPaymentSuccess(data);
                    break;

                case 'fail':
                    // 支付失败
                    this._stopPolling();
                    this._onPaymentFail(data.message || '支付失败');
                    break;

                case 'processing':
                    // 支付处理中，继续轮询
                    this.state.pollTimer = setTimeout(() => {
                        this._pollPaymentStatus();
                    }, PAYMENT_CONFIG.POLL_INTERVAL);
                    break;

                case 'cancel':
                    // 支付取消
                    this._stopPolling();
                    this._onPaymentCancel();
                    break;

                default:
                    // 未知状态，继续轮询
                    this.state.pollTimer = setTimeout(() => {
                        this._pollPaymentStatus();
                    }, PAYMENT_CONFIG.POLL_INTERVAL);
            }

        } catch (error) {
            console.error('轮询支付状态失败:', error);
            // 网络错误，继续重试
            this.state.pollTimer = setTimeout(() => {
                this._pollPaymentStatus();
            }, PAYMENT_CONFIG.POLL_INTERVAL);
        }
    }

    /**
     * 停止轮询
     * @private
     */
    _stopPolling() {
        this.state.isPolling = false;
        if (this.state.pollTimer) {
            clearTimeout(this.state.pollTimer);
            this.state.pollTimer = null;
        }
    }

    /**
     * 支付成功回调
     * @param {Object} data - 支付成功数据
     * @private
     */
    _onPaymentSuccess(data) {
        this._showToast('支付成功！', 'success');
        
        // 触发自定义事件
        const event = new CustomEvent('payment:success', {
            detail: {
                orderId: this.state.orderId,
                data: data
            }
        });
        document.dispatchEvent(event);

        // 执行回调
        if (typeof this.state.callbacks.onSuccess === 'function') {
            this.state.callbacks.onSuccess(data);
        }

        // 跳转到结果页面
        setTimeout(() => {
            window.location.href = `${PAYMENT_CONFIG.RESULT_URL}/${this.state.orderId}`;
        }, 1500);
    }

    /**
     * 支付失败回调
     * @param {string} message - 失败信息
     * @private
     */
    _onPaymentFail(message) {
        this._showToast(message || '支付失败', 'error');

        // 触发自定义事件
        const event = new CustomEvent('payment:fail', {
            detail: {
                orderId: this.state.orderId,
                message: message
            }
        });
        document.dispatchEvent(event);

        // 执行回调
        if (typeof this.state.callbacks.onFail === 'function') {
            this.state.callbacks.onFail(message);
        }
    }

    /**
     * 支付取消回调
     * @private
     */
    _onPaymentCancel() {
        this._showToast('支付已取消', 'info');

        // 触发自定义事件
        const event = new CustomEvent('payment:cancel', {
            detail: {
                orderId: this.state.orderId
            }
        });
        document.dispatchEvent(event);

        // 执行回调
        if (typeof this.state.callbacks.onCancel === 'function') {
            this.state.callbacks.onCancel();
        }
    }

    /**
     * 显示加载状态
     * @param {boolean} show - 是否显示
     * @private
     */
    _showLoading(show) {
        const loadingEl = document.getElementById('payment-loading');
        if (loadingEl) {
            loadingEl.style.display = show ? 'flex' : 'none';
        }
    }

    /**
     * 显示Toast提示
     * @param {string} message - 提示信息
     * @param {string} type - 提示类型 (success/error/warning/info)
     * @private
     */
    _showToast(message, type = 'info') {
        // 检查是否已有Toast容器
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.style.cssText = `
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                z-index: 10000;
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 10px;
            `;
            document.body.appendChild(toastContainer);
        }

        // 创建Toast元素
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            padding: 12px 24px;
            border-radius: 8px;
            color: #fff;
            font-size: 14px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            animation: toastIn 0.3s ease;
            max-width: 80vw;
            text-align: center;
        `;

        // 根据类型设置颜色
        const colors = {
            success: '#52c41a',
            error: '#ff4d4f',
            warning: '#faad14',
            info: '#1890ff'
        };
        toast.style.backgroundColor = colors[type] || colors.info;

        toastContainer.appendChild(toast);

        // 3秒后自动移除
        setTimeout(() => {
            toast.style.animation = 'toastOut 0.3s ease';
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }, 3000);
    }

    /**
     * 设置回调函数
     * @param {Object} callbacks - 回调函数对象
     */
    setCallbacks(callbacks) {
        if (callbacks.onSuccess) this.state.callbacks.onSuccess = callbacks.onSuccess;
        if (callbacks.onFail) this.state.callbacks.onFail = callbacks.onFail;
        if (callbacks.onCancel) this.state.callbacks.onCancel = callbacks.onCancel;
        if (callbacks.onProcessing) this.state.callbacks.onProcessing = callbacks.onProcessing;
    }
}

// ============================================================
// 初始化
// ============================================================
// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes toastIn {
        from {
            opacity: 0;
            transform: translateY(-20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    @keyframes toastOut {
        from {
            opacity: 1;
            transform: translateY(0);
        }
        to {
            opacity: 0;
            transform: translateY(-20px);
        }
    }
`;
document.head.appendChild(style);

// 创建全局支付处理器实例
const paymentHandler = new PaymentHandler();

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { PaymentHandler, paymentHandler };
} else {
    window.PaymentHandler = PaymentHandler;
    window.paymentHandler = paymentHandler;
}