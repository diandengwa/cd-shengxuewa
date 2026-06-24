/**
 * K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
 * 付费模式重构 — 按次诊断计费方案
 * 前端支付交互JS：购买套餐、微信支付唤起、余额显示、诊断确认弹窗
 * 
 * @file app/static/js/payment_v2.js
 * @version 2.0.0
 */

// ============================================================
// 全局状态管理
// ============================================================
const PaymentState = {
    // 用户信息
    user: null,
    // 余额信息
    balance: 0,
    // 套餐列表
    packages: [],
    // 当前选中的套餐
    selectedPackage: null,
    // 诊断次数
    diagnosisCount: 0,
    // 支付状态
    paymentStatus: 'idle', // idle | processing | success | failed
    // 微信支付参数
    wxPayParams: null,
    // 诊断确认弹窗状态
    confirmDialogOpen: false,
    // 当前诊断ID（用于确认弹窗）
    currentDiagnosisId: null,
    // 回调URL
    callbackUrl: null,
    // 微信支付轮询定时器
    wxPayPollTimer: null,
    // 微信支付倒计时
    wxPayCountdown: 300, // 5分钟倒计时（秒）
    // 微信支付倒计时定时器
    wxPayCountdownTimer: null,
    // 三档定价配置
    pricingTiers: {
        single: { credits: 1, price: 29.90, label: '单次诊断' },
        basic: { credits: 5, price: 99.90, label: '基础套餐' },
        premium: { credits: 15, price: 199.90, label: '高级套餐' }
    },
    // 当前选中的定价档位
    selectedTier: null
};

// ============================================================
// DOM 元素缓存
// ============================================================
const DOM = {
    // 余额显示
    balanceDisplay: document.getElementById('balance-display'),
    balanceAmount: document.getElementById('balance-amount'),
    balanceLoading: document.getElementById('balance-loading'),
    
    // 套餐选择
    packageContainer: document.getElementById('package-container'),
    packageList: document.getElementById('package-list'),
    packageLoading: document.getElementById('package-loading'),
    packageError: document.getElementById('package-error'),
    
    // 三档定价选择
    pricingContainer: document.getElementById('pricing-container'),
    pricingTiers: document.querySelectorAll('.pricing-tier'),
    pricingLoading: document.getElementById('pricing-loading'),
    
    // 支付按钮
    payButton: document.getElementById('pay-button'),
    payButtonText: document.getElementById('pay-button-text'),
    payButtonLoading: document.getElementById('pay-button-loading'),
    
    // 诊断确认弹窗
    confirmDialog: document.getElementById('confirm-dialog'),
    confirmDialogOverlay: document.getElementById('confirm-dialog-overlay'),
    confirmDiagnosisInfo: document.getElementById('confirm-diagnosis-info'),
    confirmPackageInfo: document.getElementById('confirm-package-info'),
    confirmBalanceInfo: document.getElementById('confirm-balance-info'),
    confirmButton: document.getElementById('confirm-button'),
    cancelButton: document.getElementById('cancel-button'),
    
    // 支付结果弹窗
    paymentResultDialog: document.getElementById('payment-result-dialog'),
    paymentResultOverlay: document.getElementById('payment-result-overlay'),
    paymentResultIcon: document.getElementById('payment-result-icon'),
    paymentResultTitle: document.getElementById('payment-result-title'),
    paymentResultMessage: document.getElementById('payment-result-message'),
    paymentResultButton: document.getElementById('payment-result-button'),
    
    // 微信支付二维码
    wxPayQrCode: document.getElementById('wx-pay-qrcode'),
    wxPayQrCodeContainer: document.getElementById('wx-pay-qrcode-container'),
    wxPayStatus: document.getElementById('wx-pay-status'),
    wxPayTimer: document.getElementById('wx-pay-timer'),
    
    // 错误提示
    errorToast: document.getElementById('error-toast'),
    errorToastMessage: document.getElementById('error-toast-message'),
    errorToastClose: document.getElementById('error-toast-close'),
    
    // credits购买相关
    creditsAmount: document.getElementById('credits-amount'),
    creditsPrice: document.getElementById('credits-price'),
    creditsBuyButton: document.getElementById('credits-buy-button')
};

