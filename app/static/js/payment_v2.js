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
    wxPayCountdownTimer: null
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
    errorToastClose: document.getElementById('error-toast-close')
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
            hideError();
        }, 5000);
    }
}

/**
 * 隐藏错误提示
 */
function hideError() {
    if (DOM.errorToast) {
        DOM.errorToast.classList.add('hidden');
        DOM.errorToast.classList.remove('show');
    }
}

/**
 * 显示加载状态
 * @param {HTMLElement} element - 要显示加载状态的元素
 */
function showLoading(element) {
    if (element) {
        element.classList.remove('hidden');
    }
}

/**
 * 隐藏加载状态
 * @param {HTMLElement} element - 要隐藏加载状态的元素
 */
function hideLoading(element) {
    if (element) {
        element.classList.add('hidden');
    }
}

/**
 * 显示支付结果弹窗
 * @param {string} type - 结果类型：'success' | 'failed'
 * @param {string} title - 弹窗标题
 * @param {string} message - 弹窗消息
 */
function showPaymentResult(type, title, message) {
    if (!DOM.paymentResultDialog || !DOM.paymentResultOverlay) return;
    
    // 设置图标
    if (DOM.paymentResultIcon) {
        DOM.paymentResultIcon.className = type === 'success' 
            ? 'payment-result-icon success' 
            : 'payment-result-icon failed';
        DOM.paymentResultIcon.textContent = type === 'success' ? '✓' : '✕';
    }
    
    // 设置标题和消息
    if (DOM.paymentResultTitle) {
        DOM.paymentResultTitle.textContent = title;
    }
    if (DOM.paymentResultMessage) {
        DOM.paymentResultMessage.textContent = message;
    }
    
    // 显示弹窗
    DOM.paymentResultDialog.classList.remove('hidden');
    DOM.paymentResultOverlay.classList.remove('hidden');
}

/**
 * 隐藏支付结果弹窗
 */
function hidePaymentResult() {
    if (DOM.paymentResultDialog && DOM.paymentResultOverlay) {
        DOM.paymentResultDialog.classList.add('hidden');
        DOM.paymentResultOverlay.classList.add('hidden');
    }
}

/**
 * 显示诊断确认弹窗
 */
function showConfirmDialog() {
    if (!DOM.confirmDialog || !DOM.confirmDialogOverlay) return;
    
    // 更新弹窗信息
    if (DOM.confirmDiagnosisInfo && PaymentState.currentDiagnosisId) {
        DOM.confirmDiagnosisInfo.textContent = `诊断ID: ${PaymentState.currentDiagnosisId}`;
    }
    
    if (DOM.confirmPackageInfo && PaymentState.selectedPackage) {
        DOM.confirmPackageInfo.textContent = `套餐: ${PaymentState.selectedPackage.name} (${formatAmount(PaymentState.selectedPackage.price)}元/${PaymentState.selectedPackage.diagnosis_count}次)`;
    }
    
    if (DOM.confirmBalanceInfo) {
        DOM.confirmBalanceInfo.textContent = `当前余额: ${formatAmount(PaymentState.balance)}元 (可用诊断次数: ${PaymentState.diagnosisCount}次)`;
    }
    
    // 显示弹窗
    DOM.confirmDialog.classList.remove('hidden');
    DOM.confirmDialogOverlay.classList.remove('hidden');
    PaymentState.confirmDialogOpen = true;
}

/**
 * 隐藏诊断确认弹窗
 */
function hideConfirmDialog() {
    if (DOM.confirmDialog && DOM.confirmDialogOverlay) {
        DOM.confirmDialog.classList.add('hidden');
        DOM.confirmDialogOverlay.classList.add('hidden');
    }
    PaymentState.confirmDialogOpen = false;
}

/**
 * 显示微信支付二维码
 */
function showWxPayQrCode() {
    if (!DOM.wxPayQrCodeContainer) return;
    
    // 显示二维码容器
    DOM.wxPayQrCodeContainer.classList.remove('hidden');
    
    // 开始倒计时
    startWxPayCountdown();
    
    // 开始轮询支付状态
    startWxPayPolling();
}

/**
 * 隐藏微信支付二维码
 */
function hideWxPayQrCode() {
    if (DOM.wxPayQrCodeContainer) {
        DOM.wxPayQrCodeContainer.classList.add('hidden');
    }
    
    // 停止倒计时
    stopWxPayCountdown();
    
    // 停止轮询
    stopWxPayPolling();
}

/**
 * 开始微信支付倒计时
 */
