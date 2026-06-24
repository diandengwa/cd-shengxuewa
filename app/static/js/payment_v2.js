/**
 * K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
 * 付费模式重构 — 按次诊断计费方案
 * 前端支付交互JS：套餐选择、微信支付唤起、余额显示、诊断确认弹窗
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
    callbackUrl: null
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
            DOM.errorToast.classList.remove('show');
            DOM.errorToast.classList.add('hidden');
        }, 5000);
    } else {
        console.error('Error:', message);
        alert(message);
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
 * 显示支付按钮加载状态
 */
function showPayButtonLoading() {
    if (DOM.payButton) {
        DOM.payButton.disabled = true;
        DOM.payButton.classList.add('loading');
    }
    if (DOM.payButtonText) {
        DOM.payButtonText.textContent = '处理中...';
    }
    if (DOM.payButtonLoading) {
        showLoading(DOM.payButtonLoading);
    }
}

/**
 * 隐藏支付按钮加载状态
 */
function hidePayButtonLoading() {
    if (DOM.payButton) {
        DOM.payButton.disabled = false;
        DOM.payButton.classList.remove('loading');
    }
    if (DOM.payButtonText) {
        DOM.payButtonText.textContent = '立即支付';
    }
    if (DOM.payButtonLoading) {
        hideLoading(DOM.payButtonLoading);
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
        const response = await fetch('/api/v2/payment/balance', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });
        
        if (!response.ok) {
            throw new Error(`获取余额失败: ${response.status} ${response.statusText}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '获取余额失败');
        }
        
        return data.data.balance;
    } catch (error) {
        console.error('获取余额失败:', error);
        throw error;
    }
}

/**
 * 获取套餐列表
 * @returns {Promise<Array>} 套餐列表
 */
async function fetchPackages() {
    try {
        const response = await fetch('/api/v2/payment/packages', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });
        
        if (!response.ok) {
            throw new Error(`获取套餐失败: ${response.status} ${response.statusText}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '获取套餐失败');
        }
        
        return data.data.packages;
    } catch (error) {
        console.error('获取套餐失败:', error);
        throw error;
    }
}

/**
 * 创建微信支付订单
 * @param {string} packageId - 套餐ID
 * @returns {Promise<Object>} 支付参数
 */
async function createWxPayOrder(packageId) {
    try {
        const response = await fetch('/api/v2/payment/wxpay/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                package_id: packageId
            })
        });
        
        if (!response.ok) {
            throw new Error(`创建支付订单失败: ${response.status} ${response.statusText}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '创建支付订单失败');
        }
        
        return data.data;
    } catch (error) {
        console.error('创建支付订单失败:', error);
        throw error;
    }
}

/**
 * 查询支付状态
 * @param {string} orderId - 订单ID
 * @returns {Promise<Object>} 支付状态
 */
async function queryPaymentStatus(orderId) {
    try {
        const response = await fetch(`/api/v2/payment/wxpay/status/${orderId}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });
        
        if (!response.ok) {
            throw new Error(`查询支付状态失败: ${response.status} ${response.statusText}`);
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
 * 使用余额支付诊断
 * @param {string} diagnosisId - 诊断ID
 * @returns {Promise<Object>} 支付结果
 */
async function payWithBalance(diagnosisId) {
    try {
        const response = await fetch('/api/v2/payment/balance/pay', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                diagnosis_id: diagnosisId
            })
        });
        
        if (!response.ok) {
            throw new Error(`余额支付失败: ${response.status} ${response.statusText}`);
        }
        
        const data = await response.json();
        if (data.code !== 0) {
            throw new Error(data.message || '余额支付失败');
        }
        
        return data.data;
    } catch (error) {
        console.error('余额支付失败:', error);
        throw error;
    }
}

// ============================================================
// 余额显示模块
// ============================================================

/**
 * 更新余额显示
 * @param {number} balance - 余额（分）
 */
