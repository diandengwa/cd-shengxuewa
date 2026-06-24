/**
 * K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
 * 前端诊断次数管理JS：余额显示、购买弹窗、消耗确认
 * 
 * 付费模式重构 — 按次诊断计费方案
 * Issue #26 Task A
 */

// ============================================================
// 全局状态
// ============================================================
const CreditsState = {
    balance: 0,           // 当前剩余诊断次数
    isFetching: false,    // 是否正在请求
    isPurchasing: false,  // 是否正在购买
    isConsuming: false,   // 是否正在消耗
    lastFetchTime: null,  // 上次获取余额时间
    fetchInterval: 30000, // 自动刷新间隔（毫秒）
    autoRefreshTimer: null
};

// ============================================================
// DOM 缓存
// ============================================================
const DOM = {
    balanceDisplay: document.getElementById('credits-balance'),
    balanceBadge: document.getElementById('credits-badge'),
    buyBtn: document.getElementById('credits-buy-btn'),
    buyModal: document.getElementById('credits-buy-modal'),
    buyModalClose: document.getElementById('credits-buy-modal-close'),
    buyForm: document.getElementById('credits-buy-form'),
    buyPackageSelect: document.getElementById('credits-package-select'),
    buyConfirmBtn: document.getElementById('credits-buy-confirm-btn'),
    buyCancelBtn: document.getElementById('credits-buy-cancel-btn'),
    consumeConfirmModal: document.getElementById('credits-consume-modal'),
    consumeConfirmBtn: document.getElementById('credits-consume-confirm-btn'),
    consumeCancelBtn: document.getElementById('credits-consume-cancel-btn'),
    consumeReason: document.getElementById('credits-consume-reason'),
    toastContainer: document.getElementById('toast-container')
};

// ============================================================
// 工具函数
// ============================================================

/**
 * 显示 Toast 消息
 * @param {string} message - 消息内容
 * @param {'success'|'error'|'warning'|'info'} type - 消息类型
 * @param {number} duration - 显示时长（毫秒）
 */
function showToast(message, type = 'info', duration = 3000) {
    if (!DOM.toastContainer) {
        // 如果容器不存在，动态创建
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;';
        document.body.appendChild(container);
        DOM.toastContainer = container;
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.style.cssText = `
        padding: 12px 20px;
        border-radius: 8px;
        color: #fff;
        font-size: 14px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideIn 0.3s ease;
        min-width: 200px;
        max-width: 400px;
        word-break: break-word;
    `;

    // 根据类型设置背景色
    const colors = {
        success: '#10b981',
        error: '#ef4444',
        warning: '#f59e0b',
        info: '#3b82f6'
    };
    toast.style.backgroundColor = colors[type] || colors.info;
    toast.textContent = message;

    DOM.toastContainer.appendChild(toast);

    // 自动移除
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }, duration);
}

/**
 * 格式化数字显示
 * @param {number} num
 * @returns {string}
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return num.toLocaleString('zh-CN');
}

/**
 * 获取 CSRF Token（如果有）
 * @returns {string|null}
 */
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : null;
}

// ============================================================
// API 请求封装
// ============================================================

/**
 * 通用 API 请求
 * @param {string} url - 请求地址
 * @param {object} options - 请求选项
 * @returns {Promise<object>}
 */
async function apiRequest(url, options = {}) {
    const defaultHeaders = {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
    };

    const csrfToken = getCsrfToken();
    if (csrfToken) {
        defaultHeaders['X-CSRF-Token'] = csrfToken;
    }

    const config = {
        headers: { ...defaultHeaders, ...options.headers },
        ...options
    };

    // 如果是 FormData，不要设置 Content-Type
    if (options.body instanceof FormData) {
        delete config.headers['Content-Type'];
    }

    try {
        const response = await fetch(url, config);
        
        // 处理 401 未授权
        if (response.status === 401) {
            showToast('登录已过期，请重新登录', 'error');
            // 延迟跳转到登录页
            setTimeout(() => {
                window.location.href = '/auth/login?redirect=' + encodeURIComponent(window.location.pathname);
            }, 1500);
            throw new Error('Unauthorized');
        }

        // 处理 403 无权限
        if (response.status === 403) {
            showToast('没有权限执行此操作', 'error');
            throw new Error('Forbidden');
        }

        // 处理 429 限流
        if (response.status === 429) {
            showToast('操作过于频繁，请稍后再试', 'warning');
            throw new Error('Rate Limited');
        }

        const data = await response.json();

        if (!response.ok) {
            const errorMsg = data.detail || data.message || `请求失败 (${response.status})`;
            showToast(errorMsg, 'error');
            throw new Error(errorMsg);
        }

        return data;
    } catch (error) {
        if (error.name === 'TypeError' && error.message.includes('fetch')) {
            showToast('网络连接失败，请检查网络', 'error');
            throw error;
        }
        throw error;
    }
}