// ============================================================
// 工具函数
// ============================================================

/**
 * 格式化金额（分转元）
 * @param {number} amount - 金额（分）
 * @returns {string} 格式化后的金额字符串
 */
function formatAmount(amount) {
    if (amount === null || amount === undefined) return '0.00';
    return (amount / 100).toFixed(2);
}

/**
 * 格式化时间（秒转分钟:秒）
 * @param {number} seconds - 秒数
 * @returns {string} 格式化后的时间字符串
 */
function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

/**
 * 显示错误提示
 * @param {string} message - 错误信息
 */
function showError(message) {
    if (DOM.errorToast && DOM.errorToastMessage) {
        DOM.errorToastMessage.textContent = message;
        DOM.errorToast.classList.remove('hidden');
        DOM.errorToast.classList.add('show');
        // 5秒后自动隐藏
        setTimeout(() => {
            DOM.errorToast.classList.remove('show');
            DOM.errorToast.classList.add('hidden');
        }, 5000);
    }
}

/**
 * 隐藏错误提示
 */
function hideError() {
    if (DOM.errorToast) {
        DOM.errorToast.classList.remove('show');
        DOM.errorToast.classList.add('hidden');
    }
}

/**
 * 显示加载状态
 * @param {HTMLElement} element - 要显示加载状态的元素
 */
function showLoading(element) {
    if (element) {
        element.classList.remove('hidden');
        element.classList.add('show');
    }
}

/**
 * 隐藏加载状态
 * @param {HTMLElement} element - 要隐藏加载状态的元素
 */
function hideLoading(element) {
    if (element) {
        element.classList.remove('show');
        element.classList.add('hidden');
    }
}

/**
 * 显示弹窗
 * @param {HTMLElement} dialog - 弹窗元素
 * @param {HTMLElement} overlay - 遮罩层元素
 */
function showDialog(dialog, overlay) {
    if (dialog && overlay) {
        dialog.classList.remove('hidden');
        dialog.classList.add('show');
        overlay.classList.remove('hidden');
        overlay.classList.add('show');
        document.body.style.overflow = 'hidden';
    }
}

/**
 * 隐藏弹窗
 * @param {HTMLElement} dialog - 弹窗元素
 * @param {HTMLElement} overlay - 遮罩层元素
 */