function startWxPayCountdown() {
    PaymentState.wxPayCountdown = 300; // 5分钟
    
    if (DOM.wxPayTimer) {
        DOM.wxPayTimer.textContent = formatTime(PaymentState.wxPayCountdown);
    }
    
    // 清除之前的定时器
    if (PaymentState.wxPayCountdownTimer) {
        clearInterval(PaymentState.wxPayCountdownTimer);
    }
    
    // 开始倒计时
    PaymentState.wxPayCountdownTimer = setInterval(() => {
        PaymentState.wxPayCountdown--;
        
        if (DOM.wxPayTimer) {
            DOM.wxPayTimer.textContent = formatTime(PaymentState.wxPayCountdown);
        }
        
        // 倒计时结束
        if (PaymentState.wxPayCountdown <= 0) {
            stopWxPayCountdown();
            stopWxPayPolling();
            
            // 更新状态
            if (DOM.wxPayStatus) {
                DOM.wxPayStatus.textContent = '支付超时，请重新发起支付';
                DOM.wxPayStatus.className = 'wx-pay-status failed';
            }
            
            // 显示支付失败
            showPaymentResult('failed', '支付超时', '请在5分钟内完成支付，请重新发起支付');
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
 * 开始微信支付状态轮询
 */
function startWxPayPolling() {
    // 清除之前的轮询
    if (PaymentState.wxPayPollTimer) {
        clearInterval(PaymentState.wxPayPollTimer);
    }
    
    // 每3秒轮询一次
    PaymentState.wxPayPollTimer = setInterval(async () => {
        try {
            const response = await fetch('/api/v2/payment/status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    order_id: PaymentState.wxPayParams?.order_id
                })
            });
            
            if (!response.ok) {
                throw new Error('查询支付状态失败');
            }
            
            const data = await response.json();
            
            if (data.success) {
                const status = data.data.status;
                
                if (status === 'success') {
                    // 支付成功
                    stopWxPayPolling();
                    stopWxPayCountdown();
                    
                    if (DOM.wxPayStatus) {
                        DOM.wxPayStatus.textContent = '支付成功！';
                        DOM.wxPayStatus.className = 'wx-pay-status success';
                    }
                    
                    // 更新余额
                    await updateBalance();
                    
                    // 显示支付成功
                    showPaymentResult('success', '支付成功', '您的诊断次数已增加，可以开始诊断了');
                    
                    // 隐藏二维码
                    setTimeout(() => {
                        hideWxPayQrCode();
                    }, 2000);
                    
                } else if (status === 'failed') {
                    // 支付失败
                    stopWxPayPolling();
                    stopWxPayCountdown();
                    
                    if (DOM.wxPayStatus) {
                        DOM.wxPayStatus.textContent = '支付失败，请重新发起支付';
                        DOM.wxPayStatus.className = 'wx-pay-status failed';
                    }
                    
                    showPaymentResult('failed', '支付失败', '支付处理失败，请重新发起支付');
                }
            }
        } catch (error) {
            console.error('轮询支付状态失败:', error);
        }
    }, 3000);
}

/**
 * 停止微信支付状态轮询
 */
function stopWxPayPolling() {
    if (PaymentState.wxPayPollTimer) {
        clearInterval(PaymentState.wxPayPollTimer);
        PaymentState.wxPayPollTimer = null;
    }
}

// ============================================================
// 核心业务逻辑
// ============================================================

/**
 * 初始化支付模块
 */
async function initPayment() {
    try {
        // 加载用户信息
        await loadUserInfo();
        
        // 加载余额
        await updateBalance();
        
        // 加载套餐列表
        await loadPackages();
        
        // 绑定事件
        bindEvents();
        
    } catch (error) {
        console.error('初始化支付模块失败:', error);
        showError('初始化支付模块失败，请刷新页面重试');
    }
}

/**
 * 加载用户信息
 */
async function loadUserInfo() {
    try {
        const response = await fetch('/api/v2/user/info');
        if (!response.ok) {
            throw new Error('获取用户信息失败');
        }
        
        const data = await response.json();
        if (data.success) {
            PaymentState.user = data.data;
        }
    } catch (error) {
        console.error('加载用户信息失败:', error);
        showError('获取用户信息失败');
    }
}

/**
 * 更新余额显示
 */
async function updateBalance() {
    try {
        showLoading(DOM.balanceLoading);
        
        const response = await fetch('/api/v2/payment/balance');
        if (!response.ok) {
            throw new Error('获取余额失败');
        }
        
        const data = await response.json();
        if (data.success) {
            PaymentState.balance = data.data.balance;
            PaymentState.diagnosisCount = data.data.diagnosis_count;
            
            // 更新显示
            if (DOM.balanceAmount) {
                DOM.balanceAmount.textContent = formatAmount(PaymentState.balance);
            }
            
            if (DOM.balanceDisplay) {
                DOM.balanceDisplay.classList.remove('hidden');
            }
        }
    } catch (error) {
        console.error('更新余额失败:', error);
        showError('获取余额失败');
    } finally {
        hideLoading(DOM.balanceLoading);
    }
}

/**
 * 加载套餐列表
 */
async function loadPackages() {
    try {
        showLoading(DOM.packageLoading);
        hideLoading(DOM.packageError);
        
        const response = await fetch('/api/v2/payment/packages');
        if (!response.ok) {
            throw new Error('获取套餐列表失败');
        }
        
        const data = await response.json();
        if (data.success) {
            PaymentState.packages = data.data;
            renderPackages();
        }
    } catch (error) {
        console.error('加载套餐列表失败:', error);
        showError('获取套餐列表失败');
        
        if (DOM.packageError) {
            DOM.packageError.classList.remove('hidden');
        }
    } finally {
        hideLoading(DOM.packageLoading);
    }
}

/**
 * 渲染套餐列表
 */
function renderPackages() {
    if (!DOM.packageList) return;
    
    // 清空列表
    DOM.packageList.innerHTML = '';
    
    // 渲染每个套餐
    PaymentState.packages.forEach((pkg, index) => {
        const packageElement = document.createElement('div');
        packageElement.className = 'package-item';
        packageElement.dataset.packageId = pkg.id;
        
        packageElement.innerHTML = `
            <div class="package-header">
                <h3 class="package-name">${pkg.name}</h3>
                <span class="package-price">¥${formatAmount(pkg.price)}</span>
            </div>
            <div class="package-body">
                <p class="package-description">${pkg.description || ''}</p>
                <p class="package-diagnosis-count">诊断次数: ${pkg.diagnosis_count}次</p>
                ${pkg.original_price && pkg.original_price > pkg.price ? 
                    `<p class="package-original-price">原价: ¥${formatAmount(pkg.original_price)}</p>` : ''}
            </div>
            <div class="package-footer">
                <button class="btn-select-package" data-package-id="${pkg.id}">
                    选择套餐
                </button>
            </div>
        `;
        
        // 默认选中第一个套餐
        if (index === 0) {
            packageElement.classList.add('selected');
            PaymentState.selectedPackage = pkg;
        }
        
        // 点击选择套餐
        packageElement.querySelector('.btn-select-package').addEventListener('click', () => {
            selectPackage(pkg, packageElement);
        });
        
        DOM.packageList.appendChild(packageElement);
    });
    
    // 显示套餐容器
    if (DOM.packageContainer) {
        DOM.packageContainer.classList.remove('hidden');
    }
}

/**
 * 选择套餐
 * @param {Object} pkg - 套餐对象
 * @param {HTMLElement} element - 套餐元素
 */
function selectPackage(pkg, element) {
    // 取消其他套餐的选中状态
    document.querySelectorAll('.package-item').forEach(item => {
        item.classList.remove('selected');
    });
    
    // 选中当前套餐
    element.classList.add('selected');
    PaymentState.selectedPackage = pkg;
    
    // 启用支付按钮
    if (DOM.payButton) {
        DOM.payButton.disabled = false;
    }
}

/**
 * 绑定事件
 */
function bindEvents() {
    // 支付按钮点击
    if (DOM.payButton) {
        DOM.payButton.addEventListener('click', handlePay);
    }
    
    // 确认按钮点击
    if (DOM.confirmButton) {
        DOM.confirmButton.addEventListener('click', handleConfirm);
    }
    
    // 取消按钮点击
    if (DOM.cancelButton) {
        DOM.cancelButton.addEventListener('click', hideConfirmDialog);
    }
    
    // 支付结果弹窗关闭
    if (DOM.paymentResultButton) {
        DOM.paymentResultButton.addEventListener('click', hidePaymentResult);
    }
    
    // 错误提示关闭
    if (DOM.errorToastClose) {
        DOM.errorToastClose.addEventListener('click', hideError);
    }
    
    // 点击遮罩关闭弹窗
    if (DOM.confirmDialogOverlay) {
        DOM.confirmDialogOverlay.addEventListener('click', hideConfirmDialog);
    }
    
    if (DOM.paymentResultOverlay) {
        DOM.paymentResultOverlay.addEventListener('click', hidePaymentResult);
    }
}

/**
 * 处理支付按钮点击
 */
async function handlePay() {
    // 检查是否选择了套餐
    if (!PaymentState.selectedPackage) {
        showError('请先选择套餐');
        return;
    }
    
    // 检查支付状态
    if (PaymentState.paymentStatus === 'processing') {
        showError('正在处理支付，请稍候');
        return;
    }
    
    // 显示确认弹窗
    showConfirmDialog();
}

/**
 * 处理确认按钮点击
 */
async function handleConfirm() {
    // 隐藏确认弹窗
    hideConfirmDialog();
    
    // 设置支付状态为处理中
    PaymentState.paymentStatus = 'processing';
    
    // 更新按钮状态
    if (DOM.payButton) {
        DOM.payButton.disabled = true;
        showLoading(DOM.payButtonLoading);
        if (DOM.payButtonText) {
            DOM.payButtonText.textContent = '处理中...';
        }
    }
    
    try {
        // 发起支付请求
        const response = await fetch('/api/v2/payment/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                package_id: PaymentState.selectedPackage.id,
                callback_url: PaymentState.callbackUrl || window.location.href
            })
        });
        
        if (!response.ok) {
            throw new Error('创建支付订单失败');
        }
        
        const data = await response.json();
        
        if (data.success) {
            // 保存微信支付参数
            PaymentState.wxPayParams = data.data;
            
            // 显示微信支付二维码
            if (DOM.wxPayQrCode && data.data.qr_code_url) {
                DOM.wxPayQrCode.src = data.data.qr_code_url;
            }
            
            // 更新支付状态
            if (DOM.wxPayStatus) {
                DOM.wxPayStatus.textContent = '请使用微信扫描二维码完成支付';
                DOM.wxPayStatus.className = 'wx-pay-status pending';
            }
            
            // 显示二维码
            showWxPayQrCode();
            
        } else {
            throw new Error(data.message || '创建支付订单失败');
        }
        
    } catch (error) {
        console.error('支付失败:', error);
        showError(error.message || '支付失败，请重试');
        
        // 恢复按钮状态
        if (DOM.payButton) {
            DOM.payButton.disabled = false;
            hideLoading(DOM.payButtonLoading);
            if (DOM.payButtonText) {
                DOM.payButtonText.textContent = '立即购买';
            }
        }
        
        PaymentState.paymentStatus = 'failed';
    }
}