// ============================================================
// 核心功能：余额管理
// ============================================================

/**
 * 获取当前用户诊断次数余额
 * @param {boolean} showLoading - 是否显示加载状态
 * @returns {Promise<number>} 剩余次数
 */
async function fetchCreditsBalance(showLoading = true) {
    if (CreditsState.isFetching) return CreditsState.balance;

    CreditsState.isFetching = true;
    
    try {
        const data = await apiRequest('/api/credits/balance');
        
        if (data && typeof data.balance === 'number') {
            CreditsState.balance = data.balance;
            CreditsState.lastFetchTime = Date.now();
            updateBalanceDisplay();
            return data.balance;
        } else {
            console.error('获取余额返回格式异常:', data);
            showToast('获取诊断次数失败', 'error');
            return CreditsState.balance;
        }
    } catch (error) {
        console.error('获取余额失败:', error);
        // 如果是网络错误，不显示 toast，避免频繁提示
        if (error.message !== '网络连接失败，请检查网络') {
            showToast('获取诊断次数失败，请稍后重试', 'error');
        }
        return CreditsState.balance;
    } finally {
        CreditsState.isFetching = false;
    }
}

/**
 * 更新页面上的余额显示
 */
function updateBalanceDisplay() {
    const balanceText = formatNumber(CreditsState.balance);
    
    if (DOM.balanceDisplay) {
        DOM.balanceDisplay.textContent = balanceText;
        // 根据余额数量添加样式类
        DOM.balanceDisplay.classList.remove('credits-low', 'credits-empty', 'credits-sufficient');
        if (CreditsState.balance <= 0) {
            DOM.balanceDisplay.classList.add('credits-empty');
        } else if (CreditsState.balance <= 3) {
            DOM.balanceDisplay.classList.add('credits-low');
        } else {
            DOM.balanceDisplay.classList.add('credits-sufficient');
        }
    }
    
    if (DOM.balanceBadge) {
        DOM.balanceBadge.textContent = balanceText;
        DOM.balanceBadge.classList.remove('credits-low', 'credits-empty', 'credits-sufficient');
        if (CreditsState.balance <= 0) {
            DOM.balanceBadge.classList.add('credits-empty');
        } else if (CreditsState.balance <= 3) {
            DOM.balanceBadge.classList.add('credits-low');
        } else {
            DOM.balanceBadge.classList.add('credits-sufficient');
        }
    }
}

/**
 * 启动自动刷新余额
 */
function startAutoRefresh() {
    stopAutoRefresh();
    CreditsState.autoRefreshTimer = setInterval(() => {
        fetchCreditsBalance(false);
    }, CreditsState.fetchInterval);
}

/**
 * 停止自动刷新余额
 */
function stopAutoRefresh() {
    if (CreditsState.autoRefreshTimer) {
        clearInterval(CreditsState.autoRefreshTimer);
        CreditsState.autoRefreshTimer = null;
    }
}

// ============================================================
// 核心功能：购买诊断次数
// ============================================================

/**
 * 打开购买弹窗
 */
function openBuyModal() {
    if (!DOM.buyModal) {
        showToast('购买功能暂不可用', 'error');
        return;
    }
    
    // 加载套餐列表
    loadPackages();
    
    DOM.buyModal.classList.add('active');
    DOM.buyModal.style.display = 'block';
    document.body.style.overflow = 'hidden'; // 防止背景滚动
}

/**
 * 关闭购买弹窗
 */
function closeBuyModal() {
    if (!DOM.buyModal) return;
    
    DOM.buyModal.classList.remove('active');
    DOM.buyModal.style.display = 'none';
    document.body.style.overflow = '';
}

/**
 * 加载可购买的套餐列表
 */
async function loadPackages() {
    if (!DOM.buyPackageSelect) return;
    
    try {
        const data = await apiRequest('/api/credits/packages');
        
        // 清空现有选项
        DOM.buyPackageSelect.innerHTML = '<option value="">请选择套餐</option>';
        
        if (data && Array.isArray(data.packages)) {
            data.packages.forEach(pkg => {
                const option = document.createElement('option');
                option.value = pkg.id;
                option.textContent = `${pkg.name} — ${pkg.credits}次诊断 / ¥${pkg.price}`;
                if (pkg.recommended) {
                    option.textContent += ' ★推荐';
                    option.dataset.recommended = 'true';
                }
                DOM.buyPackageSelect.appendChild(option);
            });
        } else {
            // 如果没有套餐数据，显示默认选项
            DOM.buyPackageSelect.innerHTML = `
                <option value="">暂无可用套餐</option>
            `;
        }
    } catch (error) {
        console.error('加载套餐失败:', error);
        DOM.buyPackageSelect.innerHTML = '<option value="">加载失败，请重试</option>';
    }
}