function updateBalanceDisplay(balance) {
    PaymentState.balance = balance;
    
    if (DOM.balanceAmount) {
        DOM.balanceAmount.textContent = `¥${formatAmount(balance)}`;
    }
    
    if (DOM.balanceLoading) {
        hideLoading(DOM.balanceLoading);
    }
    
    if (DOM.balanceDisplay) {
        DOM.balanceDisplay.classList.remove('hidden');
    }
}

/**
 * 加载余额
 */
async function loadBalance() {
    try {
        if (DOM.balanceLoading) {
            showLoading(DOM.balanceLoading);
        }
        
        const balance = await fetchBalance();
        updateBalanceDisplay(balance);
    } catch (error) {
        console.error('加载余额失败:', error);
        if (DOM.balanceLoading) {
            hideLoading(DOM.balanceLoading);
        }
        // 余额加载失败不阻塞页面，显示默认值
        updateBalanceDisplay(0);
    }
}

// ============================================================
// 套餐选择模块
// ============================================================

/**
 * 渲染套餐卡片
 * @param {Array} packages - 套餐列表
 */
function renderPackages(packages) {
    PaymentState.packages = packages;
    
    if (!DOM.packageList) return;
    
    // 清空现有内容
    DOM.packageList.innerHTML = '';
    
    if (!packages || packages.length === 0) {
        DOM.packageList.innerHTML = '<div class="empty-state">暂无可用套餐</div>';
        return;
    }
    
    // 渲染每个套餐
    packages.forEach((pkg, index) => {
        const card = document.createElement('div');
        card.className = 'package-card';
        card.dataset.packageId = pkg.id;
        card.dataset.index = index;
        
        // 计算优惠信息
        const originalPrice = pkg.original_price || pkg.price;
        const discount = originalPrice > pkg.price ? Math.round((1 - pkg.price / originalPrice) * 100) : 0;
        
        card.innerHTML = `
            <div class="package-card-header">
                <h3 class="package-name">${pkg.name}</h3>
                ${discount > 0 ? `<span class="package-discount-badge">-${discount}%</span>` : ''}
            </div>
            <div class="package-card-body">
                <div class="package-diagnosis-count">
                    <span class="count-number">${pkg.diagnosis_count}</span>
                    <span class="count-label">次诊断</span>
                </div>
                <div class="package-price">
                    <span class="price-current">¥${formatAmount(pkg.price)}</span>
                    ${originalPrice > pkg.price ? `<span class="price-original">¥${formatAmount(originalPrice)}</span>` : ''}
                </div>
                ${pkg.description ? `<p class="package-description">${pkg.description}</p>` : ''}
                ${pkg.features && pkg.features.length > 0 ? `
                    <ul class="package-features">
                        ${pkg.features.map(f => `<li>${f}</li>`).join('')}
                    </ul>
                ` : ''}
            </div>
            <div class="package-card-footer">
                <button class="package-select-btn" data-package-id="${pkg.id}">
                    选择套餐
                </button>
            </div>
        `;
        
        // 添加选择事件
        const selectBtn = card.querySelector('.package-select-btn');
        selectBtn.addEventListener('click', () => selectPackage(pkg.id));
        
        DOM.packageList.appendChild(card);
    });
    
    // 默认选中第一个套餐
    if (packages.length > 0) {
        selectPackage(packages[0].id);
    }
}

/**
 * 选择套餐
 * @param {string} packageId - 套餐ID
 */
function selectPackage(packageId) {
    const pkg = PaymentState.packages.find(p => p.id === packageId);
    if (!pkg) return;
    
    PaymentState.selectedPackage = pkg;
    
    // 更新UI选中状态
    const cards = DOM.packageList.querySelectorAll('.package-card');
    cards.forEach(card => {
        card.classList.remove('selected');
        if (card.dataset.packageId === packageId) {
            card.classList.add('selected');
        }
    });
    
    // 更新支付按钮状态
    updatePayButton();
}

/**
 * 加载套餐列表
 */
