/**
 * payment.js — 前端支付交互逻辑
 * 功能：唤起微信支付、轮询订单状态、更新UI显示剩余次数
 * 项目：cd-shengxuewa（成都K12升学参谋）
 * 版本：2.0.0
 */

// ============================================================
// 全局状态
// ============================================================
const PaymentState = {
    POLL_INTERVAL: 2000,        // 轮询间隔（毫秒）
    MAX_POLL_COUNT: 60,         // 最大轮询次数（2分钟）
    POLL_TIMEOUT: 120000,       // 轮询超时（毫秒）
    currentOrderId: null,       // 当前订单ID
    pollTimer: null,            // 轮询定时器
    pollCount: 0,               // 当前轮询次数
    isProcessing: false,        // 是否正在处理
};

// ============================================================
// 工具函数
// ============================================================

/**
 * 显示错误消息
 * @param {string} message - 错误消息
 * @param {number} duration - 显示时长（毫秒）
 */
function showError(message, duration = 5000) {
    const errorContainer = document.getElementById('payment-error');
    if (!errorContainer) {
        console.error('[Payment] 错误:', message);
        return;
    }
    errorContainer.textContent = message;
    errorContainer.style.display = 'block';
    errorContainer.classList.add('payment-error--visible');
    
    setTimeout(() => {
        errorContainer.style.display = 'none';
        errorContainer.classList.remove('payment-error--visible');
    }, duration);
}

/**
 * 显示成功消息
 * @param {string} message - 成功消息
 * @param {number} duration - 显示时长（毫秒）
 */
function showSuccess(message, duration = 3000) {
    const successContainer = document.getElementById('payment-success');
    if (!successContainer) {
        console.log('[Payment] 成功:', message);
        return;
    }
    successContainer.textContent = message;
    successContainer.style.display = 'block';
    successContainer.classList.add('payment-success--visible');
    
    setTimeout(() => {
        successContainer.style.display = 'none';
        successContainer.classList.remove('payment-success--visible');
    }, duration);
}

/**
 * 显示加载状态
 * @param {boolean} show - 是否显示
 * @param {string} message - 加载消息
 */
function showLoading(show, message = '处理中...') {
    const loadingOverlay = document.getElementById('payment-loading');
    if (!loadingOverlay) return;
    
    if (show) {
        loadingOverlay.style.display = 'flex';
        loadingOverlay.querySelector('.loading-text').textContent = message;
    } else {
        loadingOverlay.style.display = 'none';
    }
}

/**
 * 格式化金额（分转元）
 * @param {number} amount - 金额（分）
 * @returns {string} 格式化后的金额
 */
function formatAmount(amount) {
    return (amount / 100).toFixed(2);
}

/**
 * 获取CSRF Token
 * @returns {string|null} CSRF Token
 */
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : null;
}

// ============================================================
// 核心支付逻辑
// ============================================================

/**
 * 创建支付订单
 * @param {number} amount - 支付金额（分）
 * @param {string} description - 订单描述
 * @returns {Promise<Object>} 订单信息
 */
async function createPaymentOrder(amount, description = '升学诊断服务') {
    try {
        const csrfToken = getCsrfToken();
        const response = await fetch('/api/payment/create-order', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrfToken || '',
            },
            body: JSON.stringify({
                amount: amount,
                description: description,
            }),
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || '创建订单失败');
        }

        return await response.json();
    } catch (error) {
        console.error('[Payment] 创建订单失败:', error);
        throw error;
    }
}

/**
 * 唤起微信支付
 * @param {Object} paymentParams - 微信支付参数
 * @returns {Promise<boolean>} 是否成功唤起
 */
async function invokeWechatPay(paymentParams) {
    // 检查是否在微信环境中
    const isWechat = navigator.userAgent.toLowerCase().includes('micromessenger');
    
    if (!isWechat) {
        showError('请在微信浏览器中打开进行支付');
        return false;
    }

    // 检查WeixinJSBridge是否可用
    if (typeof WeixinJSBridge === 'undefined') {
        // 等待WeixinJSBridge加载
        return new Promise((resolve) => {
            document.addEventListener('WeixinJSBridgeReady', async () => {
                const result = await doWechatPay(paymentParams);
                resolve(result);
            });
            // 超时处理
            setTimeout(() => {
                resolve(false);
                showError('微信支付初始化超时，请刷新页面重试');
            }, 5000);
        });
    }

    return await doWechatPay(paymentParams);
}

/**
 * 执行微信支付
 * @param {Object} paymentParams - 微信支付参数
 * @returns {Promise<boolean>} 是否成功唤起
 */
