/**
 * credits.js — 诊断次数管理脚本
 * 功能：检查剩余次数、显示付费卡片、确认消耗弹窗
 * 属于 Issue #26 Task A: 按次诊断计费方案设计与实现
 */

// ============================================================
// 全局状态
// ============================================================
let currentCredits = 0;          // 当前剩余诊断次数
let isCheckingCredits = false;   // 防止重复请求
let creditCheckTimer = null;     // 定时检查句柄

// ============================================================
// DOM 引用（延迟初始化）
// ============================================================
let dom = {};

function initDOM() {
    dom = {
        creditBadge: document.getElementById('credit-badge'),
        creditCount: document.getElementById('credit-count'),
        payCard: document.getElementById('pay-card'),
        payCardOverlay: document.getElementById('pay-card-overlay'),
        confirmModal: document.getElementById('confirm-modal'),
        confirmModalOverlay: document.getElementById('confirm-modal-overlay'),
        confirmBtn: document.getElementById('confirm-btn'),
        cancelBtn: document.getElementById('cancel-btn'),
        closePayCard: document.getElementById('close-pay-card'),
        closeConfirmModal: document.getElementById('close-confirm-modal'),
        buyBtn: document.getElementById('buy-credits-btn'),
        diagnoseBtn: document.getElementById('diagnose-btn'),
        diagnoseLink: document.querySelector('[data-action="diagnose"]'),
    };
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 格式化数字显示
 */
function formatNumber(num) {
    if (num >= 10000) {
        return (num / 10000).toFixed(1) + '万';
    }
    return num.toString();
}

/**
 * 显示错误提示（可替换为更优雅的 toast）
 */
function showError(message) {
    console.error('[Credits]', message);
    // 如果有全局 toast 函数则调用
    if (typeof window.showToast === 'function') {
        window.showToast(message, 'error');
    } else {
        alert(message);
    }
}

/**
 * 显示成功提示
 */
function showSuccess(message) {
    console.log('[Credits]', message);
    if (typeof window.showToast === 'function') {
        window.showToast(message, 'success');
    }
}

// ============================================================
// 核心 API 调用
// ============================================================

/**
 * 获取当前用户剩余诊断次数
 * @returns {Promise<number>} 剩余次数
 */
async function fetchCredits() {
    try {
        const response = await fetch('/api/v1/credits/balance', {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `获取次数失败 (${response.status})`);
        }

        const data = await response.json();
        return data.credits;
    } catch (error) {
        showError('获取诊断次数失败: ' + error.message);
        throw error;
    }
}

/**
 * 消耗一次诊断次数
 * @returns {Promise<boolean>} 是否成功
 */
async function consumeCredit() {
    try {
        const response = await fetch('/api/v1/credits/consume', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ action: 'diagnose' }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `消耗次数失败 (${response.status})`);
        }

        const data = await response.json();
        return data.success;
    } catch (error) {
        showError('消耗诊断次数失败: ' + error.message);
        return false;
    }
}

/**
 * 获取付费方案列表
 * @returns {Promise<Array>} 付费方案数组
 */
async function fetchPlans() {
    try {
        const response = await fetch('/api/v1/credits/plans', {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
        });

        if (!response.ok) {
            throw new Error(`获取付费方案失败 (${response.status})`);
        }

        return await response.json();
    } catch (error) {
        showError('获取付费方案失败: ' + error.message);
        return [];
    }
}

// ============================================================
// UI 更新函数
// ============================================================

/**
 * 更新次数显示徽章
 */
function updateCreditBadge(credits) {
    currentCredits = credits;

    if (dom.creditBadge) {
        dom.creditBadge.textContent = formatNumber(credits);
        dom.creditBadge.className = 'credit-badge';
        if (credits <= 0) {
            dom.creditBadge.classList.add('credit-badge--empty');
        } else if (credits <= 3) {
            dom.creditBadge.classList.add('credit-badge--low');
        } else {
            dom.creditBadge.classList.add('credit-badge--normal');
        }
    }

    if (dom.creditCount) {
        dom.creditCount.textContent = formatNumber(credits);
    }

    // 更新诊断按钮状态
    updateDiagnoseButton(credits);
}

/**
 * 根据剩余次数更新诊断按钮状态
 */
function updateDiagnoseButton(credits) {
    const buttons = [dom.diagnoseBtn, dom.diagnoseLink].filter(Boolean);
    const canDiagnose = credits > 0;

    buttons.forEach(btn => {
        if (btn) {
            btn.disabled = !canDiagnose;
            btn.classList.toggle('disabled', !canDiagnose);
            btn.title = canDiagnose ? `剩余 ${credits} 次诊断机会` : '诊断次数已用完，请购买';
        }
    });
}

/**
 * 显示付费卡片
 */
function showPayCard() {
    if (dom.payCard && dom.payCardOverlay) {
        dom.payCard.classList.add('active');
        dom.payCardOverlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        loadPlansIntoCard();
    }
}

/**
 * 隐藏付费卡片
 */
function hidePayCard() {
    if (dom.payCard && dom.payCardOverlay) {
        dom.payCard.classList.remove('active');
        dom.payCardOverlay.classList.remove('active');
        document.body.style.overflow = '';
    }
}

/**
 * 加载付费方案到卡片中
 */
