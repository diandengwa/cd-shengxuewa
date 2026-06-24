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
     * @returns {HTMLElement} 加载元素
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
        return overlay;
    }

    /**
     * 隐藏加载状态
     * @param {HTMLElement} overlay - 加载元素
     */
    function hideLoading(overlay) {
        if (overlay && overlay.parentNode) {
            overlay.parentNode.removeChild(overlay);
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
            if (errorDiv.parentNode) {
                errorDiv.parentNode.removeChild(errorDiv);
            }
        }, 3000);
    }

    // ============================================================
    // 核心类：诊断桥接器
    // ============================================================

    class DiagnosisBridge {
        constructor() {
            this.context = null;
            this.initialized = false;
            this.confirmModal = null;
            this.currentDiagnosisCallback = null;
        }

        /**
         * 初始化桥接器
         */
        init() {
            if (this.initialized) return;
            this.initialized = true;

            // 加载已保存的上下文
            this.loadContext();

            // 根据当前页面执行不同初始化逻辑
            if (isOnDiagnosisPage()) {
                this.initDiagnosisPage();
            } else if (isOnQueryPage()) {
                this.initQueryPage();
            }

            // 监听自定义事件
            this.listenEvents();

            console.log('[diagnosis_bridge] 初始化完成');
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
                    console.log('[diagnosis_bridge] 已加载上下文:', this.context);
                } else {
                    // 上下文过期，清除
                    localStorage.removeItem(CONFIG.STORAGE_KEY);
                    console.log('[diagnosis_bridge] 上下文已过期，已清除');
                }
            }
        }

        /**
         * 保存上下文到 localStorage
         * @param {Object} context - 上下文对象
         */
        saveContext(context) {
            context.timestamp = Date.now();
            this.context = context;
            localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(context));
            console.log('[diagnosis_bridge] 上下文已保存');
        }

        /**
         * 清除上下文
         */
        clearContext() {
            this.context = null;
            localStorage.removeItem(CONFIG.STORAGE_KEY);
            console.log('[diagnosis_bridge] 上下文已清除');
        }

        /**
         * 初始化诊断页面
         */
        initDiagnosisPage() {
            // 如果有上下文，自动填充诊断表单
            if (this.context) {
                this.fillDiagnosisForm(this.context);
            }
            // 初始化诊断结果中的政策引用点击
            this.initPolicyReferences();
        }

        /**
         * 初始化查询页面
         */
        initQueryPage() {
            // 添加诊断引导按钮
            this.addGuideButton();
            // 添加诊断引导条
            this.addGuideBar();
        }

        /**
         * 监听自定义事件
         */
        listenEvents() {
            document.addEventListener(CONFIG.EVENTS.NAVIGATE_TO_DIAGNOSIS, (e) => {
                if (e.detail) {
                    this.saveContext(e.detail);
                }
                this.navigateToDiagnosis();
            });

            document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, (e) => {
                if (e.detail) {
                    this.saveDiagnosisResult(e.detail);
                }
            });

            document.addEventListener(CONFIG.EVENTS.CREDITS_CHECK, () => {
                this.checkCreditsAndDiagnose();
            });

            document.addEventListener(CONFIG.EVENTS.PAYMENT_GUIDE, () => {
                this.showPaymentGuide();
            });

            document.addEventListener(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, (e) => {
                if (e.detail && e.detail.policyId) {
                    this.navigateToPolicy(e.detail.policyId);
                }
            });
        }

        /**
         * 填充诊断表单
         * @param {Object} context - 上下文数据
         */
        fillDiagnosisForm(context) {
            // 查找表单元素并填充
            const form = document.getElementById('diagnosis-form');
            if (!form) return;

            // 填充学生信息
            if (context.studentName) {
                const nameInput = form.querySelector('[name="student_name"]');
                if (nameInput) nameInput.value = context.studentName;
            }

            if (context.grade) {
                const gradeInput = form.querySelector('[name="grade"]');
                if (gradeInput) gradeInput.value = context.grade;
            }

            if (context.queryText) {
                const queryInput = form.querySelector('[name="query_text"]');
                if (queryInput) queryInput.value = context.queryText;
            }

            // 显示上下文徽章
            this.showContextBadge(context);
        }

        /**
         * 显示上下文徽章
         * @param {Object} context - 上下文数据
         */
        showContextBadge(context) {
            const badgeContainer = document.getElementById('context-badge-container');
            if (!badgeContainer) return;

            const badge = document.createElement('div');
            badge.className = CONFIG.UI.CONTEXT_BADGE_CLASS;
            badge.innerHTML = `
                <span class="badge-icon">📋</span>
                <span class="badge-text">已带入查询上下文: "${context.queryText || '未指定'}"</span>
                <button class="badge-clear" onclick="window.diagnosisBridge.clearContext()">×</button>
            `;
            badgeContainer.appendChild(badge);
        }

        /**
         * 初始化政策引用点击
         */
        initPolicyReferences() {
            document.querySelectorAll(`.${CONFIG.UI.POLICY_REFERENCE_CLASS}`).forEach(el => {
                el.addEventListener('click', (e) => {
                    e.preventDefault();
                    const policyId = el.getAttribute('data-policy-id');
                    if (policyId) {
                        this.navigateToPolicy(policyId);
                    }
                });
            });
        }

        /**
         * 添加诊断引导按钮
         */
        addGuideButton() {
            const existingBtn = document.querySelector(`.${CONFIG.UI.GUIDE_BUTTON_CLASS}`);
            if (existingBtn) return;

            const btn = document.createElement('button');
            btn.className = CONFIG.UI.GUIDE_BUTTON_CLASS;
            btn.innerHTML = '🔍 开始诊断分析';
            btn.addEventListener('click', () => {
                this.collectQueryContext();
            });
            document.body.appendChild(btn);
        }

        /**
         * 添加诊断引导条
         */
        addGuideBar() {
            const existingBar = document.querySelector(`.${CONFIG.UI.GUIDE_BAR_CLASS}`);
            if (existingBar) return;

            const bar = document.createElement('div');
            bar.className = CONFIG.UI.GUIDE_BAR_CLASS;
            bar.innerHTML = `
                <div class="guide-bar-content">
                    <span class="guide-bar-icon">💡</span>
                    <span class="guide-bar-text">需要更精准的升学建议？试试智能诊断分析</span>
                    <button class="guide-bar-action">立即诊断</button>
                </div>
            `;
            bar.querySelector('.guide-bar-action').addEventListener('click', () => {
                this.collectQueryContext();
            });
            document.body.appendChild(bar);
        }

        /**
         * 收集查询上下文
         */
        collectQueryContext() {
            // 从当前页面收集查询上下文
            const context = {
                id: generateId(),
                timestamp: Date.now(),
                source: getCurrentPath(),
                queryText: this.getQueryText(),
                studentName: this.getStudentName(),
                grade: this.getGrade(),
                school: this.getSchool(),
                additionalInfo: this.getAdditionalInfo()
            };

            // 保存上下文并导航到诊断页面
            this.saveContext(context);
            this.navigateToDiagnosis();
        }

        /**
         * 获取查询文本
         * @returns {string}
         */
        getQueryText() {
            const queryInput = document.querySelector('[name="query"]') || 
                              document.querySelector('[name="search"]') ||
                              document.querySelector('.search-input');
            return queryInput ? queryInput.value : '';
        }

        /**
         * 获取学生姓名
         * @returns {string}
         */
        getStudentName() {
            const nameInput = document.querySelector('[name="student_name"]');
            return nameInput ? nameInput.value : '';
        }

        /**
         * 获取年级
         * @returns {string}
         */
        getGrade() {
            const gradeSelect = document.querySelector('[name="grade"]');
            return gradeSelect ? gradeSelect.value : '';
        }

        /**
         * 获取学校
         * @returns {string}
         */
        getSchool() {
            const schoolInput = document.querySelector('[name="school"]');
            return schoolInput ? schoolInput.value : '';
        }

        /**
         * 获取额外信息
         * @returns {Object}
         */
        getAdditionalInfo() {
            const info = {};
            const additionalInputs = document.querySelectorAll('[data-additional]');
            additionalInputs.forEach(input => {
                info[input.name] = input.value;
            });
            return info;
        }

        /**
         * 导航到诊断页面
         */
        navigateToDiagnosis() {
            window.location.href = CONFIG.DIAGNOSIS_PATH;
        }

        /**
         * 保存诊断结果
         * @param {Object} result - 诊断结果
         */
        saveDiagnosisResult(result) {
            const results = this.getDiagnosisHistory();
            results.unshift({
                id: generateId(),
                timestamp: Date.now(),
                ...result
            });

            // 限制历史记录数量
            if (results.length > CONFIG.MAX_HISTORY) {
                results.length = CONFIG.MAX_HISTORY;
            }

            localStorage.setItem(CONFIG.RESULT_STORAGE_KEY, JSON.stringify(results));
            
            // 触发诊断完成事件
            document.dispatchEvent(new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, {
                detail: result
            }));
        }

        /**
         * 获取诊断历史
         * @returns {Array}
         */
        getDiagnosisHistory() {
            const stored = localStorage.getItem(CONFIG.RESULT_STORAGE_KEY);
            return safeParseJSON(stored, []);
        }

        /**
         * 导航到政策详情页
         * @param {string} policyId - 政策ID
         */
        navigateToPolicy(policyId) {
            window.location.href = `${CONFIG.API.GET_POLICY}${policyId}`;
        }

        // ============================================================
        // 诊断前确认逻辑（Issue #26）
        // ============================================================

        /**
         * 检查诊断次数并发起诊断
         * @param {Function} callback - 诊断发起回调函数
         */
        checkCreditsAndDiagnose(callback) {
            this.currentDiagnosisCallback = callback;

            // 显示加载状态
            const loading = showLoading('检查诊断次数...');

            // 调用检查次数接口
            fetch(CONFIG.API.CHECK_CREDITS, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('网络请求失败');
                }
                return response.json();
            })
            .then(data => {
                hideLoading(loading);

                if (data.success) {
                    const { credits, required } = data.data;
                    
                    if (credits >= required) {
                        // 有足够次数，显示确认弹窗
                        this.showConfirmModal(credits, required);
                    } else {
                        // 次数不足，显示付费引导
                        this.showInsufficientCredits(credits, required);
                    }
                } else {
                    showError(data.message || '检查诊断次数失败');
                }
            })
            .catch(error => {
                hideLoading(loading);
                console.error('[diagnosis_bridge] 检查诊断次数失败:', error);
                showError('检查诊断次数失败，请稍后重试');
            });
        }

        /**
         * 显示诊断确认弹窗
         * @param {number} credits - 当前剩余次数
         * @param {number} required - 所需次数
         */
        showConfirmModal(credits, required) {
            // 移除已有弹窗
            this.removeConfirmModal();

            // 创建遮罩层
            const overlay = document.createElement('div');
            overlay.className = CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS;
            
            // 创建弹窗
            const modal = document.createElement('div');
            modal.className = CONFIG.UI.CONFIRM_MODAL_CLASS;
            modal.innerHTML = `
                <div class="confirm-modal-header">
                    <h3>确认诊断</h3>
                    <button class="confirm-modal-close">&times;</button>
                </div>
                <div class="confirm-modal-body">
                    <div class="credits-info">
                        <span class="credits-icon">⚡</span>
                        <span class="credits-text">当前剩余诊断次数：<strong>${credits}</strong> 次</span>
                    </div>
                    <div class="cost-info">
                        <span class="cost-icon">💰</span>
                        <span class="cost-text">本次诊断将消耗 <strong>${required}</strong> 次诊断机会</span>
                    </div>
                    <div class="confirm-message">
                        <p>确认开始诊断分析？诊断结果将帮助您更好地了解升学路径。</p>
                    </div>
                </div>
                <div class="confirm-modal-footer">
                    <button class="btn btn-secondary confirm-cancel">取消</button>
                    <button class="btn btn-primary confirm-start">开始诊断</button>
                </div>
            `;

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // 保存弹窗引用
            this.confirmModal = {
                overlay: overlay,
                modal: modal
            };

            // 绑定事件
            const closeBtn = modal.querySelector('.confirm-modal-close');
            const cancelBtn = modal.querySelector('.confirm-cancel');
            const startBtn = modal.querySelector('.confirm-start');

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

            // 开始诊断
            startBtn.addEventListener('click', () => {
                closeModal();
                this.startDiagnosis();
            });
        }

        /**
         * 移除确认弹窗
         */
        removeConfirmModal() {
            if (this.confirmModal) {
                if (this.confirmModal.overlay && this.confirmModal.overlay.parentNode) {
                    this.confirmModal.overlay.parentNode.removeChild(this.confirmModal.overlay);
                }
                this.confirmModal = null;
            }
        }

        /**
         * 显示次数不足提示
         * @param {number} credits - 当前剩余次数
         * @param {number} required - 所需次数
         */
        showInsufficientCredits(credits, required) {
            // 移除已有弹窗
            this.removeConfirmModal();

            // 创建遮罩层
            const overlay = document.createElement('div');
            overlay.className = CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS;
            
            // 创建弹窗
            const modal = document.createElement('div');
            modal.className = CONFIG.UI.CONFIRM_MODAL_CLASS;
            modal.innerHTML = `
                <div class="confirm-modal-header">
                    <h3>诊断次数不足</h3>
                    <button class="confirm-modal-close">&times;</button>
                </div>
                <div class="confirm-modal-body">
                    <div class="insufficient-icon">😅</div>
                    <div class="insufficient-info">
                        <p>当前剩余诊断次数：<strong>${credits}</strong> 次</p>
                        <p>本次诊断需要：<strong>${required}</strong> 次</p>
                        <p>还差 <strong>${required - credits}</strong> 次</p>
                    </div>
                    <div class="price-info">
                        <p>单次诊断价格：<strong>¥${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS}</strong></p>
                        <p>购买套餐更优惠！</p>
                    </div>
                </div>
                <div class="confirm-modal-footer">
                    <button class="btn btn-secondary confirm-cancel">稍后再说</button>
                    <button class="btn btn-primary confirm-recharge">去充值</button>
                </div>
            `;

            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // 保存弹窗引用
            this.confirmModal = {
                overlay: overlay,
                modal: modal
            };

            // 绑定事件
            const closeBtn = modal.querySelector('.confirm-modal-close');
            const cancelBtn = modal.querySelector('.confirm-cancel');
            const rechargeBtn = modal.querySelector('.confirm-recharge');

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

            // 跳转到充值页面
            rechargeBtn.addEventListener('click', () => {
                closeModal();
                this.showPaymentGuide();
            });
        }

        /**
         * 发起诊断
         */
        startDiagnosis() {
            // 显示加载状态
            const loading = showLoading('正在发起诊断...');

            // 准备诊断数据
            const diagnosisData = {
                context: this.context,
                timestamp: Date.now()
            };

            // 调用诊断接口
            fetch(CONFIG.API.DIAGNOSIS_START, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(diagnosisData)
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('网络请求失败');
                }
                return response.json();
            })
            .then(data => {
                hideLoading(loading);

                if (data.success) {
                    // 诊断成功，保存结果
                    this.saveDiagnosisResult(data.data);
                    
                    // 触发诊断完成事件
                    document.dispatchEvent(new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, {
                        detail: data.data
                    }));

                    // 执行回调
                    if (typeof this.currentDiagnosisCallback === 'function') {
                        this.currentDiagnosisCallback(data.data);
                    }

                    // 显示成功提示
                    this.showSuccessToast('诊断完成！');
                } else {
                    showError(data.message || '诊断失败，请稍后重试');
                }
            })
            .catch(error => {
                hideLoading(loading);
                console.error('[diagnosis_bridge] 发起诊断失败:', error);
                showError('发起诊断失败，请稍后重试');
            });
        }

        /**
         * 显示成功提示
         * @param {string} message - 成功信息
         */
        showSuccessToast(message) {
            const toast = document.createElement('div');
            toast.className = 'diagnosis-success-toast';
            toast.innerHTML = `
                <span class="toast-icon">✅</span>
                <span class="toast-text">${message}</span>
            `;
            document.body.appendChild(toast);
            
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 3000);
        }

        /**
         * 显示付费引导
         */
        showPaymentGuide() {
            // 触发付费引导事件
            document.dispatchEvent(new CustomEvent(CONFIG.EVENTS.PAYMENT_GUIDE, {
                detail: {
                    price: CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS,
                    packageUrl: CONFIG.PAYMENT.PACKAGE_URL,
                    rechargeUrl: CONFIG.PAYMENT.RECHARGE_URL
                }
            }));

            // 跳转到套餐页面
            window.location.href = CONFIG.PAYMENT.PACKAGE_URL;
        }

        /**
         * 一键重新诊断
         * @param {string} resultId - 诊断结果ID
         */
        reDiagnose(resultId) {
            const results = this.getDiagnosisHistory();
            const result = results.find(r => r.id === resultId);
            
            if (result) {
                // 使用之前的上下文重新诊断
                this.saveContext(result.context || {});
                this.checkCreditsAndDiagnose(() => {
                    this.navigateToDiagnosis();
                });
            }
        }
    }

    // ============================================================
    // 导出实例
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

})();