async function loadPackages() {
    try {
        if (DOM.packageLoading) {
            showLoading(DOM.packageLoading);
        }
        if (DOM.packageError) {
            DOM.packageError.classList.add('hidden');
        }
        
        const packages = await fetchPackages();
        renderPackages(packages);
        
        if (DOM.packageLoading) {
            hideLoading(DOM.packageLoading);
        }
    } catch (error) {
        console.error('加载套餐失败:', error);
        if (DOM.packageLoading) {
            hideLoading(DOM.packageLoading);
        }
        if (DOM.packageError) {
            DOM.packageError.classList.remove('hidden');
            DOM.packageError.textContent = '加载套餐失败，请稍后重试';
        }
        showError('加载套餐失败，请刷新页面重试');
    }
}

// ============================================================
// 支付按钮模块
// ============================================================

/**
 * 更新支付按钮状态
 */
function updatePayButton() {
    if (!DOM.payButton) return;
    
    const pkg = PaymentState.selectedPackage;
    if (!pkg) {
        DOM.payButton.disabled = true;
        DOM.payButtonText.textContent = '请选择套餐';
        return;
    }
    
    DOM.payButton.disabled = false;
    DOM.payButtonText.textContent = `立即支付 ¥${formatAmount(pkg.price)}`;
}

/**
 * 处理支付按钮点击
 */
async function handlePayButtonClick() {
    if (PaymentState.paymentStatus === 'processing') return;
    
    const pkg = PaymentState.selectedPackage;
    if (!pkg) {
        showError('请先选择套餐');
        return;
    }
    
    // 检查用户是否已登录
    if (!PaymentState.user) {
        showError('请先登录');
        window.location.href = '/auth/login?redirect=' + encodeURIComponent(window.location.pathname);
        return;
    }
    
    PaymentState.paymentStatus = 'processing';
    showPayButtonLoading();
    
    try {
        // 创建微信支付订单
        const payData = await createWxPayOrder(pkg.id);
        PaymentState.wxPayParams = payData;
        
        // 显示微信支付二维码
        showWxPayQrCode(payData);
        
        // 开始轮询支付状态
        startPaymentPolling(payData.order_id);
    } catch (error) {
        console.error('支付失败:', error);
        PaymentState.paymentStatus = 'failed';
        hidePayButtonLoading();
        showError('支付失败: ' + error.message);
    }
}

// ============================================================
// 微信支付二维码模块
// ============================================================

/**
 * 显示微信支付二维码
 * @param {Object} payData - 支付数据
 */
function showWxPayQrCode(payData) {
    if (!DOM.wxPayQrCodeContainer) return;
    
    // 显示二维码容器
    DOM.wxPayQrCodeContainer.classList.remove('hidden');
    
    // 生成二维码（使用qrcode.js库）
    if (DOM.wxPayQrCode && payData.qr_code_url) {
        // 清空二维码容器
        DOM.wxPayQrCode.innerHTML = '';
        
        // 使用QRCode库生成二维码
        if (typeof QRCode !== 'undefined') {
            new QRCode(DOM.wxPayQrCode, {
                text: payData.qr_code_url,
                width: 200,
                height: 200,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.H
            });
        } else {
            // 如果QRCode库未加载，显示图片二维码
            const img = document.createElement('img');
            img.src = payData.qr_code_url;
            img.alt = '微信支付二维码';
            img.className = 'wx-pay-qrcode-img';
            DOM.wxPayQrCode.appendChild(img);
        }
    }
    
    // 更新支付状态显示
    if (DOM.wxPayStatus) {
        DOM.wxPayStatus.textContent = '请使用微信扫描二维码支付';
    }
    
    // 开始倒计时
    startWxPayTimer(payData.expire_time || 300);
}

/**
 * 微信支付倒计时
 * @param {number} expireSeconds - 过期时间（秒）
 */
function startWxPayTimer(expireSeconds) {
    if (!DOM.wxPayTimer) return;
    
    let remaining = expireSeconds;
    
    const updateTimer = () => {
        if (remaining <= 0) {
            DOM.wxPayTimer.textContent = '二维码已过期';
            DOM.wxPayTimer.classList.add('expired');
            
            // 隐藏二维码
            if (DOM.wxPayQrCodeContainer) {
                setTimeout(() => {
                    DOM.wxPayQrCodeContainer.classList.add('hidden');
                }, 3000);
            }
            
            PaymentState.paymentStatus = 'failed';
            hidePayButtonLoading();
            return;
        }
        
        DOM.wxPayTimer.textContent = `剩余 ${formatTime(remaining)}`;
        remaining--;
        
        // 每秒更新
        setTimeout(updateTimer, 1000);
    };
    
    updateTimer();
}

