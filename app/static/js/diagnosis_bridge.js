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
            CONTEXT_BADGE_CLASS: 'diagnosis-context-badge'
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
        const toast = document.createElement('div');
        toast.className = 'diagnosis-toast diagnosis-toast-error';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 3000);
    }

    /**
     * 显示成功提示
     * @param {string} message - 成功信息
     */
    function showSuccess(message) {
        const toast = document.createElement('div');
        toast.className = 'diagnosis-toast diagnosis-toast-success';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 3000);
    }

    // ============================================================
    // 上下文管理
    // ============================================================

    /**
     * 保存诊断上下文到 localStorage
     * @param {Object} context - 上下文对象
     */
    function saveContext(context) {
        try {
            const data = {
                ...context,
                id: context.id || generateId(),
                timestamp: Date.now()
            };
            localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(data));
            console.log('[diagnosis_bridge] 上下文已保存:', data.id);
        } catch (e) {
            console.error('[diagnosis_bridge] 保存上下文失败:', e);
        }
    }

    /**
     * 获取诊断上下文
     * @returns {Object|null} 上下文对象或null
     */
    function getContext() {
        try {
            const raw = localStorage.getItem(CONFIG.STORAGE_KEY);
            if (!raw) return null;
            const context = safeParseJSON(raw);
            if (!context) return null;
            if (isContextExpired(context)) {
                console.log('[diagnosis_bridge] 上下文已过期');
                clearContext();
                return null;
            }
            return context;
        } catch (e) {
            console.error('[diagnosis_bridge] 获取上下文失败:', e);
            return null;
        }
    }

    /**
     * 清除诊断上下文
     */
    function clearContext() {
        try {
            localStorage.removeItem(CONFIG.STORAGE_KEY);
            console.log('[diagnosis_bridge] 上下文已清除');
        } catch (e) {
            console.error('[diagnosis_bridge] 清除上下文失败:', e);
        }
    }

    /**
     * 更新上下文中的部分字段
     * @param {Object} updates - 要更新的字段
     */
    function updateContext(updates) {
        const context = getContext() || {};
        saveContext({ ...context, ...updates });
    }

    // ============================================================
    // 诊断历史管理
    // ============================================================

    /**
     * 保存诊断结果到历史记录
     * @param {Object} result - 诊断结果对象
     */
    function saveDiagnosisResult(result) {
        try {
            const history = getDiagnosisHistory();
            history.unshift({
                ...result,
                id: result.id || generateId(),
                timestamp: Date.now()
            });
            // 限制历史记录数量
            if (history.length > CONFIG.MAX_HISTORY) {
                history.length = CONFIG.MAX_HISTORY;
            }
            localStorage.setItem(CONFIG.RESULT_STORAGE_KEY, JSON.stringify(history));
            console.log('[diagnosis_bridge] 诊断结果已保存');
        } catch (e) {
            console.error('[diagnosis_bridge] 保存诊断结果失败:', e);
        }
    }

    /**
     * 获取诊断历史记录
     * @returns {Array} 历史记录数组
     */
    function getDiagnosisHistory() {
        try {
            const raw = localStorage.getItem(CONFIG.RESULT_STORAGE_KEY);
            return safeParseJSON(raw, []);
        } catch (e) {
            console.error('[diagnosis_bridge] 获取诊断历史失败:', e);
            return [];
        }
    }

    /**
     * 清除诊断历史记录
     */
    function clearDiagnosisHistory() {
        try {
            localStorage.removeItem(CONFIG.RESULT_STORAGE_KEY);
            console.log('[diagnosis_bridge] 诊断历史已清除');
        } catch (e) {
            console.error('[diagnosis_bridge] 清除诊断历史失败:', e);
        }
    }

    // ============================================================
    // API 调用
    // ============================================================

    /**
     * 检查用户诊断次数
     * @returns {Promise<Object>} 检查结果
     */
    async function checkCredits() {
        try {
            const response = await fetch(CONFIG.API.CHECK_CREDITS, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (e) {
            console.error('[diagnosis_bridge] 检查诊断次数失败:', e);
            throw e;
        }
    }

    /**
     * 获取用户剩余诊断次数
     * @returns {Promise<number>} 剩余次数
     */
    async function getCreditsBalance() {
        try {
            const response = await fetch(CONFIG.API.GET_CREDITS, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            return data.balance || 0;
        } catch (e) {
            console.error('[diagnosis_bridge] 获取诊断次数失败:', e);
            return 0;
        }
    }

    /**
     * 开始诊断
     * @param {Object} context - 诊断上下文
     * @returns {Promise<Object>} 诊断结果
     */
    async function startDiagnosis(context) {
        try {
            const response = await fetch(CONFIG.API.DIAGNOSIS_START, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(context)
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (e) {
            console.error('[diagnosis_bridge] 开始诊断失败:', e);
            throw e;
        }
    }

    /**
     * 获取政策原文
     * @param {string} policyId - 政策ID
     * @returns {Promise<Object>} 政策详情
     */
    async function getPolicyDetail(policyId) {
        try {
            const response = await fetch(`${CONFIG.API.GET_POLICY}${policyId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return await response.json();
        } catch (e) {
            console.error('[diagnosis_bridge] 获取政策详情失败:', e);
            throw e;
        }
    }

    // ============================================================
    // 付费引导
    // ============================================================

    /**
     * 显示付费引导弹窗
     * @param {number} balance - 当前剩余次数
     */
    function showPaymentGuide(balance) {
        const modal = document.createElement('div');
        modal.className = 'diagnosis-modal';
        modal.innerHTML = `
            <div class="diagnosis-modal-content">
                <div class="diagnosis-modal-header">
                    <h3>诊断次数不足</h3>
                    <button class="diagnosis-modal-close">&times;</button>
                </div>
                <div class="diagnosis-modal-body">
                    <p>当前剩余诊断次数：<strong>${balance}</strong> 次</p>
                    <p>每次诊断需要消耗 <strong>${CONFIG.PAYMENT.MIN_CREDITS_REQUIRED}</strong> 次</p>
                    <p>单次诊断价格：<strong>¥${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS}</strong></p>
                    <div class="diagnosis-payment-options">
                        <a href="${CONFIG.PAYMENT.PACKAGE_URL}" class="diagnosis-btn diagnosis-btn-primary">
                            购买套餐
                        </a>
                        <a href="${CONFIG.PAYMENT.RECHARGE_URL}" class="diagnosis-btn diagnosis-btn-secondary">
                            立即充值
                        </a>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        // 关闭按钮事件
        const closeBtn = modal.querySelector('.diagnosis-modal-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                document.body.removeChild(modal);
            });
        }

        // 点击遮罩关闭
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        });

        // 触发付费引导事件
        const event = new CustomEvent(CONFIG.EVENTS.PAYMENT_GUIDE, {
            detail: { balance, modal }
        });
        document.dispatchEvent(event);
    }

    // ============================================================
    // UI 组件创建
    // ============================================================

    /**
     * 创建引导按钮
     * @param {Object} context - 上下文对象
     * @returns {HTMLElement} 按钮元素
     */
    function createGuideButton(context) {
        const btn = document.createElement('button');
        btn.className = CONFIG.UI.GUIDE_BUTTON_CLASS;
        btn.innerHTML = `
            <span class="guide-btn-icon">🔍</span>
            <span class="guide-btn-text">开始诊断</span>
            <span class="guide-btn-badge">${context.keywords || '当前查询'}</span>
        `;
        
        btn.addEventListener('click', async function(e) {
            e.preventDefault();
            await navigateToDiagnosis(context);
        });

        return btn;
    }

    /**
     * 创建引导栏
     * @param {Object} context - 上下文对象
     * @returns {HTMLElement} 引导栏元素
     */
    function createGuideBar(context) {
        const bar = document.createElement('div');
        bar.className = CONFIG.UI.GUIDE_BAR_CLASS;
        bar.innerHTML = `
            <div class="guide-bar-content">
                <div class="guide-bar-info">
                    <span class="guide-bar-icon">📋</span>
                    <span class="guide-bar-text">基于当前查询结果，可以进行升学诊断</span>
                    <span class="guide-bar-context">${context.keywords || '当前查询'}</span>
                </div>
                <div class="guide-bar-actions">
                    <button class="guide-bar-btn guide-bar-btn-primary" id="guideBarDiagnoseBtn">
                        开始诊断
                    </button>
                    <button class="guide-bar-btn guide-bar-btn-secondary" id="guideBarSkipBtn">
                        稍后再说
                    </button>
                </div>
            </div>
        `;

        // 开始诊断按钮
        const diagnoseBtn = bar.querySelector('#guideBarDiagnoseBtn');
        if (diagnoseBtn) {
            diagnoseBtn.addEventListener('click', async function(e) {
                e.preventDefault();
                await navigateToDiagnosis(context);
            });
        }

        // 稍后再说按钮
        const skipBtn = bar.querySelector('#guideBarSkipBtn');
        if (skipBtn) {
            skipBtn.addEventListener('click', function() {
                bar.classList.add('guide-bar-hidden');
                setTimeout(() => {
                    if (bar.parentNode) {
                        bar.parentNode.removeChild(bar);
                    }
                }, 300);
            });
        }

        return bar;
    }

    /**
     * 创建上下文徽章
     * @param {Object} context - 上下文对象
     * @returns {HTMLElement} 徽章元素
     */
    function createContextBadge(context) {
        const badge = document.createElement('span');
        badge.className = CONFIG.UI.CONTEXT_BADGE_CLASS;
        badge.innerHTML = `
            <span class="badge-icon">📌</span>
            <span class="badge-text">${context.keywords || '待诊断'}</span>
            <span class="badge-remove">&times;</span>
        `;

        // 移除按钮
        const removeBtn = badge.querySelector('.badge-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                clearContext();
                if (badge.parentNode) {
                    badge.parentNode.removeChild(badge);
                }
            });
        }

        return badge;
    }

    /**
     * 创建政策引用链接
     * @param {Object} policy - 政策对象
     * @returns {HTMLElement} 链接元素
     */
    function createPolicyReference(policy) {
        const ref = document.createElement('a');
        ref.className = CONFIG.UI.POLICY_REFERENCE_CLASS;
        ref.href = `${CONFIG.QUERY_PATH}?policy_id=${policy.id}`;
        ref.textContent = policy.title || '查看政策原文';
        ref.target = '_blank';
        ref.rel = 'noopener noreferrer';

        ref.addEventListener('click', function(e) {
            const event = new CustomEvent(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, {
                detail: { policy }
            });
            document.dispatchEvent(event);
        });

        return ref;
    }

    // ============================================================
    // 导航逻辑
    // ============================================================

    /**
     * 导航到诊断页面
     * @param {Object} context - 上下文对象
     */
    async function navigateToDiagnosis(context) {
        try {
            // 检查诊断次数
            const balance = await getCreditsBalance();
            if (balance < CONFIG.PAYMENT.MIN_CREDITS_REQUIRED) {
                showPaymentGuide(balance);
                return;
            }

            // 保存上下文
            saveContext(context);

            // 触发导航事件
            const event = new CustomEvent(CONFIG.EVENTS.NAVIGATE_TO_DIAGNOSIS, {
                detail: { context }
            });
            document.dispatchEvent(event);

            // 导航到诊断页面
            window.location.href = CONFIG.DIAGNOSIS_PATH;
        } catch (e) {
            console.error('[diagnosis_bridge] 导航到诊断页面失败:', e);
            showError('导航到诊断页面失败，请稍后重试');
        }
    }

    /**
     * 从诊断页面返回查询页面
     * @param {Object} result - 诊断结果
     */
    function navigateBackToQuery(result) {
        // 保存诊断结果
        saveDiagnosisResult(result);

        // 触发诊断完成事件
        const event = new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, {
            detail: { result }
        });
        document.dispatchEvent(event);

        // 导航回查询页面
        window.location.href = CONFIG.QUERY_PATH;
    }

    // ============================================================
    // 事件监听
    // ============================================================

    /**
     * 监听上下文就绪事件
     */
    function listenContextReady() {
        document.addEventListener(CONFIG.EVENTS.CONTEXT_READY, function(e) {
            const context = e.detail;
            if (context) {
                saveContext(context);
                console.log('[diagnosis_bridge] 上下文已就绪:', context);
            }
        });
    }

    /**
     * 监听诊断完成事件
     */
    function listenDiagnosisComplete() {
        document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, function(e) {
            const result = e.detail;
            if (result) {
                saveDiagnosisResult(result);
                console.log('[diagnosis_bridge] 诊断完成:', result);
            }
        });
    }

    /**
     * 监听诊断次数检查事件
     */
    function listenCreditsCheck() {
        document.addEventListener(CONFIG.EVENTS.CREDITS_CHECK, async function(e) {
            try {
                const balance = await getCreditsBalance();
                const event = new CustomEvent(CONFIG.EVENTS.CREDITS_INSUFFICIENT, {
                    detail: { balance, required: CONFIG.PAYMENT.MIN_CREDITS_REQUIRED }
                });
                document.dispatchEvent(event);
            } catch (error) {
                console.error('[diagnosis_bridge] 诊断次数检查失败:', error);
            }
        });
    }

    // ============================================================
    // 页面初始化
    // ============================================================

    /**
     * 初始化查询页面
     */
    function initQueryPage() {
        console.log('[diagnosis_bridge] 初始化查询页面');

        // 检查是否有诊断结果需要回写
        const context = getContext();
        if (context && context.result) {
            // 显示诊断结果提示
            showSuccess('诊断结果已就绪，可查看详情');
        }

        // 创建引导栏（如果有上下文）
        if (context && !context.result) {
            const guideBar = createGuideBar(context);
            const container = document.querySelector('.query-results-container');
            if (container) {
                container.appendChild(guideBar);
            }
        }

        // 监听查询结果事件
        document.addEventListener('query:results-ready', function(e) {
            const queryContext = e.detail;
            if (queryContext) {
                // 创建引导按钮
                const guideBtn = createGuideButton(queryContext);
                const resultsFooter = document.querySelector('.query-results-footer');
                if (resultsFooter) {
                    resultsFooter.appendChild(guideBtn);
                }

                // 创建引导栏
                const guideBar = createGuideBar(queryContext);
                const container = document.querySelector('.query-results-container');
                if (container) {
                    container.appendChild(guideBar);
                }
            }
        });
    }

    /**
     * 初始化诊断页面
     */
    function initDiagnosisPage() {
        console.log('[diagnosis_bridge] 初始化诊断页面');

        // 获取上下文
        const context = getContext();
        if (context) {
            // 显示上下文徽章
            const badge = createContextBadge(context);
            const header = document.querySelector('.diagnosis-header');
            if (header) {
                header.appendChild(badge);
            }

            // 自动填充诊断表单
            const keywordInput = document.querySelector('#diagnosisKeyword');
            if (keywordInput && context.keywords) {
                keywordInput.value = context.keywords;
            }

            const gradeSelect = document.querySelector('#diagnosisGrade');
            if (gradeSelect && context.grade) {
                gradeSelect.value = context.grade;
            }

            const regionSelect = document.querySelector('#diagnosisRegion');
            if (regionSelect && context.region) {
                regionSelect.value = context.region;
            }
        }

        // 处理政策引用链接
        document.querySelectorAll(`.${CONFIG.UI.POLICY_REFERENCE_CLASS}`).forEach(function(ref) {
            ref.addEventListener('click', function(e) {
                e.preventDefault();
                const policyId = ref.dataset.policyId;
                if (policyId) {
                    // 保存当前诊断上下文
                    const currentContext = getContext() || {};
                    saveContext({
                        ...currentContext,
                        returnToDiagnosis: true,
                        policyId: policyId
                    });
                    // 跳转到政策详情
                    window.location.href = `${CONFIG.QUERY_PATH}?policy_id=${policyId}`;
                }
            });
        });
    }

    /**
     * 初始化历史记录页面
     */
    function initHistoryPage() {
        console.log('[diagnosis_bridge] 初始化历史记录页面');

        const historyContainer = document.querySelector('.diagnosis-history-container');
        if (!historyContainer) return;

        const history = getDiagnosisHistory();
        if (history.length === 0) {
            historyContainer.innerHTML = '<p class="history-empty">暂无诊断记录</p>';
            return;
        }

        const list = document.createElement('ul');
        list.className = 'diagnosis-history-list';

        history.forEach(function(item) {
            const li = document.createElement('li');
            li.className = 'diagnosis-history-item';
            li.innerHTML = `
                <div class="history-item-header">
                    <span class="history-item-date">${new Date(item.timestamp).toLocaleString()}</span>
                    <span class="history-item-keywords">${item.keywords || '未指定关键词'}</span>
                </div>
                <div class="history-item-body">
                    <p>${item.summary || '暂无摘要'}</p>
                </div>
                <div class="history-item-actions">
                    <button class="history-item-view" data-id="${item.id}">查看详情</button>
                    <button class="history-item-rediagnose" data-id="${item.id}">重新诊断</button>
                </div>
            `;

            // 查看详情
            const viewBtn = li.querySelector('.history-item-view');
            if (viewBtn) {
                viewBtn.addEventListener('click', function() {
                    const event = new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_HISTORY, {
                        detail: { item }
                    });
                    document.dispatchEvent(event);
                    // 跳转到诊断结果页面
                    window.location.href = `${CONFIG.DIAGNOSIS_PATH}/result/${item.id}`;
                });
            }

            // 重新诊断
            const rediagnoseBtn = li.querySelector('.history-item-rediagnose');
            if (rediagnoseBtn) {
                rediagnoseBtn.addEventListener('click', async function() {
                    const context = {
                        keywords: item.keywords,
                        grade: item.grade,
                        region: item.region,
                        previousResult: item
                    };
                    await navigateToDiagnosis(context);
                });
            }

            list.appendChild(li);
        });

        historyContainer.appendChild(list);
    }

    // ============================================================
    // 主初始化
    // ============================================================

    /**
     * 主初始化函数
     */
    function init() {
        console.log('[diagnosis_bridge] 初始化诊断引导组件');

        // 注册事件监听
        listenContextReady();
        listenDiagnosisComplete();
        listenCreditsCheck();

        // 根据当前页面初始化
        if (isOnQueryPage()) {
            initQueryPage();
        } else if (isOnDiagnosisPage()) {
            initDiagnosisPage();
        }

        // 检查是否有历史记录页面
        if (document.querySelector('.diagnosis-history-container')) {
            initHistoryPage();
        }

        // 监听页面可见性变化，刷新上下文状态
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden) {
                const context = getContext();
                if (context && isOnDiagnosisPage()) {
                    console.log('[diagnosis_bridge] 页面重新可见，上下文有效');
                }
            }
        });

        console.log('[diagnosis_bridge] 诊断引导组件初始化完成');
    }

    // ============================================================
    // DOM 就绪后启动
    // ============================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();