/**
 * 提交购买请求
 * @param {string} packageId - 套餐ID
 * @returns {Promise<boolean>} 是否成功
 */
async function submitPurchase(packageId) {
    if (CreditsState.isPurchasing) return false;
    
    if (!packageId) {
        showToast('请选择要购买的套餐', 'warning');
        return false;
    }
    
    CreditsState.isPurchasing = true;
    if (DOM.buyConfirmBtn) {
        DOM.buyConfirmBtn.disabled = true;
        DOM.buyConfirmBtn.textContent = '处理中...';
    }
    
    try {
        const data = await apiRequest('/api/credits/purchase', {
            method: 'POST',
            body: JSON.stringify({ package_id: packageId })
        });
        
        if (data && data.success) {
            showToast(`购买成功！获得 ${data.credits || ''} 次诊断次数`, 'success');
            // 刷新余额
            await fetchCreditsBalance();
            closeBuyModal();
            return true;
        } else {
            const errorMsg = data.message || '购买失败，请稍后重试';
            showToast(errorMsg, 'error');
            return false;
        }
    } catch (error) {
        console.error('购买失败:', error);
        showToast('购买失败，请稍后重试', 'error');
        return false;
    } finally {
        CreditsState.isPurchasing = false;
        if (DOM.buyConfirmBtn) {
            DOM.buyConfirmBtn.disabled = false;
            DOM.buyConfirmBtn.textContent = '确认购买';
        }
    }
}

// ============================================================
// 核心功能：消耗诊断次数
// ============================================================

/**
 * 检查是否有足够的诊断次数
 * @param {number} required - 需要的次数
 * @returns {boolean}
 */
function hasEnoughCredits(required = 1) {
    return CreditsState.balance >= required;
}

/**
 * 打开消耗确认弹窗
 * @param {string} reason - 消耗原因
 * @param {number} amount - 消耗数量
 * @param {function} onConfirm - 确认后的回调
 */
function openConsumeModal(reason = '', amount = 1, onConfirm = null) {
    if (!DOM.consumeConfirmModal) {
        showToast('消耗确认功能暂不可用', 'error');
        return;
    }
    
    // 检查余额
    if (!hasEnoughCredits(amount)) {
        showToast(`诊断次数不足（需要 ${amount} 次，当前 ${CreditsState.balance} 次）`, 'warning');
        // 自动弹出购买弹窗
        setTimeout(() => openBuyModal(), 500);
        return;
    }
    
    // 设置消耗原因显示
    if (DOM.consumeReason) {
        DOM.consumeReason.textContent = reason || '诊断服务消耗';
    }
    
    // 存储确认回调
    DOM.consumeConfirmModal.dataset.callback = onConfirm ? 'custom' : 'default';
    DOM.consumeConfirmModal.dataset.amount = amount;
    if (onConfirm) {
        DOM.consumeConfirmModal._onConfirm = onConfirm;
    }
    
    DOM.consumeConfirmModal.classList.add('active');
    DOM.consumeConfirmModal.style.display = 'block';
    document.body.style.overflow = 'hidden';
}

/**
 * 关闭消耗确认弹窗
 */
function closeConsumeModal() {
    if (!DOM.consumeConfirmModal) return;
    
    DOM.consumeConfirmModal.classList.remove('active');
    DOM.consumeConfirmModal.style.display = 'none';
    document.body.style.overflow = '';
    delete DOM.consumeConfirmModal._onConfirm;
}

/**
 * 执行消耗诊断次数
 * @param {string} reason - 消耗原因
 * @param {number} amount - 消耗数量
 * @returns {Promise<boolean>} 是否成功
 */
async function consumeCredits(reason = '诊断服务', amount = 1) {
    if (CreditsState.isConsuming) return false;
    
    if (!hasEnoughCredits(amount)) {
        showToast(`诊断次数不足（需要 ${amount} 次，当前 ${CreditsState.balance} 次）`, 'warning');
        return false;
    }
    
    CreditsState.isConsuming = true;
    
    try {
        const data = await apiRequest('/api/credits/consume', {
            method: 'POST',
            body: JSON.stringify({
                reason: reason,
                amount: amount
            })
        });
        
        if (data && data.success) {
            // 更新本地余额
            CreditsState.balance = data.balance || (CreditsState.balance - amount);
            updateBalanceDisplay();
            
            showToast(`消耗 ${amount} 次诊断次数`, 'success');
            return true;
        } else {
            const errorMsg = data.message || '消耗失败，请稍后重试';
            showToast(errorMsg, 'error');
            return false;
        }
    } catch (error) {
        console.error('消耗诊断次数失败:', error);
        showToast('消耗失败，请稍后重试', 'error');
        return false;
    } finally {
        CreditsState.isConsuming = false;
    }
}

// ============================================================
// 事件绑定
// ============================================================

