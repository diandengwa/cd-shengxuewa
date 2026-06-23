/**
 * K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
 * 前端主脚本 — 集成支付和credits管理；添加诊断前检查钩子
 * 
 * 依赖: 无外部依赖，纯原生 JavaScript
 * 版本: 2.0.0
 */

(function() {
    'use strict';

    // ============================================================
    // 配置常量
    // ============================================================
    const CONFIG = {
        // API 端点
        API_BASE: '/api/v1',
        ENDPOINTS: {
            CHECK_CREDITS: '/credits/check',
            DEDUCT_CREDITS: '/credits/deduct',
            CREATE_PAYMENT: '/payment/create',
            PAYMENT_STATUS: '/payment/status',
            DIAGNOSE: '/diagnose'
        },
        // 诊断消耗的credits数量
        DIAGNOSE_COST: 1,
        // 轮询间隔（毫秒）
        POLL_INTERVAL: 2000,
        // 最大轮询次数
        MAX_POLL_COUNT: 30
    };

    // ============================================================
    // 状态管理
    // ============================================================
    const state = {
        credits: 0,
        isDiagnosing: false,
        paymentPollCount: 0,
        paymentPollTimer: null
    };

    // ============================================================
    // DOM 缓存
    // ============================================================
    let elements = {};

    /**
     * 缓存常用 DOM 元素
     */
    function cacheElements() {
        elements = {
            diagnoseBtn: document.getElementById('diagnose-btn'),
            creditsDisplay: document.getElementById('credits-display'),
            creditsModal: document.getElementById('credits-modal'),
            paymentModal: document.getElementById('payment-modal'),
            paymentQrCode: document.getElementById('payment-qrcode'),
            paymentStatus: document.getElementById('payment-status'),
            diagnoseForm: document.getElementById('diagnose-form'),
            errorMessage: document.getElementById('error-message'),
            loadingSpinner: document.getElementById('loading-spinner')
        };
    }

    // ============================================================
    // 工具函数
    // ============================================================

    /**
     * 发送 API 请求
     * @param {string} endpoint - API 路径
     * @param {object} data - 请求体数据
     * @param {string} method - HTTP 方法
     * @returns {Promise<object>} 响应数据
     */
    async function apiRequest(endpoint, data = {}, method = 'POST') {
        const url = `${CONFIG.API_BASE}${endpoint}`;
        
        try {
            const response = await fetch(url, {
                method: method,
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: method !== 'GET' ? JSON.stringify(data) : undefined,
                credentials: 'same-origin'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `请求失败: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API 请求错误 [${endpoint}]:`, error);
            throw error;
        }
    }

    /**
     * 显示错误消息
     * @param {string} message - 错误信息
     * @param {number} duration - 显示时长（毫秒）
     */
    function showError(message, duration = 5000) {
        if (elements.errorMessage) {
            elements.errorMessage.textContent = message;
            elements.errorMessage.style.display = 'block';
            
            setTimeout(() => {
                elements.errorMessage.style.display = 'none';
            }, duration);
        } else {
            alert(message);
        }
    }

    /**
     * 显示加载状态
     * @param {boolean} show - 是否显示
     */
    function showLoading(show) {
        if (elements.loadingSpinner) {
            elements.loadingSpinner.style.display = show ? 'block' : 'none';
        }
        if (elements.diagnoseBtn) {
            elements.diagnoseBtn.disabled = show;
            elements.diagnoseBtn.textContent = show ? '诊断中...' : '开始诊断';
        }
        state.isDiagnosing = show;
    }

    /**
     * 更新 credits 显示
     * @param {number} credits - 当前 credits 数量
     */
    function updateCreditsDisplay(credits) {
        state.credits = credits;
        if (elements.creditsDisplay) {
            elements.creditsDisplay.textContent = `剩余诊断次数: ${credits}`;
        }
    }

    // ============================================================
    // Credits 管理
    // ============================================================

    /**
     * 检查用户 credits 余额
     * @returns {Promise<number>} 当前 credits 数量
     */
    async function checkCredits() {
        try {
            const response = await apiRequest(CONFIG.ENDPOINTS.CHECK_CREDITS, {}, 'GET');
            const credits = response.credits || 0;
            updateCreditsDisplay(credits);
            return credits;
        } catch (error) {
            console.error('检查 credits 失败:', error);
            showError('无法获取诊断次数，请刷新页面重试');
            return 0;
        }
    }

    /**
     * 扣除诊断 credits
     * @returns {Promise<boolean>} 是否成功扣除
     */
    async function deductCredits() {
        try {
            const response = await apiRequest(CONFIG.ENDPOINTS.DEDUCT_CREDITS, {
                amount: CONFIG.DIAGNOSE_COST,
                description: '诊断消耗'
            });
            
            if (response.success) {
                updateCreditsDisplay(response.remaining_credits);
                return true;
            }
            return false;
        } catch (error) {
            console.error('扣除 credits 失败:', error);
            showError('诊断次数扣除失败');
            return false;
        }
    }

    // ============================================================
    // 支付管理
    // ============================================================

    /**
     * 创建支付订单
     * @param {number} amount - 支付金额（分）
     * @param {number} credits - 购买的 credits 数量
     * @returns {Promise<object>} 支付订单信息
     */
    async function createPayment(amount, credits) {
        try {
            const response = await apiRequest(CONFIG.ENDPOINTS.CREATE_PAYMENT, {
                amount: amount,
                credits: credits,
                description: `购买 ${credits} 次诊断次数`
            });
            return response;
        } catch (error) {
            console.error('创建支付订单失败:', error);
            showError('创建支付订单失败，请稍后重试');
            throw error;
        }
    }

    /**
     * 查询支付状态
     * @param {string} orderId - 订单 ID
     * @returns {Promise<object>} 支付状态信息
     */
    async function queryPaymentStatus(orderId) {
        try {
            const response = await apiRequest(`${CONFIG.ENDPOINTS.PAYMENT_STATUS}/${orderId}`, {}, 'GET');
            return response;
        } catch (error) {
            console.error('查询支付状态失败:', error);
            return { status: 'unknown' };
        }
    }

    /**
     * 轮询支付状态
     * @param {string} orderId - 订单 ID
     * @param {function} onSuccess - 支付成功回调
     * @param {function} onFail - 支付失败回调
     */
    function pollPaymentStatus(orderId, onSuccess, onFail) {
        state.paymentPollCount = 0;
        
        if (state.paymentPollTimer) {
            clearInterval(state.paymentPollTimer);
        }

        state.paymentPollTimer = setInterval(async () => {
            state.paymentPollCount++;

            try {
                const result = await queryPaymentStatus(orderId);
                
                if (result.status === 'success') {
                    clearInterval(state.paymentPollTimer);
                    state.paymentPollTimer = null;
                    
                    if (elements.paymentStatus) {
                        elements.paymentStatus.textContent = '支付成功！';
                        elements.paymentStatus.className = 'payment-status success';
                    }
                    
                    // 更新 credits
                    await checkCredits();
                    
                    if (onSuccess) onSuccess(result);
                } else if (result.status === 'failed' || result.status === 'expired') {
                    clearInterval(state.paymentPollTimer);
                    state.paymentPollTimer = null;
                    
                    if (elements.paymentStatus) {
                        elements.paymentStatus.textContent = '支付失败或已过期';
                        elements.paymentStatus.className = 'payment-status failed';
                    }
                    
                    if (onFail) onFail(result);
                } else if (state.paymentPollCount >= CONFIG.MAX_POLL_COUNT) {
                    clearInterval(state.paymentPollTimer);
                    state.paymentPollTimer = null;
                    
                    if (elements.paymentStatus) {
                        elements.paymentStatus.textContent = '支付超时，请重新尝试';
                        elements.paymentStatus.className = 'payment-status timeout';
                    }
                    
                    if (onFail) onFail({ status: 'timeout' });
                }
            } catch (error) {
                console.error('轮询支付状态出错:', error);
            }
        }, CONFIG.POLL_INTERVAL);
    }

    /**
     * 打开支付弹窗
     * @param {number} amount - 支付金额（分）
     * @param {number} credits - 购买的 credits 数量
     */
    async function openPaymentModal(amount, credits) {
        if (!elements.paymentModal) {
            showError('支付功能暂不可用');
            return;
        }

        try {
            // 显示加载状态
            if (elements.paymentQrCode) {
                elements.paymentQrCode.innerHTML = '<div class="loading">生成支付二维码中...</div>';
            }
            elements.paymentModal.style.display = 'block';

            // 创建支付订单
            const paymentResult = await createPayment(amount, credits);
            
            // 显示支付二维码
            if (elements.paymentQrCode && paymentResult.qr_code_url) {
                elements.paymentQrCode.innerHTML = `<img src="${paymentResult.qr_code_url}" alt="支付二维码">`;
            }

            // 更新支付状态
            if (elements.paymentStatus) {
                elements.paymentStatus.textContent = '请扫描二维码完成支付';
                elements.paymentStatus.className = 'payment-status pending';
            }

            // 开始轮询支付状态
            pollPaymentStatus(paymentResult.order_id, async (result) => {
                // 支付成功后的操作
                setTimeout(() => {
                    closePaymentModal();
                    showError('支付成功！诊断次数已更新', 3000);
                }, 1500);
            }, (result) => {
                // 支付失败后的操作
                console.warn('支付失败:', result);
            });

        } catch (error) {
            console.error('打开支付弹窗失败:', error);
            showError('支付功能异常，请稍后重试');
            closePaymentModal();
        }
    }

    /**
     * 关闭支付弹窗
     */
    function closePaymentModal() {
        if (elements.paymentModal) {
            elements.paymentModal.style.display = 'none';
        }
        if (state.paymentPollTimer) {
            clearInterval(state.paymentPollTimer);
            state.paymentPollTimer = null;
        }
    }

    // ============================================================
    // 诊断前检查钩子
    // ============================================================

    /**
     * 诊断前检查 — 确保用户有足够的 credits
     * @returns {Promise<boolean>} 是否通过检查
     */
    async function preDiagnoseCheck() {
        // 防止重复诊断
        if (state.isDiagnosing) {
            showError('正在诊断中，请稍候...');
            return false;
        }

        try {
            // 检查 credits
            const credits = await checkCredits();
            
            if (credits < CONFIG.DIAGNOSE_COST) {
                // credits 不足，提示购买
                const buyMore = confirm('诊断次数不足，是否前往购买？');
                if (buyMore) {
                    // 打开购买弹窗或跳转到购买页面
                    openPaymentModal(1000, 10); // 示例：10元购买10次
                }
                return false;
            }

            // 检查表单数据
            if (elements.diagnoseForm) {
                const formData = new FormData(elements.diagnoseForm);
                const requiredFields = ['student_name', 'grade', 'subject'];
                for (const field of requiredFields) {
                    if (!formData.get(field)) {
                        showError(`请填写 ${field} 字段`);
                        return false;
                    }
                }
            }

            return true;
        } catch (error) {
            console.error('诊断前检查失败:', error);
            showError('诊断前检查失败，请刷新页面重试');
            return false;
        }
    }

    /**
     * 执行诊断
     * @param {object} diagnoseData - 诊断数据
     * @returns {Promise<object>} 诊断结果
     */
    async function performDiagnose(diagnoseData) {
        showLoading(true);

        try {
            // 扣除 credits
            const deductSuccess = await deductCredits();
            if (!deductSuccess) {
                showLoading(false);
                showError('诊断次数扣除失败，请重试');
                return null;
            }

            // 发送诊断请求
            const result = await apiRequest(CONFIG.ENDPOINTS.DIAGNOSE, diagnoseData);
            
            showLoading(false);
            return result;
        } catch (error) {
            showLoading(false);
            console.error('诊断失败:', error);
            showError('诊断失败，请稍后重试');
            return null;
        }
    }

    // ============================================================
    // 事件绑定
    // ============================================================

    /**
     * 绑定诊断按钮点击事件
     */
    function bindDiagnoseButton() {
        if (!elements.diagnoseBtn) return;

        elements.diagnoseBtn.addEventListener('click', async (event) => {
            event.preventDefault();

            // 执行诊断前检查
            const checkPassed = await preDiagnoseCheck();
            if (!checkPassed) return;

            // 收集诊断数据
            let diagnoseData = {};
            if (elements.diagnoseForm) {
                const formData = new FormData(elements.diagnoseForm);
                formData.forEach((value, key) => {
                    diagnoseData[key] = value;
                });
            }

            // 执行诊断
            const result = await performDiagnose(diagnoseData);
            if (result) {
                // 处理诊断结果
                console.log('诊断结果:', result);
                // 可以在这里触发结果展示逻辑
                const event = new CustomEvent('diagnoseComplete', { detail: result });
                document.dispatchEvent(event);
            }
        });
    }

    /**
     * 绑定购买按钮事件
     */
    function bindPurchaseButtons() {
        // 绑定所有购买按钮
        document.querySelectorAll('[data-purchase]').forEach(button => {
            button.addEventListener('click', (event) => {
                const amount = parseInt(button.dataset.amount) || 1000; // 默认10元
                const credits = parseInt(button.dataset.credits) || 10; // 默认10次
                openPaymentModal(amount, credits);
            });
        });
    }

    /**
     * 绑定关闭弹窗事件
     */
    function bindModalCloseButtons() {
        // 关闭支付弹窗
        document.querySelectorAll('.modal-close, .modal-overlay').forEach(element => {
            element.addEventListener('click', () => {
                closePaymentModal();
                if (elements.creditsModal) {
                    elements.creditsModal.style.display = 'none';
                }
            });
        });
    }

    // ============================================================
    // 初始化
    // ============================================================

    /**
     * 页面初始化
     */
    async function init() {
        // 缓存 DOM 元素
        cacheElements();

        // 检查登录状态和 credits
        await checkCredits();

        // 绑定事件
        bindDiagnoseButton();
        bindPurchaseButtons();
        bindModalCloseButtons();

        // 监听自定义事件
        document.addEventListener('diagnoseComplete', (event) => {
            // 诊断完成后的处理逻辑
            console.log('诊断完成:', event.detail);
        });

        console.log('K12 Rocket v2.0 前端脚本初始化完成');
    }

    // 等待 DOM 加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();