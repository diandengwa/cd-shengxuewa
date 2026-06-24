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
        const loadingEl = document.createElement('div');
        loadingEl.className = 'diagnosis-loading-overlay';
        loadingEl.innerHTML = `
            <div class="diagnosis-loading-spinner">
                <div class="spinner"></div>
                <p>${message}</p>
            </div>
        `;
        document.body.appendChild(loadingEl);
    }

    /**
     * 隐藏加载状态
     */
    function hideLoading() {
        const loadingEl = document.querySelector('.diagnosis-loading-overlay');
        if (loadingEl) {
            loadingEl.remove();
        }
    }

    /**
     * 显示错误提示
     * @param {string} message - 错误信息
     */
    function showError(message) {
        const errorEl = document.createElement('div');
        errorEl.className = 'diagnosis-error-toast';
        errorEl.textContent = message;
        document.body.appendChild(errorEl);
        setTimeout(() => {
            if (errorEl.parentNode) {
                errorEl.remove();
            }
        }, 5000);
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
            this.currentContext = null;
            this.creditsBalance = 0;
            this.pendingDiagnosis = null;
        }

        /**
         * 初始化桥接器
         */
        init() {
            if (this.initialized) return;
            this.initialized = true;

            // 加载已保存的上下文
            this.loadContext();

            // 根据当前页面执行相应初始化
            if (isOnDiagnosisPage()) {
                this.initDiagnosisPage();
            } else if (isOnQueryPage()) {
                this.initQueryPage();
            }

            // 监听自定义事件
            this.bindEvents();

            console.log('[diagnosis_bridge] 初始化完成');
        }

        /**
         * 加载保存的上下文
         */
        loadContext() {
            const saved = localStorage.getItem(CONFIG.STORAGE_KEY);
            if (saved) {
                const context = safeParseJSON(saved);
                if (context && !isContextExpired(context)) {
                    this.currentContext = context;
                    console.log('[diagnosis_bridge] 已加载上下文:', context);
                } else {
                    // 上下文已过期，清除
                    localStorage.removeItem(CONFIG.STORAGE_KEY);
                    console.log('[diagnosis_bridge] 上下文已过期，已清除');
                }
            }
        }

        /**
         * 保存上下文到本地存储
         * @param {Object} context - 上下文对象
         */
        saveContext(context) {
            if (!context) return;
            context.timestamp = Date.now();
            context.id = context.id || generateId();
            this.currentContext = context;
            try {
                localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(context));
                console.log('[diagnosis_bridge] 上下文已保存');
            } catch (e) {
                console.error('[diagnosis_bridge] 保存上下文失败:', e);
            }
        }

        /**
         * 清除上下文
         */
        clearContext() {
            this.currentContext = null;
            localStorage.removeItem(CONFIG.STORAGE_KEY);
            console.log('[diagnosis_bridge] 上下文已清除');
        }

        /**
         * 绑定事件监听
         */
        bindEvents() {
            // 监听诊断完成事件
            document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, (e) => {
                this.handleDiagnosisComplete(e.detail);
            });

            // 监听导航到诊断页面事件
            document.addEventListener(CONFIG.EVENTS.NAVIGATE_TO_DIAGNOSIS, (e) => {
                this.navigateToDiagnosis(e.detail);
            });

            // 监听查看历史记录事件
            document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_HISTORY, () => {
                this.showHistory();
            });

            // 监听积分检查事件
            document.addEventListener(CONFIG.EVENTS.CREDITS_CHECK, (e) => {
                this.checkCreditsAndDiagnose(e.detail);
            });

            // 监听政策引用点击事件
            document.addEventListener(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, (e) => {
                this.handlePolicyReferenceClick(e.detail);
            });
        }

        /**
         * 初始化诊断页面
         */
        initDiagnosisPage() {
            // 检查是否有待处理的上下文
            if (this.currentContext) {
                this.applyContextToDiagnosis(this.currentContext);
            }

            // 初始化诊断结果中的政策引用
            this.initPolicyReferences();
        }

        /**
         * 初始化查询页面
         */
        initQueryPage() {
            // 添加诊断引导按钮
            this.addGuideButton();
            
            // 添加诊断引导栏
            this.addGuideBar();
        }

        /**
         * 将上下文应用到诊断页面
         * @param {Object} context - 上下文对象
         */
        applyContextToDiagnosis(context) {
            if (!context) return;

            // 触发上下文就绪事件
            const event = new CustomEvent(CONFIG.EVENTS.CONTEXT_READY, {
                detail: context
            });
            document.dispatchEvent(event);

            // 填充诊断表单
            const form = document.getElementById('diagnosis-form');
            if (form) {
                // 填充查询关键词
                const keywordInput = form.querySelector('[name="keyword"]');
                if (keywordInput && context.keyword) {
                    keywordInput.value = context.keyword;
                }

                // 填充查询结果
                const resultInput = form.querySelector('[name="query_result"]');
                if (resultInput && context.queryResult) {
                    resultInput.value = context.queryResult;
                }

                // 填充额外参数
                const extraInput = form.querySelector('[name="extra_params"]');
                if (extraInput && context.extraParams) {
                    extraInput.value = JSON.stringify(context.extraParams);
                }
            }

            // 显示上下文徽章
            this.showContextBadge(context);
        }

        /**
         * 显示上下文徽章
         * @param {Object} context - 上下文对象
         */
        showContextBadge(context) {
            const existingBadge = document.querySelector(`.${CONFIG.UI.CONTEXT_BADGE_CLASS}`);
            if (existingBadge) {
                existingBadge.remove();
            }

            const badge = document.createElement('div');
            badge.className = CONFIG.UI.CONTEXT_BADGE_CLASS;
            badge.innerHTML = `
                <span class="badge-icon">📋</span>
                <span class="badge-text">已带入查询: "${context.keyword || '未知'}"</span>
                <button class="badge-clear" title="清除上下文">×</button>
            `;

            // 清除按钮事件
            badge.querySelector('.badge-clear').addEventListener('click', () => {
                this.clearContext();
                badge.remove();
            });

            // 插入到页面顶部
            const container = document.querySelector('.diagnosis-container') || document.body;
            container.insertBefore(badge, container.firstChild);
        }

        /**
         * 添加诊断引导按钮（查询结果页底部）
         */
        addGuideButton() {
            const existingBtn = document.querySelector(`.${CONFIG.UI.GUIDE_BUTTON_CLASS}`);
            if (existingBtn) return;

            const btn = document.createElement('button');
            btn.className = CONFIG.UI.GUIDE_BUTTON_CLASS;
            btn.innerHTML = '🔍 获取专业诊断';
            btn.title = '基于当前查询结果进行AI诊断分析';

            btn.addEventListener('click', () => {
                this.prepareDiagnosis();
            });

            // 添加到页面底部
            const container = document.querySelector('.query-results-container') || document.body;
            container.appendChild(btn);
        }

        /**
         * 添加诊断引导栏（查询结果页顶部）
         */
        addGuideBar() {
            const existingBar = document.querySelector(`.${CONFIG.UI.GUIDE_BAR_CLASS}`);
            if (existingBar) return;

            const bar = document.createElement('div');
            bar.className = CONFIG.UI.GUIDE_BAR_CLASS;
            bar.innerHTML = `
                <div class="guide-bar-content">
                    <span class="guide-bar-icon">💡</span>
                    <span class="guide-bar-text">想要更精准的升学建议？试试AI诊断分析</span>
                    <button class="guide-bar-action">立即诊断</button>
                </div>
            `;

            bar.querySelector('.guide-bar-action').addEventListener('click', () => {
                this.prepareDiagnosis();
            });

            // 插入到查询结果上方
            const container = document.querySelector('.query-results-container');
            if (container) {
                container.insertBefore(bar, container.firstChild);
            }
        }

        /**
         * 准备诊断（捕获当前查询上下文）
         */
        prepareDiagnosis() {
            // 捕获当前查询上下文
            const context = this.captureQueryContext();
            if (!context) {
                showError('无法获取查询上下文，请重新查询');
                return;
            }

            // 保存上下文
            this.saveContext(context);

            // 检查积分并弹出确认弹窗
            this.showDiagnosisConfirm(context);
        }

        /**
         * 捕获当前查询上下文
         * @returns {Object|null} 上下文对象
         */
        captureQueryContext() {
            try {
                // 从页面元素获取查询信息
                const keywordEl = document.querySelector('.search-keyword, .query-keyword');
                const resultEl = document.querySelector('.query-result-content, .search-result');

                const context = {
                    keyword: keywordEl ? keywordEl.textContent.trim() : '',
                    queryResult: resultEl ? resultEl.textContent.trim() : '',
                    url: window.location.href,
                    timestamp: Date.now(),
                    extraParams: {}
                };

                // 捕获额外参数（如区域、年级等）
                const extraParams = {};
                const gradeEl = document.querySelector('[data-grade]');
                const regionEl = document.querySelector('[data-region]');
                if (gradeEl) extraParams.grade = gradeEl.dataset.grade;
                if (regionEl) extraParams.region = regionEl.dataset.region;
                context.extraParams = extraParams;

                return context.keyword ? context : null;
            } catch (e) {
                console.error('[diagnosis_bridge] 捕获上下文失败:', e);
                return null;
            }
        }

        /**
         * 显示诊断确认弹窗（含积分检查）
         * @param {Object} context - 上下文对象
         */
        async showDiagnosisConfirm(context) {
            // 先检查积分
            try {
                const creditsData = await this.checkCredits();
                if (creditsData === null) {
                    // 未登录或API错误
                    this.showPaymentGuide('请先登录后再进行诊断');
                    return;
                }

                if (creditsData.credits < CONFIG.PAYMENT.MIN_CREDITS_REQUIRED) {
                    // 积分不足，显示付费引导
                    this.showPaymentGuide('诊断次数不足，请充值后再使用');
                    return;
                }

                // 积分充足，显示确认弹窗
                this.showConfirmModal(context, creditsData);
            } catch (e) {
                console.error('[diagnosis_bridge] 积分检查失败:', e);
                showError('积分检查失败，请稍后重试');
            }
        }

        /**
         * 检查用户积分
         * @returns {Promise<Object|null>} 积分数据
         */
        async checkCredits() {
            try {
                const response = await fetch(CONFIG.API.CHECK_CREDITS, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    credentials: 'same-origin'
                });

                if (!response.ok) {
                    if (response.status === 401) {
                        // 未登录
                        return null;
                    }
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                this.creditsBalance = data.credits || 0;
                return data;
            } catch (e) {
                console.error('[diagnosis_bridge] 积分检查API调用失败:', e);
                return null;
            }
        }

        /**
         * 显示确认弹窗
         * @param {Object} context - 上下文对象
         * @param {Object} creditsData - 积分数据
         */
        showConfirmModal(context, creditsData) {
            // 移除已存在的弹窗
            this.removeConfirmModal();

            const overlay = document.createElement('div');
            overlay.className = CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS;
            
            const modal = document.createElement('div');
            modal.className = CONFIG.UI.CONFIRM_MODAL_CLASS;
            modal.innerHTML = `
                <div class="modal-header">
                    <h3>确认诊断</h3>
                    <button class="modal-close" title="关闭">×</button>
                </div>
                <div class="modal-body">
                    <div class="modal-info">
                        <p>将基于以下内容进行AI诊断分析：</p>
                        <div class="modal-context-preview">
                            <strong>查询关键词：</strong>
                            <span>${context.keyword}</span>
                        </div>
                    </div>
                    <div class="modal-credits-info">
                        <span class="credits-label">本次诊断消耗：</span>
                        <span class="credits-cost">${CONFIG.PAYMENT.MIN_CREDITS_REQUIRED} 次</span>
                        <span class="credits-balance">（当前余额：${creditsData.credits} 次）</span>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary modal-cancel">取消</button>
                    <button class="btn btn-primary modal-confirm">确认诊断</button>
                </div>
            `;

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // 绑定事件
            const closeBtn = modal.querySelector('.modal-close');
            const cancelBtn = modal.querySelector('.modal-cancel');
            const confirmBtn = modal.querySelector('.modal-confirm');

            const closeModal = () => {
                this.removeConfirmModal();
            };

            closeBtn.addEventListener('click', closeModal);
            cancelBtn.addEventListener('click', closeModal);
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    closeModal();
                }
            });

            confirmBtn.addEventListener('click', async () => {
                confirmBtn.disabled = true;
                confirmBtn.textContent = '处理中...';
                await this.consumeCreditsAndDiagnose(context);
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
         * 消耗积分并发起诊断
         * @param {Object} context - 上下文对象
         */
        async consumeCreditsAndDiagnose(context) {
            showLoading('正在消耗诊断次数...');

            try {
                // 调用消耗积分API
                const consumeResponse = await fetch(CONFIG.API.DIAGNOSIS_START, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        context: context,
                        credits_cost: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED
                    })
                });

                if (!consumeResponse.ok) {
                    const errorData = await consumeResponse.json().catch(() => ({}));
                    throw new Error(errorData.message || `HTTP ${consumeResponse.status}`);
                }

                const result = await consumeResponse.json();
                
                // 更新本地积分余额
                if (result.credits_remaining !== undefined) {
                    this.creditsBalance = result.credits_remaining;
                }

                // 移除确认弹窗
                this.removeConfirmModal();
                hideLoading();

                // 导航到诊断页面
                this.navigateToDiagnosis(context);

            } catch (e) {
                hideLoading();
                console.error('[diagnosis_bridge] 消耗积分失败:', e);
                showError(e.message || '诊断启动失败，请稍后重试');
                
                // 重新启用确认按钮
                const confirmBtn = document.querySelector(`.${CONFIG.UI.CONFIRM_MODAL_CLASS} .modal-confirm`);
                if (confirmBtn) {
                    confirmBtn.disabled = false;
                    confirmBtn.textContent = '确认诊断';
                }
            }
        }

        /**
         * 检查积分并发起诊断（外部事件触发）
         * @param {Object} detail - 事件详情
         */
        async checkCreditsAndDiagnose(detail) {
            const context = detail && detail.context ? detail.context : this.currentContext;
            if (!context) {
                showError('没有可用的诊断上下文');
                return;
            }

            await this.showDiagnosisConfirm(context);
        }

        /**
         * 显示付费引导
         * @param {string} message - 提示信息
         */
        showPaymentGuide(message) {
            // 触发积分不足事件
            const event = new CustomEvent(CONFIG.EVENTS.CREDITS_INSUFFICIENT, {
                detail: {
                    message: message,
                    creditsRequired: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED,
                    currentCredits: this.creditsBalance
                }
            });
            document.dispatchEvent(event);

            // 触发付费引导事件
            const paymentEvent = new CustomEvent(CONFIG.EVENTS.PAYMENT_GUIDE, {
                detail: {
                    message: message,
                    price: CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS,
                    packageUrl: CONFIG.PAYMENT.PACKAGE_URL,
                    rechargeUrl: CONFIG.PAYMENT.RECHARGE_URL
                }
            });
            document.dispatchEvent(paymentEvent);

            // 显示付费引导弹窗
            this.showPaymentModal(message);
        }

        /**
         * 显示付费引导弹窗
         * @param {string} message - 提示信息
         */
        showPaymentModal(message) {
            // 移除已存在的付费引导弹窗
            const existingModal = document.querySelector('.payment-guide-modal');
            if (existingModal) {
                existingModal.remove();
            }

            const modal = document.createElement('div');
            modal.className = 'payment-guide-modal';
            modal.innerHTML = `
                <div class="payment-guide-overlay"></div>
                <div class="payment-guide-content">
                    <div class="payment-guide-header">
                        <h3>诊断次数不足</h3>
                        <button class="payment-guide-close">×</button>
                    </div>
                    <div class="payment-guide-body">
                        <div class="payment-guide-icon">⚠️</div>
                        <p class="payment-guide-message">${message}</p>
                        <div class="payment-guide-details">
                            <p>每次诊断消耗 <strong>${CONFIG.PAYMENT.MIN_CREDITS_REQUIRED}</strong> 次诊断机会</p>
                            <p>单次诊断价格：<strong>¥${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS}</strong></p>
                        </div>
                    </div>
                    <div class="payment-guide-footer">
                        <button class="btn btn-secondary payment-guide-cancel">稍后再说</button>
                        <button class="btn btn-primary payment-guide-recharge">去充值</button>
                        <button class="btn btn-primary payment-guide-packages">查看套餐</button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            // 绑定事件
            const closeBtn = modal.querySelector('.payment-guide-close');
            const cancelBtn = modal.querySelector('.payment-guide-cancel');
            const rechargeBtn = modal.querySelector('.payment-guide-recharge');
            const packagesBtn = modal.querySelector('.payment-guide-packages');
            const overlay = modal.querySelector('.payment-guide-overlay');

            const closeModal = () => {
                modal.remove();
            };

            closeBtn.addEventListener('click', closeModal);
            cancelBtn.addEventListener('click', closeModal);
            overlay.addEventListener('click', closeModal);

            rechargeBtn.addEventListener('click', () => {
                window.location.href = CONFIG.PAYMENT.RECHARGE_URL;
            });

            packagesBtn.addEventListener('click', () => {
                window.location.href = CONFIG.PAYMENT.PACKAGE_URL;
            });
        }

        /**
         * 导航到诊断页面
         * @param {Object} context - 上下文对象
         */
        navigateToDiagnosis(context) {
            if (!context) {
                context = this.currentContext;
            }

            if (!context) {
                showError('没有可用的诊断上下文');
                return;
            }

            // 保存上下文
            this.saveContext(context);

            // 导航到诊断页面
            const targetUrl = `${CONFIG.DIAGNOSIS_PATH}?context=${encodeURIComponent(JSON.stringify(context))}`;
            window.location.href = targetUrl;
        }

        /**
         * 处理诊断完成
         * @param {Object} detail - 诊断结果详情
         */
        handleDiagnosisComplete(detail) {
            if (!detail || !detail.result) return;

            // 保存诊断结果到历史记录
            this.saveDiagnosisResult(detail);

            // 如果在查询页面，回写诊断结果
            if (isOnQueryPage()) {
                this.writeDiagnosisResult(detail.result);
            }

            // 触发诊断完成事件
            const event = new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, {
                detail: detail
            });
            document.dispatchEvent(event);
        }

        /**
         * 保存诊断结果到历史记录
         * @param {Object} detail - 诊断结果详情
         */
        saveDiagnosisResult(detail) {
            try {
                const history = this.getDiagnosisHistory();
                const record = {
                    id: generateId(),
                    timestamp: Date.now(),
                    context: detail.context || this.currentContext,
                    result: detail.result,
                    summary: detail.summary || ''
                };

                history.unshift(record);

                // 限制历史记录数量
                if (history.length > CONFIG.MAX_HISTORY) {
                    history.length = CONFIG.MAX_HISTORY;
                }

                localStorage.setItem(CONFIG.RESULT_STORAGE_KEY, JSON.stringify(history));
                console.log('[diagnosis_bridge] 诊断结果已保存到历史记录');
            } catch (e) {
                console.error('[diagnosis_bridge] 保存诊断结果失败:', e);
            }
        }

        /**
         * 获取诊断历史记录
         * @returns {Array} 历史记录数组
         */
        getDiagnosisHistory() {
            const saved = localStorage.getItem(CONFIG.RESULT_STORAGE_KEY);
            return safeParseJSON(saved, []);
        }

        /**
         * 显示诊断历史记录
         */
        showHistory() {
            const history = this.getDiagnosisHistory();
            if (history.length === 0) {
                showError('暂无诊断历史记录');
                return;
            }

            // 触发历史记录事件，由页面处理显示
            const event = new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_HISTORY, {
                detail: {
                    history: history
                }
            });
            document.dispatchEvent(event);
        }

        /**
         * 回写诊断结果到查询页面
         * @param {Object} result - 诊断结果
         */
        writeDiagnosisResult(result) {
            if (!result) return;

            // 查找诊断结果容器
            const container = document.querySelector('.diagnosis-result-container, .query-result-diagnosis');
            if (!container) return;

            // 更新诊断结果内容
            const contentEl = container.querySelector('.diagnosis-content');
            if (contentEl) {
                contentEl.innerHTML = result.content || result.text || '';
            }

            // 更新诊断摘要
            const summaryEl = container.querySelector('.diagnosis-summary');
            if (summaryEl && result.summary) {
                summaryEl.textContent = result.summary;
            }

            // 显示容器
            container.style.display = 'block';
        }

        /**
         * 初始化政策引用链接
         */
        initPolicyReferences() {
            const refs = document.querySelectorAll(`.${CONFIG.UI.POLICY_REFERENCE_CLASS}`);
            refs.forEach(ref => {
                ref.addEventListener('click', (e) => {
                    e.preventDefault();
                    const policyId = ref.dataset.policyId;
                    if (policyId) {
                        this.handlePolicyReferenceClick({ policyId: policyId });
                    }
                });
            });
        }

        /**
         * 处理政策引用点击
         * @param {Object} detail - 政策引用详情
         */
        async handlePolicyReferenceClick(detail) {
            if (!detail || !detail.policyId) return;

            try {
                showLoading('正在加载政策原文...');

                const response = await fetch(`${CONFIG.API.GET_POLICY}${detail.policyId}`, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    credentials: 'same-origin'
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                hideLoading();

                // 触发政策引用点击事件
                const event = new CustomEvent(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, {
                    detail: {
                        policyId: detail.policyId,
                        policyData: data
                    }
                });
                document.dispatchEvent(event);

                // 显示政策原文弹窗
                this.showPolicyModal(data);

            } catch (e) {
                hideLoading();
                console.error('[diagnosis_bridge] 获取政策原文失败:', e);
                showError('获取政策原文失败，请稍后重试');
            }
        }

        /**
         * 显示政策原文弹窗
         * @param {Object} policyData - 政策数据
         */
        showPolicyModal(policyData) {
            // 移除已存在的政策弹窗
            const existingModal = document.querySelector('.policy-reference-modal');
            if (existingModal) {
                existingModal.remove();
            }

            const modal = document.createElement('div');
            modal.className = 'policy-reference-modal';
            modal.innerHTML = `
                <div class="policy-reference-overlay"></div>
                <div class="policy-reference-content">
                    <div class="policy-reference-header">
                        <h3>${policyData.title || '政策原文'}</h3>
                        <button class="policy-reference-close">×</button>
                    </div>
                    <div class="policy-reference-body">
                        ${policyData.content || policyData.text || '暂无内容'}
                    </div>
                    <div class="policy-reference-footer">
                        <button class="btn btn-secondary policy-reference-close-btn">关闭</button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            // 绑定事件
            const closeBtns = modal.querySelectorAll('.policy-reference-close, .policy-reference-close-btn');
            const overlay = modal.querySelector('.policy-reference-overlay');

            const closeModal = () => {
                modal.remove();
            };

            closeBtns.forEach(btn => btn.addEventListener('click', closeModal));
            overlay.addEventListener('click', closeModal);
        }

        /**
         * 一键重新诊断
         * @param {Object} context - 上下文对象
         */
        reDiagnose(context) {
            if (!context) {
                context = this.currentContext;
            }

            if (!context) {
                showError('没有可用的诊断上下文');
                return;
            }

            // 清除旧上下文
            this.clearContext();

            // 保存新上下文
            this.saveContext(context);

            // 检查积分并诊断
            this.showDiagnosisConfirm(context);
        }

        /**
         * 获取当前积分余额
         * @returns {number} 积分余额
         */
        getCreditsBalance() {
            return this.creditsBalance;
        }

        /**
         * 刷新积分余额
         * @returns {Promise<number>} 积分余额
         */
        async refreshCreditsBalance() {
            try {
                const data = await this.checkCredits();
                return data ? data.credits : 0;
            } catch (e) {
                console.error('[diagnosis_bridge] 刷新积分余额失败:', e);
                return this.creditsBalance;
            }
        }
    }

    // ============================================================
    // 导出单例
    // ============================================================

    // 创建全局实例
    window.diagnosisBridge = new DiagnosisBridge();

    // DOM 加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.diagnosisBridge.init();
        });
    } else {
        window.diagnosisBridge.init();
    }

    // 导出模块（支持模块化加载）
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = DiagnosisBridge;
    }

})();