/**
 * 初始化所有事件监听
 */
function initEventListeners() {
    // 购买按钮
    if (DOM.buyBtn) {
        DOM.buyBtn.addEventListener('click', (e) => {
            e.preventDefault();
            openBuyModal();
        });
    }
    
    // 购买弹窗关闭按钮
    if (DOM.buyModalClose) {
        DOM.buyModalClose.addEventListener('click', closeBuyModal);
    }
    
    // 购买弹窗取消按钮
    if (DOM.buyCancelBtn) {
        DOM.buyCancelBtn.addEventListener('click', closeBuyModal);
    }
    
    // 点击弹窗外部关闭
    if (DOM.buyModal) {
        DOM.buyModal.addEventListener('click', (e) => {
            if (e.target === DOM.buyModal) {
                closeBuyModal();
            }
        });
    }
    
    // 购买表单提交
    if (DOM.buyForm) {
        DOM.buyForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const packageId = DOM.buyPackageSelect ? DOM.buyPackageSelect.value : '';
            await submitPurchase(packageId);
        });
    }
    
    // 购买确认按钮
    if (DOM.buyConfirmBtn) {
        DOM.buyConfirmBtn.addEventListener('click', async () => {
            const packageId = DOM.buyPackageSelect ? DOM.buyPackageSelect.value : '';
            await submitPurchase(packageId);
        });
    }
    
    // 消耗确认弹窗关闭
    if (DOM.consumeCancelBtn) {
        DOM.consumeCancelBtn.addEventListener('click', closeConsumeModal);
    }
    
    // 消耗确认按钮
    if (DOM.consumeConfirmBtn) {
        DOM.consumeConfirmBtn.addEventListener('click', async () => {
            const amount = parseInt(DOM.consumeConfirmModal.dataset.amount || '1', 10);
            const reason = DOM.consumeReason ? DOM.consumeReason.textContent : '诊断服务';
            
            // 检查是否有自定义回调
            if (DOM.consumeConfirmModal._onConfirm) {
                const result = await DOM.consumeConfirmModal._onConfirm(reason, amount);
                if (result !== false) {
                    closeConsumeModal();
                }
            } else {
                const success = await consumeCredits(reason, amount);
                if (success) {
                    closeConsumeModal();
                }
            }
        });
    }
    
    // 消耗弹窗外部点击关闭
    if (DOM.consumeConfirmModal) {
        DOM.consumeConfirmModal.addEventListener('click', (e) => {
            if (e.target === DOM.consumeConfirmModal) {
                closeConsumeModal();
            }
        });
    }
    
    // 页面可见性变化时刷新余额
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            fetchCreditsBalance(false);
        }
    });
    
    // 页面关闭时停止自动刷新
    window.addEventListener('beforeunload', () => {
        stopAutoRefresh();
    });
}

// ============================================================
// 初始化
// ============================================================

/**
 * 初始化诊断次数管理模块
 */
async function initCreditsManager() {
    console.log('[CreditsManager] 初始化诊断次数管理...');
    
    // 初始化事件监听
    initEventListeners();
    
    // 获取初始余额
    await fetchCreditsBalance();
    
    // 启动自动刷新
    startAutoRefresh();
    
    // 添加 CSS 动画（如果不存在）
    if (!document.getElementById('credits-animation-style')) {
        const style = document.createElement('style');
        style.id = 'credits-animation-style';
        style.textContent = `
            @keyframes slideIn {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            
            .credits-empty {
                color: #ef4444 !important;
            }
            
            .credits-low {
                color: #f59e0b !important;
            }
            
            .credits-sufficient {
                color: #10b981 !important;
            }
            
            #credits-buy-modal.active,
            #credits-consume-modal.active {
                display: block !important;
            }
        `;
        document.head.appendChild(style);
    }
    
    console.log('[CreditsManager] 初始化完成');
}

// ============================================================
// 导出接口（供其他模块使用）
// ============================================================

window.CreditsManager = {
    // 状态
    state: CreditsState,
    
    // 余额管理
    fetchBalance: fetchCreditsBalance,
    getBalance: () => CreditsState.balance,
    hasEnough: hasEnoughCredits,
    updateDisplay: updateBalanceDisplay,
    
    // 购买
    openBuyModal: openBuyModal,
    closeBuyModal: closeBuyModal,
    purchase: submitPurchase,
    
    // 消耗
    openConsumeModal: openConsumeModal,
    closeConsumeModal: closeConsumeModal,
    consume: consumeCredits,
    
    // 生命周期
    init: initCreditsManager,
    startAutoRefresh: startAutoRefresh,
    stopAutoRefresh: stopAutoRefresh
};

// ============================================================
// 自动初始化（DOM 加载完成后）
// ============================================================
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCreditsManager);
} else {
    // DOM 已经加载完成
    initCreditsManager();
}