function hideDialog(dialog, overlay) {
    if (dialog && overlay) {
        dialog.classList.remove('show');
        dialog.classList.add('hidden');
        overlay.classList.remove('show');
        overlay.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

// ============================================================
// API 请求函数
// ============================================================

/**
 * 获取用户余额
 * @returns {Promise<number>} 用户余额（分）
 */
async function fetchBalance() {
    try {
        const response = await fetch('/api/v2/user/balance', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        
        if (!response.ok) {
            throw new Error(`获取余额失败: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '获取余额失败');
        }
        
        PaymentState.balance = data.data.balance || 0;
        return PaymentState.balance;
    } catch (error) {
        console.error('获取余额失败:', error);
        showError('获取余额失败，请刷新页面重试');
        throw error;
    }
}

/**
 * 获取套餐列表
 * @returns {Promise<Array>} 套餐列表
 */
async function fetchPackages() {
    try {
        const response = await fetch('/api/v2/packages', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        
        if (!response.ok) {
            throw new Error(`获取套餐列表失败: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '获取套餐列表失败');
        }
        
        PaymentState.packages = data.data.packages || [];
        return PaymentState.packages;
    } catch (error) {
        console.error('获取套餐列表失败:', error);
        showError('获取套餐列表失败，请刷新页面重试');
        throw error;
    }
}

/**
 * 创建支付订单
 * @param {string} packageId - 套餐ID
 * @returns {Promise<Object>} 支付订单信息
 */
async function createPaymentOrder(packageId) {
    try {
        const response = await fetch('/api/v2/payment/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                package_id: packageId,
                payment_method: 'wechat'
            })
        });
        
        if (!response.ok) {
            throw new Error(`创建支付订单失败: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '创建支付订单失败');
        }
        
        return data.data;
    } catch (error) {
        console.error('创建支付订单失败:', error);
        showError('创建支付订单失败，请稍后重试');
        throw error;
    }
}

/**
 * 查询支付状态
 * @param {string} orderId - 订单ID
 * @returns {Promise<Object>} 支付状态信息
 */
async function queryPaymentStatus(orderId) {
    try {
        const response = await fetch(`/api/v2/payment/status/${orderId}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        
        if (!response.ok) {
            throw new Error(`查询支付状态失败: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '查询支付状态失败');
        }
        
        return data.data;
    } catch (error) {
        console.error('查询支付状态失败:', error);
        throw error;
    }
}

/**
 * 购买credits
 * @param {string} tier - 定价档位
 * @returns {Promise<Object>} 购买结果
 */
async function purchaseCredits(tier) {
    try {
        const response = await fetch('/api/v2/credits/purchase', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                tier: tier,
                payment_method: 'wechat'
            })
        });
        
        if (!response.ok) {
            throw new Error(`购买credits失败: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '购买credits失败');
        }
        
        return data.data;
    } catch (error) {
        console.error('购买credits失败:', error);
        showError('购买credits失败，请稍后重试');
        throw error;
    }
}

/**
 * 使用诊断次数
 * @param {string} diagnosisId - 诊断ID
 * @returns {Promise<Object>} 使用结果
 */
async function useDiagnosis(diagnosisId) {
    try {
        const response = await fetch('/api/v2/diagnosis/use', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                diagnosis_id: diagnosisId
            })
        });
        
        if (!response.ok) {
            throw new Error(`使用诊断次数失败: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '使用诊断次数失败');
        }
        
        return data.data;
    } catch (error) {
        console.error('使用诊断次数失败:', error);
        showError('使用诊断次数失败，请稍后重试');
        throw error;
    }
}

// ============================================================
// UI 更新函数
// ============================================================

/**
 * 更新余额显示
 */
function updateBalanceDisplay() {
    if (DOM.balanceAmount) {
        DOM.balanceAmount.textContent = formatAmount(PaymentState.balance);
    }
    if (DOM.balanceLoading) {
        hideLoading(DOM.balanceLoading);
    }
    if (DOM.balanceDisplay) {
        DOM.balanceDisplay.classList.remove('hidden');
    }
}

/**
 * 更新套餐列表显示
 * @param {Array} packages - 套餐列表
 */
function updatePackageList(packages) {
    if (!DOM.packageList) return;
    
    // 清空现有列表
    DOM.packageList.innerHTML = '';
    
    if (!packages || packages.length === 0) {
        DOM.packageList.innerHTML = '<div class="empty-state">暂无可用套餐</div>';
        return;
    }
    
    // 渲染套餐列表
    packages.forEach(pkg => {
        const packageElement = document.createElement('div');
        packageElement.className = 'package-item';
        packageElement.dataset.packageId = pkg.id;
        
        packageElement.innerHTML = `
            <div class="package-info">
                <h3 class="package-name">${pkg.name}</h3>
                <p class="package-description">${pkg.description || ''}</p>
                <div class="package-details">
                    <span class="package-credits">${pkg.credits} 次诊断</span>
                    <span class="package-price">¥${formatAmount(pkg.price)}</span>
                </div>
            </div>
            <div class="package-select">
                <input type="radio" name="package" value="${pkg.id}" id="package-${pkg.id}">
                <label for="package-${pkg.id}">选择</label>
            </div>
        `;
        
        // 添加选择事件
        packageElement.addEventListener('click', () => {
            selectPackage(pkg);
        });
        
        DOM.packageList.appendChild(packageElement);
    });
    
    // 隐藏加载状态
    if (DOM.packageLoading) {
        hideLoading(DOM.packageLoading);
    }
}

/**
 * 更新三档定价显示
 */
function updatePricingDisplay() {
    if (!DOM.pricingTiers) return;
    
    const tiers = PaymentState.pricingTiers;
    
    DOM.pricingTiers.forEach(tierElement => {
        const tier = tierElement.dataset.tier;
        if (tier && tiers[tier]) {
            const tierData = tiers[tier];
            const creditsElement = tierElement.querySelector('.tier-credits');
            const priceElement = tierElement.querySelector('.tier-price');
            const labelElement = tierElement.querySelector('.tier-label');
            
            if (creditsElement) creditsElement.textContent = `${tierData.credits} 次`;
            if (priceElement) priceElement.textContent = `¥${tierData.price.toFixed(2)}`;
            if (labelElement) labelElement.textContent = tierData.label;
            
            // 添加选择事件
            tierElement.addEventListener('click', () => {
                selectPricingTier(tier);
            });
        }
    });
    
    // 隐藏加载状态
    if (DOM.pricingLoading) {
        hideLoading(DOM.pricingLoading);
    }
}

/**
 * 选择套餐
 * @param {Object} pkg - 套餐对象
 */
function selectPackage(pkg) {
    PaymentState.selectedPackage = pkg;
    
    // 更新UI选中状态
    const packageItems = document.querySelectorAll('.package-item');
    packageItems.forEach(item => {
        item.classList.remove('selected');
        if (item.dataset.packageId === pkg.id) {
            item.classList.add('selected');
            const radio = item.querySelector('input[type="radio"]');
            if (radio) radio.checked = true;
        }
    });
    
    // 更新支付按钮状态
    updatePayButton();
}

/**
 * 选择定价档位
 * @param {string} tier - 定价档位
 */
function selectPricingTier(tier) {
    PaymentState.selectedTier = tier;
    
    // 更新UI选中状态
    DOM.pricingTiers.forEach(tierElement => {
        tierElement.classList.remove('selected');
        if (tierElement.dataset.tier === tier) {
            tierElement.classList.add('selected');
        }
    });
    
    // 更新credits购买信息
    if (DOM.creditsAmount && DOM.creditsPrice) {
        const tierData = PaymentState.pricingTiers[tier];
        if (tierData) {
            DOM.creditsAmount.textContent = `${tierData.credits} 次诊断`;
            DOM.creditsPrice.textContent = `¥${tierData.price.toFixed(2)}`;
        }
    }
    
    // 更新支付按钮状态
    updatePayButton();
}

/**
 * 更新支付按钮状态
 */
function updatePayButton() {
    if (!DOM.payButton || !DOM.payButtonText) return;
    
    const hasSelection = PaymentState.selectedPackage || PaymentState.selectedTier;
    
    if (hasSelection) {
        DOM.payButton.disabled = false;
        DOM.payButton.classList.remove('disabled');
        
        if (PaymentState.selectedPackage) {
            DOM.payButtonText.textContent = `支付 ¥${formatAmount(PaymentState.selectedPackage.price)}`;
        } else if (PaymentState.selectedTier) {
            const tierData = PaymentState.pricingTiers[PaymentState.selectedTier];
            DOM.payButtonText.textContent = `购买 ¥${tierData.price.toFixed(2)}`;
        }
    } else {
        DOM.payButton.disabled = true;
        DOM.payButton.classList.add('disabled');
        DOM.payButtonText.textContent = '请选择套餐';
    }
}

/**
 * 显示诊断确认弹窗
 * @param {string} diagnosisId - 诊断ID
 */
function showConfirmDialog(diagnosisId) {
    PaymentState.currentDiagnosisId = diagnosisId;
    
    // 更新弹窗信息
    if (DOM.confirmDiagnosisInfo) {
        DOM.confirmDiagnosisInfo.textContent = `诊断ID: ${diagnosisId}`;
    }
    
    if (DOM.confirmPackageInfo) {
        if (PaymentState.selectedPackage) {
            DOM.confirmPackageInfo.textContent = `套餐: ${PaymentState.selectedPackage.name} (${PaymentState.selectedPackage.credits}次)`;
        } else if (PaymentState.selectedTier) {
            const tierData = PaymentState.pricingTiers[PaymentState.selectedTier];
            DOM.confirmPackageInfo.textContent = `套餐: ${tierData.label} (${tierData.credits}次)`;
        }
    }
    
    if (DOM.confirmBalanceInfo) {
        DOM.confirmBalanceInfo.textContent = `当前余额: ${formatAmount(PaymentState.balance)} 次`;
    }
    
    // 显示弹窗
    showDialog(DOM.confirmDialog, DOM.confirmDialogOverlay);
    PaymentState.confirmDialogOpen = true;
}

/**
 * 隐藏诊断确认弹窗
 */
function hideConfirmDialog() {
    hideDialog(DOM.confirmDialog, DOM.confirmDialogOverlay);
    PaymentState.confirmDialogOpen = false;
    PaymentState.currentDiagnosisId = null;
}

/**
 * 显示支付结果弹窗
 * @param {boolean} success - 是否成功
 * @param {string} title - 标题
 * @param {string} message - 消息
 */
function showPaymentResult(success, title, message) {
    if (DOM.paymentResultIcon) {
        DOM.paymentResultIcon.className = success ? 'icon-success' : 'icon-failed';
        DOM.paymentResultIcon.textContent = success ? '✓' : '✗';
    }
    
    if (DOM.paymentResultTitle) {
        DOM.paymentResultTitle.textContent = title;
    }
    
    if (DOM.paymentResultMessage) {
        DOM.paymentResultMessage.textContent = message;
    }
    
    showDialog(DOM.paymentResultDialog, DOM.paymentResultOverlay);
}

/**
 * 隐藏支付结果弹窗
 */
function hidePaymentResult() {
    hideDialog(DOM.paymentResultDialog, DOM.paymentResultOverlay);
}

/**
 * 显示微信支付二维码
 * @param {string} qrCodeUrl - 二维码URL
 */
function showWxPayQrCode(qrCodeUrl) {
    if (DOM.wxPayQrCode) {
        DOM.wxPayQrCode.src = qrCodeUrl;
        DOM.wxPayQrCode.alt = '微信支付二维码';
    }
    
    if (DOM.wxPayQrCodeContainer) {
        DOM.wxPayQrCodeContainer.classList.remove('hidden');
        DOM.wxPayQrCodeContainer.classList.add('show');
    }
    
    // 开始倒计时
    startWxPayCountdown();
}

/**
 * 隐藏微信支付二维码
 */
function hideWxPayQrCode() {
    if (DOM.wxPayQrCodeContainer) {
        DOM.wxPayQrCodeContainer.classList.remove('show');
        DOM.wxPayQrCodeContainer.classList.add('hidden');
    }
    
    // 停止倒计时
    stopWxPayCountdown();
}

/**
 * 开始微信支付倒计时
 */
function startWxPayCountdown() {
    PaymentState.wxPayCountdown = 300;
    
    if (DOM.wxPayTimer) {
        DOM.wxPayTimer.textContent = formatTime(PaymentState.wxPayCountdown);
    }
    
    PaymentState.wxPayCountdownTimer = setInterval(() => {
        PaymentState.wxPayCountdown--;
        
        if (DOM.wxPayTimer) {
            DOM.wxPayTimer.textContent = formatTime(PaymentState.wxPayCountdown);
        }
        
        if (PaymentState.wxPayCountdown <= 0) {
            stopWxPayCountdown();
            hideWxPayQrCode();
            showPaymentResult(false, '支付超时', '微信支付二维码已过期，请重新下单');
        }
    }, 1000);
}

/**
 * 停止微信支付倒计时
 */
function stopWxPayCountdown() {
    if (PaymentState.wxPayCountdownTimer) {
        clearInterval(PaymentState.wxPayCountdownTimer);
        PaymentState.wxPayCountdownTimer = null;
    }
}

/**
 * 开始轮询支付状态
 * @param {string} orderId - 订单ID
 */
function startWxPayPolling(orderId) {
    let pollCount = 0;
    const maxPolls = 60; // 最多轮询60次（5分钟）
    
    PaymentState.wxPayPollTimer = setInterval(async () => {
        pollCount++;
        
        try {
            const statusData = await queryPaymentStatus(orderId);
            
            if (statusData.status === 'success') {
                // 支付成功
                stopWxPayPolling();
                hideWxPayQrCode();
                
                // 更新余额
                await fetchBalance();
                updateBalanceDisplay();
                
                showPaymentResult(true, '支付成功', '您的诊断次数已到账');
                
                // 如果有待处理的诊断，自动使用
                if (PaymentState.currentDiagnosisId) {
                    await useDiagnosis(PaymentState.currentDiagnosisId);
                }
                
                // 触发支付成功回调
                if (PaymentState.callbackUrl) {
                    window.location.href = PaymentState.callbackUrl;
                }
            } else if (statusData.status === 'failed') {
                // 支付失败
                stopWxPayPolling();
                hideWxPayQrCode();
                showPaymentResult(false, '支付失败', '支付未成功，请重新下单');
            }
            
            // 更新支付状态显示
            if (DOM.wxPayStatus) {
                DOM.wxPayStatus.textContent = statusData.status === 'pending' ? '等待支付...' : statusData.status;
            }
        } catch (error) {
            console.error('轮询支付状态失败:', error);
        }
        
        // 超过最大轮询次数停止
        if (pollCount >= maxPolls) {
            stopWxPayPolling();
            hideWxPayQrCode();
            showPaymentResult(false, '支付超时', '支付状态查询超时，请确认是否已支付');
        }
    }, 5000); // 每5秒轮询一次
}

/**
 * 停止轮询支付状态
 */
function stopWxPayPolling() {
    if (PaymentState.wxPayPollTimer) {
        clearInterval(PaymentState.wxPayPollTimer);
        PaymentState.wxPayPollTimer = null;
    }
}

// ============================================================
// 支付流程处理
// ============================================================

/**
 * 处理支付按钮点击
 */
async function handlePayButtonClick() {
    if (PaymentState.paymentStatus === 'processing') return;
    
    PaymentState.paymentStatus = 'processing';
    
    // 显示加载状态
    if (DOM.payButtonLoading) {
        showLoading(DOM.payButtonLoading);
    }
    if (DOM.payButtonText) {
        DOM.payButtonText.textContent = '处理中...';
    }
    DOM.payButton.disabled = true;
    
    try {
        let orderData;
        
        if (PaymentState.selectedPackage) {
            // 购买套餐
            orderData = await createPaymentOrder(PaymentState.selectedPackage.id);
        } else if (PaymentState.selectedTier) {
            // 购买credits
            orderData = await purchaseCredits(PaymentState.selectedTier);
        } else {
            throw new Error('请选择套餐或定价档位');
        }
        
        // 保存微信支付参数
        PaymentState.wxPayParams = orderData.wx_pay_params;
        
        // 显示微信支付二维码
        if (orderData.qr_code_url) {
            showWxPayQrCode(orderData.qr_code_url);
        }
        
        // 开始轮询支付状态
        if (orderData.order_id) {
            startWxPayPolling(orderData.order_id);
        }
        
        // 重置支付状态
        PaymentState.paymentStatus = 'idle';
        
    } catch (error) {
        console.error('支付处理失败:', error);
        PaymentState.paymentStatus = 'failed';
        showPaymentResult(false, '支付失败', error.message || '支付处理失败，请稍后重试');
    } finally {
        // 恢复按钮状态
        if (DOM.payButtonLoading) {
            hideLoading(DOM.payButtonLoading);
        }
        DOM.payButton.disabled = false;
        updatePayButton();
    }
}

/**
 * 处理确认诊断按钮点击
 */
async function handleConfirmDiagnosis() {
    if (!PaymentState.currentDiagnosisId) {
        showError('诊断ID无效');
        return;
    }
    
    try {
        // 检查余额是否足够
        if (PaymentState.balance <= 0) {
            showConfirmDialog(PaymentState.currentDiagnosisId);
            return;
        }
        
        // 使用诊断次数
        await useDiagnosis(PaymentState.currentDiagnosisId);
        
        // 更新余额
        await fetchBalance();
        updateBalanceDisplay();
        
        // 隐藏确认弹窗
        hideConfirmDialog();
        
        // 显示成功消息
        showPaymentResult(true, '诊断已开始', '您的诊断请求已提交，请等待结果');
        
    } catch (error) {
        console.error('确认诊断失败:', error);
        showError('确认诊断失败，请稍后重试');
    }
}

// ============================================================
// 事件绑定
// ============================================================

/**
 * 初始化事件绑定
 */
function initEventBindings() {
    // 支付按钮点击事件
    if (DOM.payButton) {
        DOM.payButton.addEventListener('click', handlePayButtonClick);
    }
    
    // 确认按钮点击事件
    if (DOM.confirmButton) {
        DOM.confirmButton.addEventListener('click', handleConfirmDiagnosis);
    }
    
    // 取消按钮点击事件
    if (DOM.cancelButton) {
        DOM.cancelButton.addEventListener('click', hideConfirmDialog);
    }
    
    // 支付结果弹窗关闭按钮
    if (DOM.paymentResultButton) {
        DOM.paymentResultButton.addEventListener('click', hidePaymentResult);
    }
    
    // 错误提示关闭按钮
    if (DOM.errorToastClose) {
        DOM.errorToastClose.addEventListener('click', hideError);
    }
    
    // 点击遮罩层关闭弹窗
    if (DOM.confirmDialogOverlay) {
        DOM.confirmDialogOverlay.addEventListener('click', hideConfirmDialog);
    }
    
    if (DOM.paymentResultOverlay) {
        DOM.paymentResultOverlay.addEventListener('click', hidePaymentResult);
    }
    
    // credits购买按钮
    if (DOM.creditsBuyButton) {
        DOM.creditsBuyButton.addEventListener('click', handlePayButtonClick);
    }
}

// ============================================================
// 初始化
// ============================================================

/**
 * 页面初始化
 */
async function initPaymentPage() {
    try {
        // 显示加载状态
        if (DOM.balanceLoading) showLoading(DOM.balanceLoading);
        if (DOM.packageLoading) showLoading(DOM.packageLoading);
        if (DOM.pricingLoading) showLoading(DOM.pricingLoading);
        
        // 并行加载数据
        const [balance, packages] = await Promise.all([
            fetchBalance(),
            fetchPackages()
        ]);
        
        // 更新UI
        updateBalanceDisplay();
        updatePackageList(packages);
        updatePricingDisplay();
        
        // 初始化事件绑定
        initEventBindings();
        
        // 更新支付按钮状态
        updatePayButton();
        
    } catch (error) {
        console.error('页面初始化失败:', error);
        showError('页面加载失败，请刷新重试');
    }
}

// ============================================================
// 页面加载完成后初始化
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initPaymentPage();
});

// ============================================================
// 导出模块（用于测试）
// ============================================================
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        PaymentState,
        DOM,
        formatAmount,
        formatTime,
        showError,
        hideError,
        showLoading,
        hideLoading,
        showDialog,
        hideDialog,
        fetchBalance,
        fetchPackages,
        createPaymentOrder,
        queryPaymentStatus,
        purchaseCredits,
        useDiagnosis,
        updateBalanceDisplay,
        updatePackageList,
        updatePricingDisplay,
        selectPackage,
        selectPricingTier,
        updatePayButton,
        showConfirmDialog,
        hideConfirmDialog,
        showPaymentResult,
        hidePaymentResult,
        showWxPayQrCode,
        hideWxPayQrCode,
        startWxPayCountdown,
        stopWxPayCountdown,
        startWxPayPolling,
        stopWxPayPolling,
        handlePayButtonClick,
        handleConfirmDiagnosis,
        initEventBindings,
        initPaymentPage
    };
}