function doWechatPay(paymentParams) {
    return new Promise((resolve) => {
        WeixinJSBridge.invoke(
            'getBrandWCPayRequest',
            {
                appId: paymentParams.appId,
                timeStamp: paymentParams.timeStamp,
                nonceStr: paymentParams.nonceStr,
                package: paymentParams.package,
                signType: paymentParams.signType,
                paySign: paymentParams.paySign,
            },
            (res) => {
                if (res.err_msg === 'get_brand_wcpay_request:ok') {
                    resolve(true);
                } else if (res.err_msg === 'get_brand_wcpay_request:cancel') {
                    showError('支付已取消');
                    resolve(false);
                } else {
                    showError('支付失败: ' + (res.err_desc || '未知错误'));
                    resolve(false);
                }
            }
        );
    });
}

/**
 * 轮询订单状态
 * @param {string} orderId - 订单ID
 * @returns {Promise<Object>} 订单状态
 */
async function pollOrderStatus(orderId) {
    try {
        const csrfToken = getCsrfToken();
        const response = await fetch(`/api/payment/order-status/${orderId}`, {
            headers: {
                'X-CSRF-Token': csrfToken || '',
            },
        });

        if (!response.ok) {
            throw new Error('查询订单状态失败');
        }

        return await response.json();
    } catch (error) {
        console.error('[Payment] 轮询订单状态失败:', error);
        throw error;
    }
}

/**
 * 开始轮询订单状态
 * @param {string} orderId - 订单ID
 * @param {Function} onSuccess - 支付成功回调
 * @param {Function} onFail - 支付失败回调
 */
function startPolling(orderId, onSuccess, onFail) {
    // 清除之前的轮询
    stopPolling();

    PaymentState.currentOrderId = orderId;
    PaymentState.pollCount = 0;
    PaymentState.isProcessing = true;

    // 更新UI显示等待状态
    updatePaymentUI('waiting');

    PaymentState.pollTimer = setInterval(async () => {
        PaymentState.pollCount++;

        // 检查是否超时
        if (PaymentState.pollCount * PaymentState.POLL_INTERVAL >= PaymentState.POLL_TIMEOUT) {
            stopPolling();
            updatePaymentUI('timeout');
            showError('支付超时，请重新尝试');
            if (onFail) onFail(new Error('支付超时'));
            return;
        }

        try {
            const orderStatus = await pollOrderStatus(orderId);
            
            switch (orderStatus.status) {
                case 'success':
                    // 支付成功
                    stopPolling();
                    updatePaymentUI('success');
                    showSuccess('支付成功！');
                    
                    // 更新剩余次数
                    if (orderStatus.remaining_quota !== undefined) {
                        updateRemainingQuota(orderStatus.remaining_quota);
                    }
                    
                    if (onSuccess) onSuccess(orderStatus);
                    break;

                case 'failed':
                    // 支付失败
                    stopPolling();
                    updatePaymentUI('failed');
                    showError('支付失败，请重新尝试');
                    if (onFail) onFail(new Error('支付失败'));
                    break;

                case 'pending':
                    // 支付中，继续轮询
                    updatePaymentUI('pending');
                    break;

                default:
                    // 未知状态
                    console.warn('[Payment] 未知订单状态:', orderStatus.status);
            }
        } catch (error) {
            console.error('[Payment] 轮询出错:', error);
            // 继续轮询，不中断
        }
    }, PaymentState.POLL_INTERVAL);
}

/**
 * 停止轮询
 */
function stopPolling() {
    if (PaymentState.pollTimer) {
        clearInterval(PaymentState.pollTimer);
        PaymentState.pollTimer = null;
    }
    PaymentState.currentOrderId = null;
    PaymentState.pollCount = 0;
    PaymentState.isProcessing = false;
}

// ============================================================
// UI更新函数
// ============================================================

/**
 * 更新支付UI状态
 * @param {string} status - 支付状态
 */
function updatePaymentUI(status) {
    const paymentContainer = document.getElementById('payment-container');
    if (!paymentContainer) return;

    // 移除所有状态类
    paymentContainer.classList.remove(
        'payment--waiting',
        'payment--pending',
        'payment--success',
        'payment--failed',
        'payment--timeout'
    );

    // 添加当前状态类
    paymentContainer.classList.add(`payment--${status}`);

    // 更新状态文本
    const statusText = document.getElementById('payment-status-text');
    if (statusText) {
        const statusMessages = {
            waiting: '等待支付确认...',
            pending: '支付处理中...',
            success: '支付成功！',
            failed: '支付失败',
            timeout: '支付超时',
        };
        statusText.textContent = statusMessages[status] || '未知状态';
    }

    // 显示/隐藏加载状态
    showLoading(status === 'waiting' || status === 'pending');
}

/**
 * 更新剩余诊断次数显示
 * @param {number} remaining - 剩余次数
 */
function updateRemainingQuota(remaining) {
    const quotaElement = document.getElementById('remaining-quota');
    if (quotaElement) {
        quotaElement.textContent = remaining;
        quotaElement.classList.add('quota--updated');
        
        // 动画效果
        setTimeout(() => {
            quotaElement.classList.remove('quota--updated');
        }, 1000);
    }

    // 更新诊断按钮状态
    const diagnoseButton = document.getElementById('diagnose-button');
    if (diagnoseButton) {
        if (remaining <= 0) {
            diagnoseButton.disabled = true;
            diagnoseButton.title = '剩余次数不足，请充值';
        } else {
            diagnoseButton.disabled = false;
            diagnoseButton.title = `剩余 ${remaining} 次诊断机会`;
        }
    }

    // 触发自定义事件，通知其他组件
    const event = new CustomEvent('quota-updated', {
        detail: { remaining: remaining }
    });
    document.dispatchEvent(event);
}