async function loadPlansIntoCard() {
    const plansContainer = document.getElementById('plans-container');
    if (!plansContainer) return;

    plansContainer.innerHTML = '<div class="loading-spinner">加载中...</div>';

    try {
        const plans = await fetchPlans();
        if (!plans || plans.length === 0) {
            plansContainer.innerHTML = '<p class="empty-plans">暂无可用方案</p>';
            return;
        }

        plansContainer.innerHTML = plans.map((plan, index) => `
            <div class="plan-card ${plan.recommended ? 'plan-card--recommended' : ''}" data-plan-id="${plan.id}">
                ${plan.recommended ? '<span class="plan-badge">推荐</span>' : ''}
                <h3 class="plan-name">${plan.name}</h3>
                <p class="plan-description">${plan.description || ''}</p>
                <div class="plan-price">
                    <span class="price-amount">¥${plan.price}</span>
                    <span class="price-unit">/${plan.credits}次</span>
                </div>
                <ul class="plan-features">
                    ${(plan.features || []).map(f => `<li>${f}</li>`).join('')}
                </ul>
                <button class="btn btn-primary plan-select-btn" data-plan-id="${plan.id}">
                    立即购买
                </button>
            </div>
        `).join('');

        // 绑定购买按钮事件
        plansContainer.querySelectorAll('.plan-select-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                const planId = this.dataset.planId;
                handlePurchase(planId);
            });
        });

    } catch (error) {
        plansContainer.innerHTML = '<p class="error-message">加载方案失败，请重试</p>';
    }
}

/**
 * 处理购买请求
 */
async function handlePurchase(planId) {
    try {
        const response = await fetch('/api/v1/credits/purchase', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ plan_id: planId }),
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `购买失败 (${response.status})`);
        }

        const data = await response.json();
        showSuccess('购买成功！');
        hidePayCard();
        
        // 刷新次数
        await refreshCredits();

        // 如果有支付跳转链接
        if (data.payment_url) {
            window.location.href = data.payment_url;
        }
    } catch (error) {
        showError('购买失败: ' + error.message);
    }
}

/**
 * 显示确认消耗弹窗
 */
function showConfirmModal() {
    if (dom.confirmModal && dom.confirmModalOverlay) {
        dom.confirmModal.classList.add('active');
        dom.confirmModalOverlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

/**
 * 隐藏确认消耗弹窗
 */
function hideConfirmModal() {
    if (dom.confirmModal && dom.confirmModalOverlay) {
        dom.confirmModal.classList.remove('active');
        dom.confirmModalOverlay.classList.remove('active');
        document.body.style.overflow = '';
    }
}

/**
 * 刷新剩余次数
 */
async function refreshCredits() {
    try {
        const credits = await fetchCredits();
        updateCreditBadge(credits);
        return credits;
    } catch (error) {
        return currentCredits;
    }
}

// ============================================================
// 事件处理
// ============================================================

/**
 * 处理诊断按钮点击
 */
async function handleDiagnoseClick(event) {
    if (event) event.preventDefault();

    if (isCheckingCredits) return;
    isCheckingCredits = true;

    try {
        // 先检查次数
        const credits = await refreshCredits();

        if (credits <= 0) {
            // 次数不足，显示付费卡片
            showPayCard();
            return;
        }

        // 显示确认弹窗
        showConfirmModal();
    } catch (error) {
        showError('检查次数失败，请重试');
    } finally {
        isCheckingCredits = false;
    }
}

/**
 * 确认消耗次数
 */
async function confirmConsume() {
    hideConfirmModal();

    try {
        const success = await consumeCredit();
        if (success) {
            showSuccess('诊断次数已消耗');
            await refreshCredits();
            // 触发诊断流程
            if (typeof window.startDiagnose === 'function') {
                window.startDiagnose();
            } else {
                // 默认跳转到诊断页面
                window.location.href = '/diagnose';
            }
        } else {
            showError('消耗次数失败，请重试');
        }
    } catch (error) {
        showError('消耗次数失败: ' + error.message);
    }
}

// ============================================================
// 初始化
// ============================================================

function initCredits() {
    // 等待 DOM 加载完成
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCredits);
        return;
    }

    initDOM();

    // 初始化次数显示
    refreshCredits().catch(() => {});

    // 绑定事件
    if (dom.diagnoseBtn) {
        dom.diagnoseBtn.addEventListener('click', handleDiagnoseClick);
    }

    if (dom.diagnoseLink) {
        dom.diagnoseLink.addEventListener('click', handleDiagnoseClick);
    }

    if (dom.buyBtn) {
        dom.buyBtn.addEventListener('click', showPayCard);
    }

    if (dom.closePayCard) {
        dom.closePayCard.addEventListener('click', hidePayCard);
    }

    if (dom.payCardOverlay) {
        dom.payCardOverlay.addEventListener('click', hidePayCard);
    }

    if (dom.confirmBtn) {
        dom.confirmBtn.addEventListener('click', confirmConsume);
    }

    if (dom.cancelBtn) {
        dom.cancelBtn.addEventListener('click', hideConfirmModal);
    }

    if (dom.closeConfirmModal) {
        dom.closeConfirmModal.addEventListener('click', hideConfirmModal);
    }

    if (dom.confirmModalOverlay) {
        dom.confirmModalOverlay.addEventListener('click', hideConfirmModal);
    }

    // 定时刷新次数（每 60 秒）
    if (creditCheckTimer) {
        clearInterval(creditCheckTimer);
    }
    creditCheckTimer = setInterval(refreshCredits, 60000);

    console.log('[Credits] 诊断次数管理已初始化');
}

// 启动初始化
initCredits();

// ============================================================
// 导出（供其他模块使用）
// ============================================================
window.creditsManager = {
    refresh: refreshCredits,
    getCredits: () => currentCredits,
    showPayCard,
    hidePayCard,
    showConfirmModal,
    hideConfirmModal,
};