/**
 * 隐藏微信支付二维码
 */
function hideWxPayQrCode() {
    if (DOM.wxPayQrCodeContainer) {
        DOM.wxPayQrCodeContainer.classList.add('hidden');
    }
    if (DOM.wxPayTimer) {
        DOM.wxPayTimer.textContent = '';
        DOM.wxPayTimer.classList.remove('expired');
    }
}

// ============================================================
// 支付状态轮询模块
// ============================================================

let paymentPollingInterval = null;

/**
 * 开始轮询支付状态
 * @param {string} orderId - 订单ID
 */
function startPaymentPolling(orderId) {
    // 清除之前的轮询
    stopPaymentPolling();
    
    let attempts = 0;
    const maxAttempts = 60; // 最多轮询60次（5分钟）
    
    paymentPollingInterval = setInterval(async () => {
        attempts++;
        
        try {
            const statusData = await queryPaymentStatus(orderId);
            
            if (statusData.status === 'success') {
                // 支付成功
                stopPaymentPolling();
                PaymentState.paymentStatus = 'success';
                hidePayButtonLoading();
                hideWxPayQrCode();
                
                // 更新余额
                if (statusData.new_balance !== undefined) {
                    updateBalanceDisplay(statusData.new_balance);
                } else {
                    // 重新加载余额
                    loadBalance();
                }
                
                // 显示支付成功弹窗
                showPaymentResult(true, '支付成功', '您的套餐已激活，可以开始使用诊断服务了');
                
                // 触发支付成功回调
                if (PaymentState.callbackUrl) {
                    window.location.href = PaymentState.callbackUrl;
                }
                
            } else if (statusData.status === 'failed') {
                // 支付失败
                stopPaymentPolling();
                PaymentState.paymentStatus = 'failed';
                hidePayButtonLoading();
                hideWxPayQrCode();
                
                showPaymentResult(false, '支付失败', statusData.message || '支付过程中出现错误，请重试');
                
            } else if (statusData.status === 'closed') {
                // 订单已关闭
                stopPaymentPolling();
                PaymentState.paymentStatus = 'failed';
                hidePayButtonLoading();
                hideWxPayQrCode();
                
                showPaymentResult(false, '订单已关闭', '支付二维码已过期，请重新下单');
            }
            
            // 超过最大轮询次数
            if (attempts >= maxAttempts) {
                stopPaymentPolling();
                PaymentState.paymentStatus = 'failed';
                hidePayButtonLoading();
                hideWxPayQrCode();
                
                showPaymentResult(false, '支付超时', '支付超时，请重新下单');
            }
            
        } catch (error) {
            console.error('查询支付状态失败:', error);
            // 继续轮询，不中断
        }
    }, 5000); // 每5秒轮询一次
}

/**
 * 停止轮询支付状态
 */
function stopPaymentPolling() {
    if (paymentPollingInterval) {
        clearInterval(paymentPollingInterval);
        paymentPollingInterval = null;
    }
}

// ============================================================
// 诊断确认弹窗模块
// ============================================================

/**
 * 显示诊断确认弹窗
 * @param {Object} diagnosisInfo - 诊断信息
 */
