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
        let loadingEl = document.getElementById('diagnosis-loading');
        if (!loadingEl) {
            loadingEl = document.createElement('div');
            loadingEl.id = 'diagnosis-loading';
            loadingEl.className = 'diagnosis-loading-overlay';
            loadingEl.innerHTML = `
                <div class="diagnosis-loading-content">
                    <div class="diagnosis-loading-spinner"></div>
                    <p class="diagnosis-loading-text">${message}</p>
                </div>
            `;
            document.body.appendChild(loadingEl);
        } else {
            const textEl = loadingEl.querySelector('.diagnosis-loading-text');
            if (textEl) textEl.textContent = message;
            loadingEl.style.display = 'flex';
        }
    }

    /**
     * 隐藏加载状态
     */
    function hideLoading() {
        const loadingEl = document.getElementById('diagnosis-loading');
        if (loadingEl) {
            loadingEl.style.display = 'none';
        }
    }

    /**
     * 显示错误提示
     * @param {string} message - 错误信息
     * @param {number} duration - 显示时长（毫秒）
     */
    function showError(message, duration = 5000) {
        const errorEl = document.createElement('div');
        errorEl.className = 'diagnosis-error-toast';
        errorEl.textContent = message;
        document.body.appendChild(errorEl);
        
        setTimeout(() => {
            if (errorEl.parentNode) {
                errorEl.parentNode.removeChild(errorEl);
            }
        }, duration);
    }

    /**
     * 显示成功提示
     * @param {string} message - 成功信息
     * @param {number} duration - 显示时长（毫秒）
     */
    function showSuccess(message, duration = 3000) {
        const successEl = document.createElement('div');
        successEl.className = 'diagnosis-success-toast';
        successEl.textContent = message;
        document.body.appendChild(successEl);
        
        setTimeout(() => {
            if (successEl.parentNode) {
                successEl.parentNode.removeChild(successEl);
            }
        }, duration);
    }

    // ============================================================
    // 核心功能模块
    // ============================================================

    /**
     * DiagnosisBridge 主类
     */
    class DiagnosisBridge {
        constructor() {
            this.initialized = false;
            this.context = null;
            this.creditsBalance = 0;
            this.diagnosisHistory = [];
            this.currentDiagnosisId = null;
            
            // 绑定事件处理器
            this._bindEvents();
        }

        /**
         * 初始化桥接器
         */
        async init() {
            if (this.initialized) return;
            
            try {
                // 加载历史记录
                this._loadHistory();
                
                // 加载上下文
                this._loadContext();
                
                // 获取当前积分余额
                await this._fetchCreditsBalance();
                
                // 根据当前页面执行不同初始化
                if (isOnDiagnosisPage()) {
                    this._initDiagnosisPage();
                } else if (isOnQueryPage()) {
                    this._initQueryPage();
                }
                
                this.initialized = true;
                console.log('[diagnosis_bridge] 初始化完成');
            } catch (error) {
                console.error('[diagnosis_bridge] 初始化失败:', error);
                showError('诊断桥接器初始化失败，请刷新页面重试');
            }
        }

        /**
         * 绑定全局事件
         */
        _bindEvents() {
            // 监听诊断完成事件
            document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, (e) => {
                this._handleDiagnosisComplete(e.detail);
            });

            // 监听导航到诊断页面事件
            document.addEventListener(CONFIG.EVENTS.NAVIGATE_TO_DIAGNOSIS, (e) => {
                this._handleNavigateToDiagnosis(e.detail);
            });

            // 监听积分检查事件
            document.addEventListener(CONFIG.EVENTS.CREDITS_CHECK, (e) => {
                this._handleCreditsCheck(e.detail);
            });

            // 监听付费引导事件
            document.addEventListener(CONFIG.EVENTS.PAYMENT_GUIDE, () => {
                this._showPaymentGuide();
            });

            // 监听政策引用点击事件
            document.addEventListener(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, (e) => {
                this._handlePolicyReferenceClick(e.detail);
            });
        }

        /**
         * 加载上下文
         */
        _loadContext() {
            try {
                const stored = localStorage.getItem(CONFIG.STORAGE_KEY);
                if (stored) {
                    const context = safeParseJSON(stored);
                    if (context && !isContextExpired(context)) {
                        this.context = context;
                        console.log('[diagnosis_bridge] 上下文已加载:', context);
                    } else {
                        localStorage.removeItem(CONFIG.STORAGE_KEY);
                        console.log('[diagnosis_bridge] 上下文已过期，已清除');
                    }
                }
            } catch (error) {
                console.error('[diagnosis_bridge] 加载上下文失败:', error);
            }
        }

        /**
         * 保存上下文
         * @param {Object} context - 上下文对象
         */
        _saveContext(context) {
            try {
                context.timestamp = Date.now();
                localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(context));
                this.context = context;
                console.log('[diagnosis_bridge] 上下文已保存:', context);
            } catch (error) {
                console.error('[diagnosis_bridge] 保存上下文失败:', error);
            }
        }

        /**
         * 清除上下文
         */
        _clearContext() {
            try {
                localStorage.removeItem(CONFIG.STORAGE_KEY);
                this.context = null;
                console.log('[diagnosis_bridge] 上下文已清除');
            } catch (error) {
                console.error('[diagnosis_bridge] 清除上下文失败:', error);
            }
        }

        /**
         * 加载历史记录
         */
        _loadHistory() {
            try {
                const stored = localStorage.getItem(CONFIG.RESULT_STORAGE_KEY);
                if (stored) {
                    this.diagnosisHistory = safeParseJSON(stored, []);
                }
            } catch (error) {
                console.error('[diagnosis_bridge] 加载历史记录失败:', error);
                this.diagnosisHistory = [];
            }
        }

        /**
         * 保存历史记录
         */
        _saveHistory() {
            try {
                localStorage.setItem(CONFIG.RESULT_STORAGE_KEY, JSON.stringify(this.diagnosisHistory));
            } catch (error) {
                console.error('[diagnosis_bridge] 保存历史记录失败:', error);
            }
        }

        /**
         * 添加诊断历史记录
         * @param {Object} result - 诊断结果
         */
        _addHistory(result) {
            this.diagnosisHistory.unshift({
                id: result.id || generateId(),
                timestamp: Date.now(),
                context: result.context || this.context,
                summary: result.summary || '',
                creditsUsed: result.creditsUsed || 1
            });

            // 限制历史记录数量
            if (this.diagnosisHistory.length > CONFIG.MAX_HISTORY) {
                this.diagnosisHistory = this.diagnosisHistory.slice(0, CONFIG.MAX_HISTORY);
            }

            this._saveHistory();
        }

        /**
         * 获取积分余额
         */
        async _fetchCreditsBalance() {
            try {
                const response = await fetch(CONFIG.API.GET_CREDITS, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                if (!response.ok) {
                    throw new Error(`获取积分余额失败: ${response.status}`);
                }

                const data = await response.json();
                this.creditsBalance = data.balance || 0;
                console.log('[diagnosis_bridge] 当前积分余额:', this.creditsBalance);
                return this.creditsBalance;
            } catch (error) {
                console.error('[diagnosis_bridge] 获取积分余额失败:', error);
                this.creditsBalance = 0;
                return 0;
            }
        }

        /**
         * 检查积分是否足够
         * @returns {Promise<Object>} 检查结果
         */
        async checkCredits() {
            try {
                showLoading('正在检查积分...');
                
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
                    throw new Error(`积分检查失败: ${response.status}`);
                }

                const data = await response.json();
                
                // 更新本地积分余额
                this.creditsBalance = data.balance || 0;
                
                hideLoading();
                
                return {
                    sufficient: data.sufficient || false,
                    balance: this.creditsBalance,
                    required: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED,
                    price: CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS
                };
            } catch (error) {
                hideLoading();
                console.error('[diagnosis_bridge] 积分检查失败:', error);
                showError('积分检查失败，请稍后重试');
                return {
                    sufficient: false,
                    balance: 0,
                    required: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED,
                    price: CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS,
                    error: error.message
                };
            }
        }

        /**
         * 消耗积分并开始诊断
         * @param {Object} context - 诊断上下文
         * @returns {Promise<Object>} 诊断结果
         */
        async consumeCreditsAndStartDiagnosis(context) {
            try {
                showLoading('正在消耗积分并开始诊断...');
                
                const response = await fetch(CONFIG.API.DIAGNOSIS_START, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({
                        context: context,
                        creditsToConsume: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED
                    })
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `诊断启动失败: ${response.status}`);
                }

                const data = await response.json();
                
                // 更新本地积分余额
                this.creditsBalance = data.remainingCredits || 0;
                
                // 保存诊断ID
                this.currentDiagnosisId = data.diagnosisId;
                
                hideLoading();
                showSuccess('诊断已开始，请稍候...');
                
                return data;
            } catch (error) {
                hideLoading();
                console.error('[diagnosis_bridge] 诊断启动失败:', error);
                showError(error.message || '诊断启动失败，请稍后重试');
                throw error;
            }
        }

        /**
         * 显示确认弹窗
         * @param {Object} creditsInfo - 积分信息
         * @returns {Promise<boolean>} 用户是否确认
         */
        _showConfirmModal(creditsInfo) {
            return new Promise((resolve) => {
                // 移除已存在的弹窗
                const existingModal = document.querySelector(`.${CONFIG.UI.CONFIRM_MODAL_CLASS}`);
                if (existingModal) {
                    existingModal.parentNode.removeChild(existingModal);
                }

                const modal = document.createElement('div');
                modal.className = CONFIG.UI.CONFIRM_MODAL_CLASS;
                modal.innerHTML = `
                    <div class="${CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS}"></div>
                    <div class="diagnosis-confirm-modal-content">
                        <div class="diagnosis-confirm-modal-header">
                            <h3>确认诊断</h3>
                            <button class="diagnosis-confirm-close" aria-label="关闭">&times;</button>
                        </div>
                        <div class="diagnosis-confirm-modal-body">
                            <div class="diagnosis-credits-info">
                                <div class="diagnosis-credits-icon">🔍</div>
                                <p class="diagnosis-credits-text">
                                    本次诊断将消耗 <strong>${creditsInfo.required}</strong> 次诊断次数
                                </p>
                                <p class="diagnosis-credits-balance">
                                    当前剩余次数：<strong>${creditsInfo.balance}</strong> 次
                                </p>
                                ${creditsInfo.balance < creditsInfo.required ? 
                                    `<p class="diagnosis-credits-warning">⚠️ 次数不足，请先购买诊断次数</p>` : 
                                    `<p class="diagnosis-credits-price">每次诊断仅需 ¥${creditsInfo.price}</p>`
                                }
                            </div>
                            ${this.context ? `
                                <div class="diagnosis-context-preview">
                                    <h4>诊断上下文预览</h4>
                                    <div class="diagnosis-context-detail">
                                        <p><strong>查询内容：</strong>${this.context.query || '未指定'}</p>
                                        ${this.context.policyId ? `<p><strong>政策ID：</strong>${this.context.policyId}</p>` : ''}
                                        ${this.context.grade ? `<p><strong>年级：</strong>${this.context.grade}</p>` : ''}
                                    </div>
                                </div>
                            ` : ''}
                        </div>
                        <div class="diagnosis-confirm-modal-footer">
                            <button class="diagnosis-btn diagnosis-btn-cancel">取消</button>
                            ${creditsInfo.balance >= creditsInfo.required ? 
                                `<button class="diagnosis-btn diagnosis-btn-confirm">确认诊断</button>` :
                                `<button class="diagnosis-btn diagnosis-btn-recharge">去购买次数</button>`
                            }
                        </div>
                    </div>
                `;

                document.body.appendChild(modal);

                // 绑定事件
                const closeBtn = modal.querySelector('.diagnosis-confirm-close');
                const cancelBtn = modal.querySelector('.diagnosis-btn-cancel');
                const confirmBtn = modal.querySelector('.diagnosis-btn-confirm');
                const rechargeBtn = modal.querySelector('.diagnosis-btn-recharge');
                const overlay = modal.querySelector(`.${CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS}`);

                const closeModal = () => {
                    if (modal.parentNode) {
                        modal.parentNode.removeChild(modal);
                    }
                };

                closeBtn.addEventListener('click', () => {
                    closeModal();
                    resolve(false);
                });

                cancelBtn.addEventListener('click', () => {
                    closeModal();
                    resolve(false);
                });

                overlay.addEventListener('click', () => {
                    closeModal();
                    resolve(false);
                });

                if (confirmBtn) {
                    confirmBtn.addEventListener('click', () => {
                        closeModal();
                        resolve(true);
                    });
                }

                if (rechargeBtn) {
                    rechargeBtn.addEventListener('click', () => {
                        closeModal();
                        this._showPaymentGuide();
                        resolve(false);
                    });
                }
            });
        }

        /**
         * 显示付费引导
         */
        _showPaymentGuide() {
            // 触发付费引导事件
            const event = new CustomEvent(CONFIG.EVENTS.PAYMENT_GUIDE, {
                detail: {
                    balance: this.creditsBalance,
                    required: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED,
                    price: CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS,
                    packageUrl: CONFIG.PAYMENT.PACKAGE_URL,
                    rechargeUrl: CONFIG.PAYMENT.RECHARGE_URL
                }
            });
            document.dispatchEvent(event);

            // 显示付费引导弹窗
            const modal = document.createElement('div');
            modal.className = 'diagnosis-payment-guide-modal';
            modal.innerHTML = `
                <div class="diagnosis-payment-guide-overlay"></div>
                <div class="diagnosis-payment-guide-content">
                    <div class="diagnosis-payment-guide-header">
                        <h3>诊断次数不足</h3>
                        <button class="diagnosis-payment-guide-close">&times;</button>
                    </div>
                    <div class="diagnosis-payment-guide-body">
                        <div class="diagnosis-payment-guide-icon">💡</div>
                        <p class="diagnosis-payment-guide-text">
                            当前剩余诊断次数：<strong>${this.creditsBalance}</strong> 次
                        </p>
                        <p class="diagnosis-payment-guide-text">
                            每次诊断仅需 <strong>¥${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS}</strong>
                        </p>
                        <div class="diagnosis-payment-guide-packages">
                            <div class="diagnosis-package-card">
                                <h4>单次诊断</h4>
                                <p class="diagnosis-package-price">¥${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS}</p>
                                <p class="diagnosis-package-desc">适合偶尔使用</p>
                                <button class="diagnosis-btn diagnosis-btn-buy" data-package="single">立即购买</button>
                            </div>
                            <div class="diagnosis-package-card diagnosis-package-recommended">
                                <div class="diagnosis-package-badge">推荐</div>
                                <h4>10次套餐</h4>
                                <p class="diagnosis-package-price">¥${(CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS * 8).toFixed(1)}</p>
                                <p class="diagnosis-package-desc">适合频繁使用，省${(CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS * 2).toFixed(1)}元</p>
                                <button class="diagnosis-btn diagnosis-btn-buy diagnosis-btn-primary" data-package="ten">立即购买</button>
                            </div>
                            <div class="diagnosis-package-card">
                                <h4>30次套餐</h4>
                                <p class="diagnosis-package-price">¥${(CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS * 21).toFixed(1)}</p>
                                <p class="diagnosis-package-desc">适合长期使用，省${(CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS * 9).toFixed(1)}元</p>
                                <button class="diagnosis-btn diagnosis-btn-buy" data-package="thirty">立即购买</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            // 绑定事件
            const closeBtn = modal.querySelector('.diagnosis-payment-guide-close');
            const overlay = modal.querySelector('.diagnosis-payment-guide-overlay');
            const buyBtns = modal.querySelectorAll('.diagnosis-btn-buy');

            const closeModal = () => {
                if (modal.parentNode) {
                    modal.parentNode.removeChild(modal);
                }
            };

            closeBtn.addEventListener('click', closeModal);
            overlay.addEventListener('click', closeModal);

            buyBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    const packageType = btn.dataset.package;
                    closeModal();
                    // 跳转到购买页面
                    window.location.href = `${CONFIG.PAYMENT.PACKAGE_URL}?package=${packageType}`;
                });
            });
        }

        /**
         * 处理诊断完成事件
         * @param {Object} detail - 诊断结果详情
         */
        _handleDiagnosisComplete(detail) {
            if (detail && detail.result) {
                // 添加到历史记录
                this._addHistory(detail.result);
                
                // 清除当前上下文
                this._clearContext();
                
                console.log('[diagnosis_bridge] 诊断完成:', detail.result);
            }
        }

        /**
         * 处理导航到诊断页面事件
         * @param {Object} detail - 导航详情
         */
        _handleNavigateToDiagnosis(detail) {
            if (detail && detail.context) {
                this._saveContext(detail.context);
            }
            
            // 执行导航
            if (detail && detail.url) {
                window.location.href = detail.url;
            } else {
                window.location.href = CONFIG.DIAGNOSIS_PATH;
            }
        }

        /**
         * 处理积分检查事件
         * @param {Object} detail - 检查详情
         */
        async _handleCreditsCheck(detail) {
            try {
                const creditsInfo = await this.checkCredits();
                
                if (creditsInfo.sufficient) {
                    // 积分足够，显示确认弹窗
                    const confirmed = await this._showConfirmModal(creditsInfo);
                    
                    if (confirmed) {
                        // 用户确认，消耗积分并开始诊断
                        await this.consumeCreditsAndStartDiagnosis(detail.context || this.context);
                    }
                } else {
                    // 积分不足，显示付费引导
                    this._showPaymentGuide();
                }
            } catch (error) {
                console.error('[diagnosis_bridge] 积分检查处理失败:', error);
                showError('积分检查处理失败，请稍后重试');
            }
        }

        /**
         * 处理政策引用点击事件
         * @param {Object} detail - 引用详情
         */
        async _handlePolicyReferenceClick(detail) {
            if (detail && detail.policyId) {
                try {
                    // 获取政策原文
                    const response = await fetch(`${CONFIG.API.GET_POLICY}${detail.policyId}`, {
                        method: 'GET',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });

                    if (!response.ok) {
                        throw new Error(`获取政策原文失败: ${response.status}`);
                    }

                    const policy = await response.json();
                    
                    // 触发政策查看事件
                    const event = new CustomEvent('policy:view', {
                        detail: {
                            policyId: detail.policyId,
                            policy: policy,
                            source: 'diagnosis'
                        }
                    });
                    document.dispatchEvent(event);
                    
                    // 跳转到政策详情页
                    window.location.href = `/policy/${detail.policyId}`;
                } catch (error) {
                    console.error('[diagnosis_bridge] 获取政策原文失败:', error);
                    showError('获取政策原文失败，请稍后重试');
                }
            }
        }

        /**
         * 初始化诊断页面
         */
        _initDiagnosisPage() {
            // 检查是否有上下文
            if (this.context) {
                // 显示上下文信息
                this._showContextBadge();
                
                // 自动触发积分检查
                const event = new CustomEvent(CONFIG.EVENTS.CREDITS_CHECK, {
                    detail: {
                        context: this.context
                    }
                });
                document.dispatchEvent(event);
            } else {
                // 没有上下文，显示提示
                console.log('[diagnosis_bridge] 诊断页面无上下文，等待用户输入');
            }
        }

        /**
         * 初始化查询页面
         */
        _initQueryPage() {
            // 添加引导按钮
            this._addGuideButton();
            
            // 检查是否有诊断结果需要回写
            this._checkForDiagnosisResults();
        }

        /**
         * 显示上下文徽章
         */
        _showContextBadge() {
            const badge = document.createElement('div');
            badge.className = CONFIG.UI.CONTEXT_BADGE_CLASS;
            badge.innerHTML = `
                <div class="diagnosis-context-badge-content">
                    <span class="diagnosis-context-badge-icon">📋</span>
                    <span class="diagnosis-context-badge-text">
                        已加载查询上下文：${this.context.query || '未指定'}
                    </span>
                    <button class="diagnosis-context-badge-clear" title="清除上下文">&times;</button>
                </div>
            `;

            // 插入到页面顶部
            const container = document.querySelector('.diagnosis-container') || document.body;
            container.insertBefore(badge, container.firstChild);

            // 绑定清除事件
            const clearBtn = badge.querySelector('.diagnosis-context-badge-clear');
            clearBtn.addEventListener('click', () => {
                this._clearContext();
                if (badge.parentNode) {
                    badge.parentNode.removeChild(badge);
                }
            });
        }

        /**
         * 添加引导按钮
         */
        _addGuideButton() {
            // 检查是否已存在
            if (document.querySelector(`.${CONFIG.UI.GUIDE_BUTTON_CLASS}`)) {
                return;
            }

            const guideBar = document.createElement('div');
            guideBar.className = CONFIG.UI.GUIDE_BAR_CLASS;
            guideBar.innerHTML = `
                <div class="diagnosis-guide-bar-content">
                    <p class="diagnosis-guide-bar-text">
                        💡 想要更精准的升学建议？试试智能诊断！
                    </p>
                    <button class="${CONFIG.UI.GUIDE_BUTTON_CLASS} diagnosis-btn diagnosis-btn-primary">
                        开始诊断
                    </button>
                </div>
            `;

            // 插入到查询结果底部
            const resultsContainer = document.querySelector('.query-results') || document.querySelector('.results-container');
            if (resultsContainer) {
                resultsContainer.appendChild(guideBar);
            } else {
                document.body.appendChild(guideBar);
            }

            // 绑定点击事件
            const guideBtn = guideBar.querySelector(`.${CONFIG.UI.GUIDE_BUTTON_CLASS}`);
            guideBtn.addEventListener('click', () => {
                this._handleGuideButtonClick();
            });
        }

        /**
         * 处理引导按钮点击
         */
        _handleGuideButtonClick() {
            // 获取当前查询上下文
            const queryContext = this._captureQueryContext();
            
            if (queryContext) {
                // 保存上下文
                this._saveContext(queryContext);
                
                // 触发积分检查
                const event = new CustomEvent(CONFIG.EVENTS.CREDITS_CHECK, {
                    detail: {
                        context: queryContext
                    }
                });
                document.dispatchEvent(event);
            } else {
                // 没有查询上下文，直接导航到诊断页面
                window.location.href = CONFIG.DIAGNOSIS_PATH;
            }
        }

        /**
         * 捕获查询上下文
         * @returns {Object|null} 查询上下文
         */
        _captureQueryContext() {
            try {
                // 尝试从页面元素获取查询信息
                const queryInput = document.querySelector('input[name="query"], input[type="search"], .search-input');
                const query = queryInput ? queryInput.value : '';
                
                // 尝试获取政策ID
                const policyId = new URLSearchParams(window.location.search).get('policy_id');
                
                // 尝试获取年级信息
                const gradeSelect = document.querySelector('select[name="grade"], .grade-select');
                const grade = gradeSelect ? gradeSelect.value : '';
                
                if (!query && !policyId) {
                    return null;
                }
                
                return {
                    query: query,
                    policyId: policyId,
                    grade: grade,
                    url: window.location.href,
                    timestamp: Date.now()
                };
            } catch (error) {
                console.error('[diagnosis_bridge] 捕获查询上下文失败:', error);
                return null;
            }
        }

        /**
         * 检查是否有诊断结果需要回写
         */
        _checkForDiagnosisResults() {
            // 检查URL参数是否有诊断结果ID
            const resultId = new URLSearchParams(window.location.search).get('diagnosis_result');
            if (resultId) {
                // 查找历史记录中的诊断结果
                const result = this.diagnosisHistory.find(h => h.id === resultId);
                if (result) {
                    // 显示诊断结果提示
                    showSuccess('诊断结果已加载，请查看');
                    
                    // 触发诊断结果回写事件
                    const event = new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, {
                        detail: {
                            result: result,
                            fromHistory: true
                        }
                    });
                    document.dispatchEvent(event);
                }
            }
        }

        /**
         * 获取诊断历史
         * @returns {Array} 诊断历史列表
         */
        getDiagnosisHistory() {
            return [...this.diagnosisHistory];
        }

        /**
         * 清除所有数据
         */
        clearAllData() {
            this._clearContext();
            this.diagnosisHistory = [];
            this._saveHistory();
            this.creditsBalance = 0;
            console.log('[diagnosis_bridge] 所有数据已清除');
        }
    }

    // ============================================================
    // 导出模块
    // ============================================================

    // 创建全局实例
    const diagnosisBridge = new DiagnosisBridge();

    // 暴露到全局
    window.DiagnosisBridge = diagnosisBridge;

    // DOM加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            diagnosisBridge.init();
        });
    } else {
        diagnosisBridge.init();
    }

    // 导出模块（支持CommonJS和ES Module）
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = DiagnosisBridge;
    }
    if (typeof define === 'function' && define.amd) {
        define([], () => DiagnosisBridge);
    }

})();