/**
 * 处理支付成功回调
 * @param {Object} data - 回调数据
 */
async function handlePaymentSuccess(data) {
    try {
        // 更新余额
        await updateBalance();
        
        // 显示支付成功
        showPaymentResult('success', '支付成功', '您的诊断次数已增加，可以开始诊断了');
        
        // 重置支付状态
        PaymentState.paymentStatus = 'success';
        
        // 恢复按钮状态
        if (DOM.payButton) {
            DOM.payButton.disabled = false;
            hideLoading(DOM.payButtonLoading);
            if (DOM.payButtonText) {
                DOM.payButtonText.textContent = '立即购买';
            }
        }
        
        // 隐藏二维码
        hideWxPayQrCode();
        
        // 触发支付成功回调
        if (PaymentState.callbackUrl) {
            window.location.href = PaymentState.callbackUrl;
        }
        
    } catch (error) {
        console.error('处理支付成功回调失败:', error);
    }
}

/**
 * 处理支付失败回调
 * @param {Object} data - 回调数据
 */
async function handlePaymentFailed(data) {
    try {
        // 显示支付失败
        showPaymentResult('failed', '支付失败', data.message || '支付处理失败，请重新发起支付');
        
        // 重置支付状态
        PaymentState.paymentStatus = 'failed';
        
        // 恢复按钮状态
        if (DOM.payButton) {
            DOM.payButton.disabled = false;
            hideLoading(DOM.payButtonLoading);
            if (DOM.payButtonText) {
                DOM.payButtonText.textContent = '立即购买';
            }
        }
        
        // 隐藏二维码
        hideWxPayQrCode();
        
    } catch (error) {
        console.error('处理支付失败回调失败:', error);
    }
}