function showConfirmDialog(diagnosisInfo) {
    if (!DOM.confirmDialog || !DOM.confirmDialogOverlay) return;
    
    PaymentState.confirmDialogOpen = true;
    PaymentState.currentDiagnosisId = diagnosisInfo.id;
    
    // 更新诊断信息
    if (DOM.confirmDiagnosisInfo) {
        DOM.confirmDiagnosisInfo.innerHTML = `
            <div class="diagnosis-info-item">
                <span class="info-label">诊断类型：</span>
                <span class="info-value">${diagnosisInfo.type || '升学诊断'}</span>
            </div>
            <div class="diagnosis-info-item">
                <span class="info-label">诊断费用：</span>
                <span class="info-value">¥${formatAmount(diagnosisInfo.price || 0)}</span>
            </div>
            ${diagnosisInfo.description ? `
                <div class="diagnosis-info-item">
                    <span class="info-label">诊断说明：</span>
                    <span class="info-value">${diagnosisInfo.description}</span>
                </div>
            ` : ''}
        `;
    }
    
    // 更新套餐信息
    if (DOM.confirmPackageInfo) {
        const pkg = PaymentState.selectedPackage;
        if (pkg) {
            DOM.confirmPackageInfo.innerHTML = `
                <div class="package-info-item">
                    <span class="info-label">当前套餐：</span>
                    <span class="info-value">${pkg.name}</span>
                </div>
                <div class="package-info-item">
                    <span class="info-label">剩余次数：</span>
                    <span class="info-value">${pkg.remaining_count || 0} 次</span>
                </div>
            `;
        } else {
            DOM.confirmPackageInfo.innerHTML = '<div class="no-package">未选择套餐，将按单次诊断计费</div>';
        }
    }
    
    // 更新余额信息
    if (DOM.confirmBalanceInfo) {
        DOM.confirmBalanceInfo.innerHTML = `
            <div class="balance-info-item">
                <span class="info-label">账户余额：</span>
                <span class="info-value">¥${formatAmount(PaymentState.balance)}</span>
            </div>
            <div class="balance-info-item">
                <span class="info-label">诊断后余额：</span>
                <span class="info-value">¥${formatAmount(PaymentState.balance - (diagnosisInfo.price || 0))}</span>
            </div>
        `;
    }
    
    // 显示弹窗
    DOM.confirmDialog.classList.remove('hidden');
    DOM.confirmDialogOverlay.classList.remove('hidden');
    
    // 添加动画
    setTimeout(() => {
        DOM.confirmDialog.classList.add('show');
        DOM.confirmDialogOverlay.classList.add('show');
    }, 10);
}

/**
 * 隐藏诊断确认弹窗
 */
function hideConfirmDialog() {
    if (!DOM.confirmDialog || !DOM.confirmDialogOverlay) return;
    
    PaymentState.confirmDialogOpen = false;
    PaymentState.currentDiagnosisId = null;
    
    DOM.confirmDialog.classList.remove('show');
    DOM.confirmDialogOverlay.classList.remove('show');
    
    setTimeout(() => {
        DOM.confirmDialog.classList.add('hidden');
        DOM.confirmDialogOverlay.classList.add('hidden');
    }, 300);
}

/**
 * 处理确认按钮点击
 */
async function handleConfirmButtonClick() {
    const diagnosisId = PaymentState.currentDiagnosisId;
    if (!diagnosisId) {
        showError('诊断信息缺失');
        return;
    }
    
    // 检查余额是否足够
    const pkg = PaymentState.selectedPackage;
    const diagnosisPrice = 0; // 从诊断信息获取实际价格
    
    if (PaymentState.balance < diagnosisPrice) {
        showError('余额不足，请先充值');
        hideConfirmDialog();
        return;
    }
    
    showPayButtonLoading();
    
    try {
        // 使用余额支付
        const result = await payWithBalance(diagnosisId);
        
        hideConfirmDialog();
        hidePayButtonLoading();
        
        // 更新余额
        if (result.new_balance !== undefined) {
            updateBalanceDisplay(result.new_balance);
        } else {
            loadBalance();
        }
        
        // 显示支付成功
        showPaymentResult(true, '诊断确认成功', '诊断已开始，请等待结果');
        
        // 跳转到诊断结果页面
        if (result.redirect_url) {
            setTimeout(() => {
                window.location.href = result.redirect_url;
            }, 1500);
        }
        
    } catch (error) {
        console.error('诊断确认失败:', error);
        hidePayButtonLoading();
        showError('诊断确认失败: ' + error.message);
    }
}

// ============================================================
// 支付结果弹窗模块
// ============================================================

