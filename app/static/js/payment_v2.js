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
 * 显示弹窗
 * @param {HTMLElement} dialog - 弹窗元素
 * @param {HTMLElement} overlay - 遮罩层元素
 */
function showDialog(dialog, overlay) {
    if (dialog) {
        dialog.classList.remove('hidden');
        dialog.classList.add('show');
    }
    if (overlay) {
        overlay.classList.remove('hidden');
        overlay.classList.add('show');
    }
}

/**
 * 隐藏弹窗
 * @param {HTMLElement} dialog - 弹窗元素
 * @param {HTMLElement} overlay - 遮罩层元素
 */
function hideDialog(dialog, overlay) {
    if (dialog) {
        dialog.classList.add('hidden');
        dialog.classList.remove('show');
    }
    if (overlay) {
        overlay.classList.add('hidden');
        overlay.classList.remove('show');
    }
}

// ============================================================
// API 请求函数
// ============================================================

/**
 * 通用API请求
 * @param {string} url - 请求URL
 * @param {string} method - 请求方法
 * @param {object} data - 请求数据
 * @returns {Promise} 请求结果
 */
async function apiRequest(url, method = 'GET', data = null) {
    try {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        };
        
        if (data && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
            options.body = JSON.stringify(data);
        }
        
        const response = await fetch(url, options);
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `请求失败: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API请求错误:', error);
        throw error;
    }
}

// ============================================================
// 余额查询
// ============================================================

/**
 * 查询用户余额
 */
async function fetchBalance() {
    try {
        showLoading(DOM.balanceLoading);
        
        const data = await apiRequest('/api/v2/payment/balance');
        
        if (data.success) {
            PaymentState.balance = data.balance || 0;
            PaymentState.user = data.user || null;
            updateBalanceDisplay();
        } else {
            showError(data.message || '获取余额失败');
        }
    } catch (error) {
        showError('获取余额失败: ' + error.message);
    } finally {
        hideLoading(DOM.balanceLoading);
    }
}

/**
 * 更新余额显示
 */
function updateBalanceDisplay() {
    if (DOM.balanceAmount) {
        DOM.balanceAmount.textContent = formatAmount(PaymentState.balance);
    }
    if (DOM.balanceDisplay) {
        DOM.balanceDisplay.classList.remove('hidden');
    }
}

// ============================================================
// 套餐管理
// ============================================================

/**
 * 获取套餐列表
 */
async function fetchPackages() {
    try {
        showLoading(DOM.packageLoading);
        hideLoading(DOM.packageError);
        
        const data = await apiRequest('/api/v2/payment/packages');
        
        if (data.success) {
            PaymentState.packages = data.packages || [];
            renderPackages();
        } else {
            showError(data.message || '获取套餐列表失败');
            showLoading(DOM.packageError);
        }
    } catch (error) {
        showError('获取套餐列表失败: ' + error.message);
        showLoading(DOM.packageError);
    } finally {
        hideLoading(DOM.packageLoading);
    }
}

/**
 * 渲染套餐列表
 */
function renderPackages() {
    if (!DOM.packageList) return;
    
    DOM.packageList.innerHTML = '';
    
    if (PaymentState.packages.length === 0) {
        DOM.packageList.innerHTML = '<div class="empty-state">暂无可用套餐</div>';
        return;
    }
    
    PaymentState.packages.forEach((pkg, index) => {
        const packageCard = document.createElement('div');
        packageCard.className = 'package-card';
        packageCard.dataset.packageId = pkg.id;
        
        // 计算折扣信息
        const originalPrice = pkg.original_price || pkg.price;
        const discount = originalPrice > pkg.price ? Math.round((1 - pkg.price / originalPrice) * 100) : 0;
        
        packageCard.innerHTML = `
            <div class="package-card-header">
                <h3 class="package-name">${pkg.name}</h3>
                ${discount > 0 ? `<span class="package-discount">-${discount}%</span>` : ''}
            </div>
            <div class="package-card-body">
                <div class="package-price">
                    <span class="price-symbol">¥</span>
                    <span class="price-amount">${formatAmount(pkg.price)}</span>
                    ${originalPrice > pkg.price ? `<span class="price-original">¥${formatAmount(originalPrice)}</span>` : ''}
                </div>
                <div class="package-diagnoses">
                    <span class="diagnosis-count">${pkg.diagnosis_count}</span>
                    <span class="diagnosis-label">次诊断</span>
                </div>
                ${pkg.description ? `<p class="package-description">${pkg.description}</p>` : ''}
                ${pkg.bonus_count > 0 ? `<p class="package-bonus">赠送 ${pkg.bonus_count} 次诊断</p>` : ''}
            </div>
            <div class="package-card-footer">
                <button class="btn btn-primary select-package-btn" data-package-id="${pkg.id}">
                    选择套餐
                </button>
            </div>
        `;
        
        // 添加选择事件
        const selectBtn = packageCard.querySelector('.select-package-btn');
        selectBtn.addEventListener('click', () => selectPackage(pkg));
        
        DOM.packageList.appendChild(packageCard);
    });
    
    // 如果有默认选中的套餐
    if (PaymentState.selectedPackage) {
        highlightSelectedPackage(PaymentState.selectedPackage.id);
    }
}

/**
 * 选择套餐
 * @param {object} pkg - 套餐对象
 */
function selectPackage(pkg) {
    PaymentState.selectedPackage = pkg;
    highlightSelectedPackage(pkg.id);
    updatePayButton();
}

/**
 * 高亮选中的套餐
 * @param {number} packageId - 套餐ID
 */
function highlightSelectedPackage(packageId) {
    const packageCards = document.querySelectorAll('.package-card');
    packageCards.forEach(card => {
        card.classList.remove('selected');
        if (card.dataset.packageId == packageId) {
            card.classList.add('selected');
        }
    });
}

/**
 * 更新支付按钮状态
 */
function updatePayButton() {
    if (!DOM.payButton) return;
    
    if (PaymentState.selectedPackage) {
        DOM.payButton.disabled = false;
        DOM.payButtonText.textContent = `立即支付 ¥${formatAmount(PaymentState.selectedPackage.price)}`;
    } else {
        DOM.payButton.disabled = true;
        DOM.payButtonText.textContent = '请选择套餐';
    }
}

// ============================================================
// 支付流程
// ============================================================

/**
 * 发起支付
 */
async function initiatePayment() {
    if (!PaymentState.selectedPackage) {
        showError('请先选择套餐');
        return;
    }
    
    if (PaymentState.paymentStatus === 'processing') {
        showError('支付处理中，请稍候...');
        return;
    }
    
    try {
        PaymentState.paymentStatus = 'processing';
        updatePaymentButtonState(true);
        
        const data = await apiRequest('/api/v2/payment/create-order', 'POST', {
            package_id: PaymentState.selectedPackage.id,
            callback_url: PaymentState.callbackUrl || window.location.href
        });
        
        if (data.success) {
            PaymentState.wxPayParams = data.wx_pay_params;
            
            // 显示微信支付二维码
            showWxPayQRCode(data.wx_pay_params);
            
            // 开始轮询支付状态
            startWxPayPolling(data.order_id);
        } else {
            showError(data.message || '创建订单失败');
            PaymentState.paymentStatus = 'idle';
            updatePaymentButtonState(false);
        }
    } catch (error) {
        showError('支付失败: ' + error.message);
        PaymentState.paymentStatus = 'idle';
        updatePaymentButtonState(false);
    }
}

/**
 * 更新支付按钮状态
 * @param {boolean} isLoading - 是否正在加载
 */
function updatePaymentButtonState(isLoading) {
    if (!DOM.payButton) return;
    
    if (isLoading) {
        DOM.payButton.disabled = true;
        DOM.payButtonText.textContent = '支付处理中...';
        showLoading(DOM.payButtonLoading);
    } else {
        DOM.payButton.disabled = !PaymentState.selectedPackage;
        DOM.payButtonText.textContent = PaymentState.selectedPackage 
            ? `立即支付 ¥${formatAmount(PaymentState.selectedPackage.price)}`
            : '请选择套餐';
        hideLoading(DOM.payButtonLoading);
    }
}

/**
 * 显示微信支付二维码
 * @param {object} wxPayParams - 微信支付参数
 */
function showWxPayQRCode(wxPayParams) {
    if (!DOM.wxPayQrCodeContainer || !DOM.wxPayQrCode) return;
    
    // 显示二维码容器
    DOM.wxPayQrCodeContainer.classList.remove('hidden');
    
    // 生成二维码（使用qrcode.js库）
    if (typeof QRCode !== 'undefined') {
        DOM.wxPayQrCode.innerHTML = '';
        new QRCode(DOM.wxPayQrCode, {
            text: wxPayParams.code_url,
            width: 200,
            height: 200,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.H
        });
    } else {
        // 如果没有QRCode库，显示备用信息
        DOM.wxPayQrCode.innerHTML = `
            <div class="qr-code-fallback">
                <p>请使用微信扫描下方二维码支付</p>
                <p class="qr-code-url">${wxPayParams.code_url}</p>
            </div>
        `;
    }
    
    // 开始倒计时
    startWxPayCountdown();
    
    // 更新状态显示
    if (DOM.wxPayStatus) {
        DOM.wxPayStatus.textContent = '等待扫码支付...';
    }
}

/**
 * 开始微信支付倒计时
 */
function startWxPayCountdown() {
    PaymentState.wxPayCountdown = 300; // 5分钟
    
    if (DOM.wxPayTimer) {
        DOM.wxPayTimer.textContent = formatTime(PaymentState.wxPayCountdown);
    }
    
    if (PaymentState.wxPayCountdownTimer) {
        clearInterval(PaymentState.wxPayCountdownTimer);
    }
    
    PaymentState.wxPayCountdownTimer = setInterval(() => {
        PaymentState.wxPayCountdown--;
        
        if (DOM.wxPayTimer) {
            DOM.wxPayTimer.textContent = formatTime(PaymentState.wxPayCountdown);
        }
        
        if (PaymentState.wxPayCountdown <= 0) {
            clearInterval(PaymentState.wxPayCountdownTimer);
            PaymentState.wxPayCountdownTimer = null;
            
            // 支付超时
            if (DOM.wxPayStatus) {
                DOM.wxPayStatus.textContent = '支付超时，请重新发起支付';
            }
            
            // 停止轮询
            stopWxPayPolling();
            
            // 重置支付状态
            PaymentState.paymentStatus = 'idle';
            updatePaymentButtonState(false);
        }
    }, 1000);
}

/**
 * 开始轮询支付状态
 * @param {string} orderId - 订单ID
 */
function startWxPayPolling(orderId) {
    // 停止之前的轮询
    stopWxPayPolling();
    
    let pollCount = 0;
    const maxPolls = 60; // 最多轮询60次（5分钟）
    
    PaymentState.wxPayPollTimer = setInterval(async () => {
        pollCount++;
        
        if (pollCount > maxPolls) {
            stopWxPayPolling();
            return;
        }
        
        try {
            const data = await apiRequest(`/api/v2/payment/order-status/${orderId}`);
            
            if (data.success) {
                const status = data.order_status;
                
                if (status === 'paid' || status === 'success') {
                    // 支付成功
                    clearInterval(PaymentState.wxPayPollTimer);
                    PaymentState.wxPayPollTimer = null;
                    
                    // 停止倒计时
                    if (PaymentState.wxPayCountdownTimer) {
                        clearInterval(PaymentState.wxPayCountdownTimer);
                        PaymentState.wxPayCountdownTimer = null;
                    }
                    
                    // 更新余额
                    await fetchBalance();
                    
                    // 显示支付成功
                    showPaymentResult(true, '支付成功', '您的套餐已激活，可以开始使用诊断服务');
                    
                    // 重置支付状态
                    PaymentState.paymentStatus = 'idle';
                    updatePaymentButtonState(false);
                    
                    // 隐藏二维码
                    if (DOM.wxPayQrCodeContainer) {
                        DOM.wxPayQrCodeContainer.classList.add('hidden');
                    }
                } else if (status === 'failed' || status === 'cancelled') {
                    // 支付失败
                    clearInterval(PaymentState.wxPayPollTimer);
                    PaymentState.wxPayPollTimer = null;
                    
                    showPaymentResult(false, '支付失败', data.message || '支付未完成，请重新尝试');
                    
                    PaymentState.paymentStatus = 'idle';
                    updatePaymentButtonState(false);
                }
                // 其他状态继续轮询
            }
        } catch (error) {
            console.error('轮询支付状态失败:', error);
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
// 诊断确认弹窗
// ============================================================

/**
 * 显示诊断确认弹窗
 * @param {object} diagnosisInfo - 诊断信息
 */
function showDiagnosisConfirmation(diagnosisInfo) {
    if (!DOM.confirmDialog || !DOM.confirmDialogOverlay) return;
    
    PaymentState.currentDiagnosisId = diagnosisInfo.id;
    
    // 更新诊断信息
    if (DOM.confirmDiagnosisInfo) {
        DOM.confirmDiagnosisInfo.innerHTML = `
            <div class="diagnosis-detail">
                <p><strong>诊断类型：</strong>${diagnosisInfo.type || '综合诊断'}</p>
                <p><strong>诊断内容：</strong>${diagnosisInfo.description || '学业水平综合评估'}</p>
                <p><strong>诊断费用：</strong>¥${formatAmount(diagnosisInfo.cost || 0)}</p>
            </div>
        `;
    }
    
    // 更新套餐信息
    if (DOM.confirmPackageInfo) {
        const currentPackage = PaymentState.selectedPackage;
        if (currentPackage) {
            DOM.confirmPackageInfo.innerHTML = `
                <div class="package-detail">
                    <p><strong>当前套餐：</strong>${currentPackage.name}</p>
                    <p><strong>剩余次数：</strong>${currentPackage.remaining_diagnoses || 0} 次</p>
                </div>
            `;
        } else {
            DOM.confirmPackageInfo.innerHTML = '<p>按次计费：¥' + formatAmount(diagnosisInfo.cost || 0) + '</p>';
        }
    }
    
    // 更新余额信息
    if (DOM.confirmBalanceInfo) {
        DOM.confirmBalanceInfo.innerHTML = `
            <div class="balance-detail">
                <p><strong>当前余额：</strong>¥${formatAmount(PaymentState.balance)}</p>
                <p><strong>诊断后余额：</strong>¥${formatAmount(PaymentState.balance - (diagnosisInfo.cost || 0))}</p>
            </div>
        `;
    }
    
    // 显示弹窗
    showDialog(DOM.confirmDialog, DOM.confirmDialogOverlay);
    PaymentState.confirmDialogOpen = true;
}

/**
 * 确认诊断
 */
async function confirmDiagnosis() {
    if (!PaymentState.currentDiagnosisId) {
        showError('诊断信息缺失');
        return;
    }
    
    try {
        // 禁用确认按钮
        if (DOM.confirmButton) {
            DOM.confirmButton.disabled = true;
            DOM.confirmButton.textContent = '处理中...';
        }
        
        const data = await apiRequest('/api/v2/diagnosis/confirm', 'POST', {
            diagnosis_id: PaymentState.currentDiagnosisId,
            package_id: PaymentState.selectedPackage ? PaymentState.selectedPackage.id : null
        });
        
        if (data.success) {
            // 关闭确认弹窗
            hideDiagnosisConfirmation();
            
            // 更新余额
            await fetchBalance();
            
            // 显示成功信息
            showPaymentResult(true, '诊断已确认', '诊断服务已开始，请等待结果');
            
            // 触发诊断开始事件
            if (typeof window.onDiagnosisStarted === 'function') {
                window.onDiagnosisStarted(data.diagnosis);
            }
        } else {
            showError(data.message || '确认诊断失败');
        }
    } catch (error) {
        showError('确认诊断失败: ' + error.message);
    } finally {
        if (DOM.confirmButton) {
            DOM.confirmButton.disabled = false;
            DOM.confirmButton.textContent = '确认诊断';
        }
    }
}

/**
 * 隐藏诊断确认弹窗
 */
function hideDiagnosisConfirmation() {
    if (DOM.confirmDialog && DOM.confirmDialogOverlay) {
        hideDialog(DOM.confirmDialog, DOM.confirmDialogOverlay);
    }
    PaymentState.confirmDialogOpen = false;
    PaymentState.currentDiagnosisId = null;
}

// ============================================================
// 支付结果弹窗
// ============================================================

/**
 * 显示支付结果弹窗
 * @param {boolean} success - 是否成功
 * @param {string} title - 标题
 * @param {string} message - 消息
 */
function showPaymentResult(success, title, message) {
    if (!DOM.paymentResultDialog || !DOM.paymentResultOverlay) return;
    
    // 设置图标
    if (DOM.paymentResultIcon) {
        DOM.paymentResultIcon.className = success ? 'icon-success' : 'icon-failed';
        DOM.paymentResultIcon.textContent = success ? '✓' : '✗';
    }
    
    // 设置标题
    if (DOM.paymentResultTitle) {
        DOM.paymentResultTitle.textContent = title;
        DOM.paymentResultTitle.className = success ? 'text-success' : 'text-failed';
    }
    
    // 设置消息
    if (DOM.paymentResultMessage) {
        DOM.paymentResultMessage.textContent = message;
    }
    
    // 显示弹窗
    showDialog(DOM.paymentResultDialog, DOM.paymentResultOverlay);
}

/**
 * 隐藏支付结果弹窗
 */
function hidePaymentResult() {
    if (DOM.paymentResultDialog && DOM.paymentResultOverlay) {
        hideDialog(DOM.paymentResultDialog, DOM.paymentResultOverlay);
    }
}

// ============================================================
// 事件绑定
// ============================================================

/**
 * 绑定事件
 */
function bindEvents() {
    // 支付按钮点击事件
    if (DOM.payButton) {
        DOM.payButton.addEventListener('click', initiatePayment);
    }
    
    // 确认诊断按钮点击事件
    if (DOM.confirmButton) {
        DOM.confirmButton.addEventListener('click', confirmDiagnosis);
    }
    
    // 取消诊断按钮点击事件
    if (DOM.cancelButton) {
        DOM.cancelButton.addEventListener('click', hideDiagnosisConfirmation);
    }
    
    // 关闭诊断确认弹窗（点击遮罩层）
    if (DOM.confirmDialogOverlay) {
        DOM.confirmDialogOverlay.addEventListener('click', hideDiagnosisConfirmation);
    }
    
    // 支付结果弹窗关闭按钮
    if (DOM.paymentResultButton) {
        DOM.paymentResultButton.addEventListener('click', hidePaymentResult);
    }
    
    // 关闭支付结果弹窗（点击遮罩层）
    if (DOM.paymentResultOverlay) {
        DOM.paymentResultOverlay.addEventListener('click', hidePaymentResult);
    }
    
    // 错误提示关闭按钮
    if (DOM.errorToastClose) {
        DOM.errorToastClose.addEventListener('click', hideError);
    }
    
    // 键盘事件
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            if (PaymentState.confirmDialogOpen) {
                hideDiagnosisConfirmation();
            }
            hidePaymentResult();
            hideError();
        }
    });
}

// ============================================================
// 初始化
// ============================================================

/**
 * 初始化支付模块
 */
async function initPaymentModule() {
    try {
        // 绑定事件
        bindEvents();
        
        // 获取余额
        await fetchBalance();
        
        // 获取套餐列表
        await fetchPackages();
        
        // 更新支付按钮状态
        updatePayButton();
        
        console.log('支付模块初始化完成');
    } catch (error) {
        console.error('支付模块初始化失败:', error);
        showError('支付模块初始化失败，请刷新页面重试');
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    initPaymentModule();
});

// 导出模块（用于其他JS文件调用）
window.PaymentModule = {
    // 状态
    state: PaymentState,
    
    // 余额相关
    fetchBalance: fetchBalance,
    updateBalanceDisplay: updateBalanceDisplay,
    
    // 套餐相关
    fetchPackages: fetchPackages,
    selectPackage: selectPackage,
    
    // 支付相关
    initiatePayment: initiatePayment,
    
    // 诊断确认
    showDiagnosisConfirmation: showDiagnosisConfirmation,
    confirmDiagnosis: confirmDiagnosis,
    hideDiagnosisConfirmation: hideDiagnosisConfirmation,
    
    // 支付结果
    showPaymentResult: showPaymentResult,
    hidePaymentResult: hidePaymentResult,
    
    // 工具
    formatAmount: formatAmount,
    showError: showError,
    hideError: hideError
};