// ============================================================
// 页面加载完成后初始化
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    // 检查必要的DOM元素是否存在
    if (!DOM.balanceDisplay && !DOM.packageContainer) {
        console.warn('支付模块DOM元素未找到，可能不在支付页面');
        return;
    }
    
    // 初始化支付模块
    initPayment().catch(error => {
        console.error('支付模块初始化失败:', error);
    });
});

// ============================================================
// 导出接口（供其他模块调用）
// ============================================================
window.PaymentV2 = {
    // 状态
    state: PaymentState,
    
    // 核心方法
    init: initPayment,
    updateBalance: updateBalance,
    loadPackages: loadPackages,
    
    // 支付方法
    handlePay: handlePay,
    handleConfirm: handleConfirm,
    
    // 回调处理
    handlePaymentSuccess: handlePaymentSuccess,
    handlePaymentFailed: handlePaymentFailed,
    
    // 弹窗控制
    showConfirmDialog: showConfirmDialog,
    hideConfirmDialog: hideConfirmDialog,
    showPaymentResult: showPaymentResult,
    hidePaymentResult: hidePaymentResult,
    
    // 微信支付
    showWxPayQrCode: showWxPayQrCode,
    hideWxPayQrCode: hideWxPayQrCode,
    
    // 错误提示
    showError: showError,
    hideError: hideError
};