/**
 * 更新价格显示
 * @param {number} amount - 金额（分）
 */
function updatePriceDisplay(amount) {
    const priceElement = document.getElementById('payment-amount');
    if (priceElement) {
        priceElement.textContent = `¥${formatAmount(amount)}`;
    }
}

// ============================================================
// 主要支付流程
// ============================================================

/**
 * 执行支付流程
 * @param {number} amount - 支付金额（分）
 * @param {string} description - 订单描述
 * @returns {Promise<boolean>} 是否支付成功
 */
async function processPayment(amount, description = '升学诊断服务') {
    // 防止重复提交
    if (PaymentState.isProcessing) {
        showError('正在处理中，请稍候...');
        return false;
    }

    try {
        // 显示加载状态
        showLoading(true, '正在创建订单...');

        // 1. 创建订单
        const orderData = await createPaymentOrder(amount, description);
        
        if (!orderData || !orderData.order_id) {
            throw new Error('创建订单失败：未获取到订单ID');
        }

        // 更新价格显示
        updatePriceDisplay(amount);

        // 2. 唤起微信支付
        showLoading(true, '正在唤起微信支付...');
        const payResult = await invokeWechatPay(orderData.payment_params);
        
        if (!payResult) {
            // 支付唤起失败，取消订单
            await cancelOrder(orderData.order_id);
            showLoading(false);
            return false;
        }

        // 3. 开始轮询订单状态
        return new Promise((resolve) => {
            startPolling(
                orderData.order_id,
                // 支付成功回调
                (orderStatus) => {
                    showLoading(false);
                    resolve(true);
                },
                // 支付失败回调
                (error) => {
                    showLoading(false);
                    resolve(false);
                }
            );
        });

    } catch (error) {
        console.error('[Payment] 支付流程失败:', error);
        showError(error.message || '支付失败，请重试');
        showLoading(false);
        return false;
    }
}

/**
 * 取消订单
 * @param {string} orderId - 订单ID
 */
async function cancelOrder(orderId) {
    try {
        const csrfToken = getCsrfToken();
        await fetch(`/api/payment/cancel-order/${orderId}`, {
            method: 'POST',
            headers: {
                'X-CSRF-Token': csrfToken || '',
            },
        });
    } catch (error) {
        console.error('[Payment] 取消订单失败:', error);
    }
}

// ============================================================
// 事件绑定与初始化
// ============================================================

/**
 * 初始化支付功能
 */
function initPayment() {
    console.log('[Payment] 初始化支付模块...');

    // 绑定支付按钮事件
    const payButton = document.getElementById('pay-button');
    if (payButton) {
        payButton.addEventListener('click', async (event) => {
            event.preventDefault();
            
            const amount = parseInt(payButton.dataset.amount, 10);
            const description = payButton.dataset.description || '升学诊断服务';
            
            if (isNaN(amount) || amount <= 0) {
                showError('无效的支付金额');
                return;
            }

            await processPayment(amount, description);
        });
    }

    // 绑定套餐选择事件
    const planSelectors = document.querySelectorAll('.plan-selector');
    planSelectors.forEach(selector => {
        selector.addEventListener('change', (event) => {
            const selectedPlan = event.target.value;
            const planData = JSON.parse(event.target.dataset.plans || '{}');
            
            if (planData[selectedPlan]) {
                updatePriceDisplay(planData[selectedPlan].amount);
                
                // 更新支付按钮数据
                const payButton = document.getElementById('pay-button');
                if (payButton) {
                    payButton.dataset.amount = planData[selectedPlan].amount;
                    payButton.dataset.description = planData[selectedPlan].description;
                }
            }
        });
    });

    // 绑定关闭按钮事件
    const closeButton = document.getElementById('payment-close');
    if (closeButton) {
        closeButton.addEventListener('click', () => {
            stopPolling();
            showLoading(false);
            const paymentModal = document.getElementById('payment-modal');
            if (paymentModal) {
                paymentModal.style.display = 'none';
            }
        });
    }

    // 页面卸载时清理
    window.addEventListener('beforeunload', () => {
        stopPolling();
    });

    console.log('[Payment] 支付模块初始化完成');
}

// ============================================================
// DOM加载完成后初始化
// ============================================================
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPayment);
} else {
    initPayment();
}

// ============================================================
// 导出接口（供其他模块使用）
// ============================================================
window.PaymentAPI = {
    processPayment: processPayment,
    updateRemainingQuota: updateRemainingQuota,
    getPaymentState: () => ({ ...PaymentState }),
};