/**
 * 显示支付结果弹窗
 * @param {boolean} success - 是否成功
 * @param {string} title - 标题
 * @param {string} message - 消息
 */
function showPaymentResult(success, title, message) {
    if (!DOM.paymentResultDialog || !DOM.paymentResultOverlay) return;
    
    // 更新图标
    if (DOM.paymentResultIcon) {
        DOM.paymentResultIcon.className = `payment-result-icon ${success ? 'success' : 'failed'}`;
        DOM.paymentResultIcon.textContent = success ? '✓' : '✗';
    }
    
    // 更新标题
    if (DOM.paymentResultTitle) {
        DOM.paymentResultTitle.textContent = title;
    }
    
    // 更新消息
    if (DOM.paymentResultMessage) {
        DOM.paymentResultMessage.textContent = message;
    }
    
    // 显示弹窗
    DOM.paymentResultDialog.classList.remove('hidden');
    DOM.paymentResultOverlay.classList.remove('hidden');
    
    // 添加动画
    setTimeout(() => {
        DOM.paymentResultDialog.classList.add('show');
        DOM.paymentResultOverlay.classList.add('show');
    }, 10);
}

/**
 * 隐藏支付结果弹窗
 */
function hidePaymentResult() {
    if (!DOM.paymentResultDialog || !DOM.paymentResultOverlay) return;
    
    DOM.paymentResultDialog.classList.remove('show');
    DOM.paymentResultOverlay.classList.remove('show');
    
    setTimeout(() => {
        DOM.paymentResultDialog.classList.add('hidden');
        DOM.paymentResultOverlay.classList.add('hidden');
    }, 300);
}

// ============================================================
// 事件绑定
// ============================================================

/**
 * 绑定事件
 */
function bindEvents() {
    // 支付按钮
    if (DOM.payButton) {
        DOM.payButton.addEventListener('click', handlePayButtonClick);
    }
    
    // 确认弹窗按钮
    if (DOM.confirmButton) {
        DOM.confirmButton.addEventListener('click', handleConfirmButtonClick);
    }
    
    if (DOM.cancelButton) {
        DOM.cancelButton.addEventListener('click', hideConfirmDialog);
    }
    
    // 点击遮罩关闭弹窗
    if (DOM.confirmDialogOverlay) {
        DOM.confirmDialogOverlay.addEventListener('click', hideConfirmDialog);
    }
    
    // 支付结果弹窗按钮
    if (DOM.paymentResultButton) {
        DOM.paymentResultButton.addEventListener('click', hidePaymentResult);
    }
    
    if (DOM.paymentResultOverlay) {
        DOM.paymentResultOverlay.addEventListener('click', hidePaymentResult);
    }
    
    // 错误提示关闭按钮
    if (DOM.errorToastClose) {
        DOM.errorToastClose.addEventListener('click', hideError);
    }
    
    // 页面卸载时停止轮询
    window.addEventListener('beforeunload', () => {
        stopPaymentPolling();
    });
}

// ============================================================
// 初始化
// ============================================================

/**
 * 初始化支付模块
 */
async function initPayment() {
    console.log('初始化支付模块 v2.0');
    
    // 绑定事件
    bindEvents();
    
    // 加载用户信息
    try {
        const userResponse = await fetch('/api/v2/auth/user', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });
        
        if (userResponse.ok) {
            const userData = await userResponse.json();
            if (userData.code === 0) {
                PaymentState.user = userData.data;
            }
        }
    } catch (error) {
        console.error('获取用户信息失败:', error);
    }
    
    // 并行加载余额和套餐
    await Promise.all([
        loadBalance(),
        loadPackages()
    ]);
    
    console.log('支付模块初始化完成');
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initPayment);

// 导出模块（用于其他JS文件调用）
window.PaymentV2 = {
    // 状态
    state: PaymentState,
    
    // 方法
    showConfirmDialog,
    hideConfirmDialog,
    showPaymentResult,
    hidePaymentResult,
    loadBalance,
    loadPackages,
    selectPackage,
    
    // 事件
    onPaymentSuccess: null,
    onPaymentFailed: null
};