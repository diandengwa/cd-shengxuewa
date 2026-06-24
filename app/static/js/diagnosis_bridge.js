/**
 * diagnosis_bridge.js
 * 诊断引导组件脚本 — 处理查询→诊断的上下文传递
 * 用于成都K12升学参谋（cd-shengxuewa）产品闭环整合
 * 
 * 功能：
 * 1. 从政策查询页面捕获用户查询上下文
 * 2. 将上下文传递到诊断页面
 * 3. 支持诊断结果回写到查询页面
 * 4. 处理页面间导航和状态管理
 * 5. 支持诊断历史记录查看
 * 6. 支持一键重新诊断
 * 7. 支持诊断次数检查与付费引导（Issue #26）
 * 8. 查询结果页底部引导按钮
 * 9. 一键带入诊断上下文
 * 10. 诊断结果中引用政策原文可点击回看
 * 11. 诊断前确认逻辑：调用/check-credits接口，显示确认弹窗，消耗次数后发起诊断
 */

(function() {
    'use strict';

    // ============================================================
    // 配置常量
    // ============================================================
    const CONFIG = {
        // 存储键名
        STORAGE_KEY: 'diagnosis_bridge_context',
        // 诊断页面路径
        DIAGNOSIS_PATH: '/diagnosis',
        // 查询页面路径
        QUERY_PATH: '/query',
        // 上下文有效期（毫秒）— 30分钟
        CONTEXT_TTL: 30 * 60 * 1000,
        // 事件名称
        EVENTS: {
            CONTEXT_READY: 'diagnosis:context-ready',
            DIAGNOSIS_COMPLETE: 'diagnosis:complete',
            NAVIGATE_TO_DIAGNOSIS: 'diagnosis:navigate',
            DIAGNOSIS_HISTORY: 'diagnosis:history',
            CREDITS_CHECK: 'diagnosis:credits-check',
            CREDITS_INSUFFICIENT: 'diagnosis:credits-insufficient',
            PAYMENT_GUIDE: 'diagnosis:payment-guide',
            POLICY_REFERENCE_CLICK: 'diagnosis:policy-reference-click'
        },
        // 诊断结果存储键名
        RESULT_STORAGE_KEY: 'diagnosis_results',
        // 最大历史记录数
        MAX_HISTORY: 20,
        // API端点
        API: {
            CHECK_CREDITS: '/api/v1/credits/check',
            GET_CREDITS: '/api/v1/credits/balance',
            DIAGNOSIS_START: '/api/v1/diagnosis/start',
            GET_POLICY: '/api/v1/policy/'
        },
        // 付费引导配置
        PAYMENT: {
            MIN_CREDITS_REQUIRED: 1,
            PRICE_PER_DIAGNOSIS: 9.9,
            PACKAGE_URL: '/payment/packages',
            RECHARGE_URL: '/payment/recharge'
        },
        // UI配置
        UI: {
            GUIDE_BUTTON_CLASS: 'diagnosis-guide-btn',
            GUIDE_BAR_CLASS: 'diagnosis-guide-bar',
            POLICY_REFERENCE_CLASS: 'diagnosis-policy-ref',
            CONTEXT_BADGE_CLASS: 'diagnosis-context-badge',
            CONFIRM_MODAL_CLASS: 'diagnosis-confirm-modal',
            CONFIRM_MODAL_OVERLAY_CLASS: 'diagnosis-confirm-overlay'
        }
    };

    // ============================================================
    // 工具函数
    // ============================================================

    /**
     * 生成唯一标识符
     * @returns {string} UUID v4 格式字符串
     */
    function generateId() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    /**
     * 安全解析 JSON，失败返回默认值
     * @param {string} str - JSON 字符串
     * @param {*} defaultVal - 解析失败时的默认值
     * @returns {*} 解析结果
     */
    function safeParseJSON(str, defaultVal = null) {
        if (!str) return defaultVal;
        try {
            return JSON.parse(str);
        } catch (e) {
            console.warn('[diagnosis_bridge] JSON解析失败:', e.message);
            return defaultVal;
        }
    }

    /**
     * 检查上下文是否过期
     * @param {Object} context - 上下文对象
     * @returns {boolean} 是否过期
     */
    function isContextExpired(context) {
        if (!context || !context.timestamp) return true;
        return (Date.now() - context.timestamp) > CONFIG.CONTEXT_TTL;
    }

    /**
     * 获取当前页面路径
     * @returns {string} 当前页面路径
     */
    function getCurrentPath() {
        return window.location.pathname;
    }

    /**
     * 判断是否在诊断页面
     * @returns {boolean}
     */
    function isOnDiagnosisPage() {
        return getCurrentPath().startsWith(CONFIG.DIAGNOSIS_PATH);
    }

    /**
     * 判断是否在查询页面
     * @returns {boolean}
     */
    function isOnQueryPage() {
        return getCurrentPath().startsWith(CONFIG.QUERY_PATH);
    }

    /**
     * 显示加载状态
     * @param {string} message - 加载提示信息
     */
    function showLoading(message = '处理中...') {
        const overlay = document.createElement('div');
        overlay.className = 'diagnosis-loading-overlay';
        overlay.innerHTML = `
            <div class="diagnosis-loading-spinner">
                <div class="spinner"></div>
                <p>${message}</p>
            </div>
        `;
        document.body.appendChild(overlay);
    }

    /**
     * 隐藏加载状态
     */
    function hideLoading() {
        const overlay = document.querySelector('.diagnosis-loading-overlay');
        if (overlay) {
            overlay.remove();
        }
    }

    /**
     * 显示错误提示
     * @param {string} message - 错误信息
     */
    function showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'diagnosis-error-toast';
        errorDiv.textContent = message;
        document.body.appendChild(errorDiv);
        setTimeout(() => {
            errorDiv.remove();
        }, 3000);
    }

    // ============================================================
    // 核心功能类
    // ============================================================

    class DiagnosisBridge {
        constructor() {
            this.context = null;
            this.creditsBalance = 0;
            this.init();
        }

        /**
         * 初始化桥接器
         */
        init() {
            // 加载已保存的上下文
            this.loadContext();
            // 获取用户配额信息
            this.fetchCreditsBalance();
            // 绑定事件监听
            this.bindEvents();
            // 根据当前页面执行相应初始化
            if (isOnQueryPage()) {
                this.initQueryPage();
            } else if (isOnDiagnosisPage()) {
                this.initDiagnosisPage();
            }
        }

        /**
         * 从 localStorage 加载上下文
         */
        loadContext() {
            const stored = localStorage.getItem(CONFIG.STORAGE_KEY);
            if (stored) {
                const parsed = safeParseJSON(stored);
                if (parsed && !isContextExpired(parsed)) {
                    this.context = parsed;
                    console.log('[diagnosis_bridge] 上下文已加载:', this.context);
                } else {
                    // 上下文过期，清除
                    localStorage.removeItem(CONFIG.STORAGE_KEY);
                    console.log('[diagnosis_bridge] 上下文已过期，已清除');
                }
            }
        }

        /**
         * 保存上下文到 localStorage
         * @param {Object} context - 上下文数据
         */
        saveContext(context) {
            const data = {
                ...context,
                id: context.id || generateId(),
                timestamp: Date.now()
            };
            localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(data));
            this.context = data;
            console.log('[diagnosis_bridge] 上下文已保存:', data);
        }

        /**
         * 清除上下文
         */
        clearContext() {
            localStorage.removeItem(CONFIG.STORAGE_KEY);
            this.context = null;
            console.log('[diagnosis_bridge] 上下文已清除');
        }

        /**
         * 获取用户配额余额
         */
        async fetchCreditsBalance() {
            try {
                const response = await fetch(CONFIG.API.GET_CREDITS, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();
                if (data.success) {
                    this.creditsBalance = data.balance || 0;
                    console.log('[diagnosis_bridge] 配额余额:', this.creditsBalance);
                    // 触发余额更新事件
                    this.dispatchEvent(CONFIG.EVENTS.CREDITS_CHECK, { balance: this.creditsBalance });
                }
            } catch (error) {
                console.error('[diagnosis_bridge] 获取配额失败:', error);
                // 静默失败，不影响用户体验
            }
        }

        /**
         * 检查是否有足够配额进行诊断
         * @returns {Promise<Object>} { sufficient: boolean, balance: number }
         */
        async checkCredits() {
            try {
                const response = await fetch(CONFIG.API.CHECK_CREDITS, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({
                        required: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED
                    })
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();
                return {
                    sufficient: data.sufficient || false,
                    balance: data.balance || 0,
                    message: data.message || ''
                };
            } catch (error) {
                console.error('[diagnosis_bridge] 配额检查失败:', error);
                return {
                    sufficient: false,
                    balance: 0,
                    message: '配额检查失败，请稍后重试'
                };
            }
        }

        /**
         * 消耗一次诊断配额
         * @returns {Promise<Object>} { success: boolean, message: string }
         */
        async consumeCredits() {
            try {
                const response = await fetch(CONFIG.API.DIAGNOSIS_START, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({
                        context_id: this.context ? this.context.id : null
                    })
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();
                return {
                    success: data.success || false,
                    message: data.message || '',
                    diagnosis_id: data.diagnosis_id || null
                };
            } catch (error) {
                console.error('[diagnosis_bridge] 消耗配额失败:', error);
                return {
                    success: false,
                    message: '诊断启动失败，请稍后重试',
                    diagnosis_id: null
                };
            }
        }

        /**
         * 显示确认弹窗
         * @param {Function} onConfirm - 确认回调
         * @param {Function} onCancel - 取消回调
         */
        showConfirmModal(onConfirm, onCancel) {
            // 移除已存在的弹窗
            this.removeConfirmModal();

            const overlay = document.createElement('div');
            overlay.className = CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS;
            
            const modal = document.createElement('div');
            modal.className = CONFIG.UI.CONFIRM_MODAL_CLASS;
            modal.innerHTML = `
                <div class="modal-header">
                    <h3>确认诊断</h3>
                    <button class="modal-close-btn" aria-label="关闭">&times;</button>
                </div>
                <div class="modal-body">
                    <p>本次诊断将消耗 <strong>1</strong> 次诊断次数。</p>
                    <p>当前剩余次数：<strong id="credits-display">${this.creditsBalance}</strong> 次</p>
                    ${this.context ? `<div class="context-preview">
                        <p>诊断上下文：</p>
                        <p class="context-text">${this.context.query || '无'}</p>
                    </div>` : ''}
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary cancel-btn">取消</button>
                    <button class="btn btn-primary confirm-btn">确认诊断</button>
                </div>
            `;

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // 绑定事件
            const closeBtn = modal.querySelector('.modal-close-btn');
            const cancelBtn = modal.querySelector('.cancel-btn');
            const confirmBtn = modal.querySelector('.confirm-btn');

            const closeModal = () => {
                this.removeConfirmModal();
                if (onCancel) onCancel();
            };

            closeBtn.addEventListener('click', closeModal);
            cancelBtn.addEventListener('click', closeModal);
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    closeModal();
                }
            });

            confirmBtn.addEventListener('click', async () => {
                if (onConfirm) {
                    await onConfirm();
                }
                this.removeConfirmModal();
            });
        }

        /**
         * 移除确认弹窗
         */
        removeConfirmModal() {
            const overlay = document.querySelector(`.${CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS}`);
            if (overlay) {
                overlay.remove();
            }
        }

        /**
         * 显示付费引导弹窗
         */
        showPaymentGuide() {
            // 触发付费引导事件
            this.dispatchEvent(CONFIG.EVENTS.PAYMENT_GUIDE, {
                balance: this.creditsBalance,
                price: CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS,
                packageUrl: CONFIG.PAYMENT.PACKAGE_URL,
                rechargeUrl: CONFIG.PAYMENT.RECHARGE_URL
            });

            // 创建付费引导弹窗
            const overlay = document.createElement('div');
            overlay.className = 'diagnosis-payment-overlay';
            overlay.innerHTML = `
                <div class="diagnosis-payment-modal">
                    <div class="modal-header">
                        <h3>诊断次数不足</h3>
                        <button class="modal-close-btn" aria-label="关闭">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="payment-info">
                            <p>当前剩余诊断次数：<strong>${this.creditsBalance}</strong> 次</p>
                            <p>每次诊断需要消耗 <strong>1</strong> 次诊断次数</p>
                            <p class="price-info">单次诊断价格：<strong>¥${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS}</strong></p>
                        </div>
                        <div class="payment-options">
                            <a href="${CONFIG.PAYMENT.PACKAGE_URL}" class="btn btn-primary">购买次数包</a>
                            <a href="${CONFIG.PAYMENT.RECHARGE_URL}" class="btn btn-secondary">立即充值</a>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            // 绑定关闭事件
            const closeBtn = overlay.querySelector('.modal-close-btn');
            closeBtn.addEventListener('click', () => {
                overlay.remove();
            });
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    overlay.remove();
                }
            });
        }

        /**
         * 发起诊断流程
         */
        async startDiagnosis() {
            // 检查配额
            const creditsCheck = await this.checkCredits();
            
            if (!creditsCheck.sufficient) {
                // 配额不足，显示付费引导
                this.showPaymentGuide();
                return;
            }

            // 显示确认弹窗
            this.showConfirmModal(async () => {
                showLoading('正在启动诊断...');
                try {
                    // 消耗配额并启动诊断
                    const result = await this.consumeCredits();
                    if (result.success) {
                        // 更新本地配额
                        this.creditsBalance = creditsCheck.balance - 1;
                        // 保存诊断ID到上下文
                        if (this.context) {
                            this.context.diagnosis_id = result.diagnosis_id;
                            this.saveContext(this.context);
                        }
                        // 导航到诊断页面
                        this.navigateToDiagnosis();
                    } else {
                        showError(result.message || '诊断启动失败');
                    }
                } catch (error) {
                    console.error('[diagnosis_bridge] 诊断启动异常:', error);
                    showError('诊断启动异常，请稍后重试');
                } finally {
                    hideLoading();
                }
            });
        }

        /**
         * 导航到诊断页面
         * @param {Object} [extraParams] - 额外参数
         */
        navigateToDiagnosis(extraParams = {}) {
            const params = new URLSearchParams();
            if (this.context) {
                params.set('context_id', this.context.id);
                if (this.context.query) {
                    params.set('q', this.context.query);
                }
            }
            // 添加额外参数
            Object.entries(extraParams).forEach(([key, value]) => {
                params.set(key, value);
            });

            const targetUrl = `${CONFIG.DIAGNOSIS_PATH}?${params.toString()}`;
            console.log('[diagnosis_bridge] 导航到诊断页面:', targetUrl);
            
            // 触发导航事件
            this.dispatchEvent(CONFIG.EVENTS.NAVIGATE_TO_DIAGNOSIS, { url: targetUrl });
            
            // 执行导航
            window.location.href = targetUrl;
        }

        /**
         * 保存诊断结果
         * @param {Object} result - 诊断结果
         */
        saveDiagnosisResult(result) {
            if (!result || !result.id) return;
            
            const stored = localStorage.getItem(CONFIG.RESULT_STORAGE_KEY);
            const history = stored ? safeParseJSON(stored, []) : [];
            
            // 添加新结果到开头
            history.unshift({
                ...result,
                savedAt: Date.now()
            });
            
            // 限制历史记录数量
            if (history.length > CONFIG.MAX_HISTORY) {
                history.length = CONFIG.MAX_HISTORY;
            }
            
            localStorage.setItem(CONFIG.RESULT_STORAGE_KEY, JSON.stringify(history));
            console.log('[diagnosis_bridge] 诊断结果已保存');
        }

        /**
         * 获取诊断历史
         * @returns {Array} 历史记录列表
         */
        getDiagnosisHistory() {
            const stored = localStorage.getItem(CONFIG.RESULT_STORAGE_KEY);
            return stored ? safeParseJSON(stored, []) : [];
        }

        /**
         * 绑定全局事件
         */
        bindEvents() {
            // 监听诊断完成事件
            document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, (e) => {
                if (e.detail) {
                    this.saveDiagnosisResult(e.detail);
                }
            });

            // 监听上下文就绪事件
            document.addEventListener(CONFIG.EVENTS.CONTEXT_READY, (e) => {
                if (e.detail) {
                    this.saveContext(e.detail);
                }
            });

            // 监听政策引用点击事件
            document.addEventListener(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, (e) => {
                if (e.detail && e.detail.policyId) {
                    this.openPolicyReference(e.detail.policyId);
                }
            });
        }

        /**
         * 触发自定义事件
         * @param {string} eventName - 事件名称
         * @param {Object} detail - 事件数据
         */
        dispatchEvent(eventName, detail = {}) {
            const event = new CustomEvent(eventName, { detail });
            document.dispatchEvent(event);
        }

        /**
         * 打开政策原文引用
         * @param {string} policyId - 政策ID
         */
        async openPolicyReference(policyId) {
            try {
                const response = await fetch(`${CONFIG.API.GET_POLICY}${policyId}`, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const data = await response.json();
                if (data.success && data.policy) {
                    // 在新窗口打开政策详情
                    const policyUrl = `/policy/${policyId}`;
                    window.open(policyUrl, '_blank');
                }
            } catch (error) {
                console.error('[diagnosis_bridge] 获取政策引用失败:', error);
                showError('无法打开政策原文');
            }
        }

        /**
         * 初始化查询页面
         */
        initQueryPage() {
            // 添加诊断引导按钮
            this.addGuideButton();
            // 绑定查询表单提交事件
            this.bindQueryFormSubmit();
        }

        /**
         * 添加诊断引导按钮
         */
        addGuideButton() {
            const guideBar = document.querySelector(`.${CONFIG.UI.GUIDE_BAR_CLASS}`);
            if (guideBar) {
                const button = document.createElement('button');
                button.className = `btn btn-primary ${CONFIG.UI.GUIDE_BUTTON_CLASS}`;
                button.innerHTML = `
                    <span class="button-icon">🔍</span>
                    <span class="button-text">智能诊断</span>
                    <span class="button-badge">${this.creditsBalance}次</span>
                `;
                button.addEventListener('click', () => {
                    this.startDiagnosis();
                });
                guideBar.appendChild(button);
            }
        }

        /**
         * 绑定查询表单提交事件
         */
        bindQueryFormSubmit() {
            const queryForm = document.querySelector('#query-form');
            if (queryForm) {
                queryForm.addEventListener('submit', (e) => {
                    const queryInput = queryForm.querySelector('#query-input');
                    if (queryInput && queryInput.value.trim()) {
                        // 保存查询上下文
                        this.saveContext({
                            query: queryInput.value.trim(),
                            source: 'query_page',
                            url: window.location.href
                        });
                    }
                });
            }
        }

        /**
         * 初始化诊断页面
         */
        initDiagnosisPage() {
            // 加载上下文
            if (this.context) {
                this.applyContextToDiagnosis();
            }
            // 绑定诊断结果保存
            this.bindDiagnosisResultSave();
            // 绑定政策引用链接
            this.bindPolicyReferences();
        }

        /**
         * 将上下文应用到诊断页面
         */
        applyContextToDiagnosis() {
            const contextBadge = document.querySelector(`.${CONFIG.UI.CONTEXT_BADGE_CLASS}`);
            if (contextBadge && this.context) {
                contextBadge.textContent = `诊断上下文: ${this.context.query || '无'}`;
                contextBadge.style.display = 'block';
            }

            // 填充诊断表单
            const diagnosisForm = document.querySelector('#diagnosis-form');
            if (diagnosisForm && this.context) {
                const queryField = diagnosisForm.querySelector('#diagnosis-query');
                if (queryField && this.context.query) {
                    queryField.value = this.context.query;
                }
            }
        }

        /**
         * 绑定诊断结果保存
         */
        bindDiagnosisResultSave() {
            const saveButton = document.querySelector('#save-diagnosis-result');
            if (saveButton) {
                saveButton.addEventListener('click', () => {
                    const resultData = safeParseJSON(
                        document.querySelector('#diagnosis-result-data')?.textContent
                    );
                    if (resultData) {
                        this.saveDiagnosisResult(resultData);
                        showError('诊断结果已保存');
                    }
                });
            }
        }

        /**
         * 绑定政策引用链接
         */
        bindPolicyReferences() {
            document.querySelectorAll(`.${CONFIG.UI.POLICY_REFERENCE_CLASS}`).forEach((element) => {
                element.addEventListener('click', (e) => {
                    e.preventDefault();
                    const policyId = element.dataset.policyId;
                    if (policyId) {
                        this.dispatchEvent(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, { policyId });
                    }
                });
            });
        }

        /**
         * 一键重新诊断
         */
        async reDiagnose() {
            const history = this.getDiagnosisHistory();
            if (history.length > 0) {
                const lastResult = history[0];
                if (lastResult.context) {
                    this.saveContext(lastResult.context);
                }
            }
            await this.startDiagnosis();
        }

        /**
         * 查看诊断历史
         */
        viewDiagnosisHistory() {
            const history = this.getDiagnosisHistory();
            this.dispatchEvent(CONFIG.EVENTS.DIAGNOSIS_HISTORY, { history });
            
            // 可以在这里实现历史记录弹窗
            if (history.length === 0) {
                showError('暂无诊断历史');
                return;
            }
            
            // 创建历史记录弹窗
            const overlay = document.createElement('div');
            overlay.className = 'diagnosis-history-overlay';
            overlay.innerHTML = `
                <div class="diagnosis-history-modal">
                    <div class="modal-header">
                        <h3>诊断历史</h3>
                        <button class="modal-close-btn" aria-label="关闭">&times;</button>
                    </div>
                    <div class="modal-body">
                        ${history.map((item, index) => `
                            <div class="history-item" data-index="${index}">
                                <div class="history-query">${item.context?.query || '无查询'}</div>
                                <div class="history-time">${new Date(item.savedAt).toLocaleString()}</div>
                                <button class="btn btn-sm btn-outline view-result-btn">查看结果</button>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
            
            document.body.appendChild(overlay);
            
            // 绑定事件
            const closeBtn = overlay.querySelector('.modal-close-btn');
            closeBtn.addEventListener('click', () => overlay.remove());
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) overlay.remove();
            });
            
            // 绑定查看结果按钮
            overlay.querySelectorAll('.view-result-btn').forEach((btn, index) => {
                btn.addEventListener('click', () => {
                    const result = history[index];
                    if (result) {
                        this.dispatchEvent(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, result);
                        // 可以在这里显示结果详情
                    }
                });
            });
        }
    }

    // ============================================================
    // 初始化
    // ============================================================

    // 等待DOM加载完成
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.diagnosisBridge = new DiagnosisBridge();
        });
    } else {
        window.diagnosisBridge = new DiagnosisBridge();
    }

    // 导出模块
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = DiagnosisBridge;
    }

})();