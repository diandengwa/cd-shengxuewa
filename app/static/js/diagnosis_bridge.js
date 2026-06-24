```javascript
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
        const loadingEl = document.getElementById('diagnosis-loading');
        if (loadingEl) {
            loadingEl.textContent = message;
            loadingEl.style.display = 'block';
        } else {
            const div = document.createElement('div');
            div.id = 'diagnosis-loading';
            div.className = 'diagnosis-loading';
            div.textContent = message;
            div.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(0,0,0,0.8);color:#fff;padding:20px 30px;border-radius:8px;z-index:9999;font-size:16px;';
            document.body.appendChild(div);
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
     */
    function showError(message) {
        const errorEl = document.getElementById('diagnosis-error');
        if (errorEl) {
            errorEl.textContent = message;
            errorEl.style.display = 'block';
            setTimeout(() => {
                errorEl.style.display = 'none';
            }, 5000);
        } else {
            alert(message);
        }
    }

    // ============================================================
    // 核心功能模块
    // ============================================================

    /**
     * 诊断桥接器主类
     */
    class DiagnosisBridge {
        constructor() {
            this.context = null;
            this.initialized = false;
            this.creditsCheckInProgress = false;
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
            if (isOnQueryPage()) {
                this.initQueryPage();
            } else if (isOnDiagnosisPage()) {
                this.initDiagnosisPage();
            }

            // 监听自定义事件
            this.bindEvents();

            console.log('[diagnosis_bridge] 初始化完成');
        }

        /**
         * 加载上下文
         */
        loadContext() {
            const stored = localStorage.getItem(CONFIG.STORAGE_KEY);
            if (stored) {
                const parsed = safeParseJSON(stored);
                if (parsed && !isContextExpired(parsed)) {
                    this.context = parsed;
                } else {
                    // 上下文过期，清除
                    localStorage.removeItem(CONFIG.STORAGE_KEY);
                }
            }
        }

        /**
         * 保存上下文
         * @param {Object} context - 上下文数据
         */
        saveContext(context) {
            const data = {
                ...context,
                id: context.id || generateId(),
                timestamp: Date.now()
            };
            this.context = data;
            localStorage.setItem(CONFIG.STORAGE_KEY, JSON.stringify(data));
        }

        /**
         * 清除上下文
         */
        clearContext() {
            this.context = null;
            localStorage.removeItem(CONFIG.STORAGE_KEY);
        }

        /**
         * 初始化查询页面
         */
        initQueryPage() {
            this.renderGuideBar();
            this.bindQueryPageEvents();
        }

        /**
         * 初始化诊断页面
         */
        initDiagnosisPage() {
            this.renderContextBadge();
            this.bindDiagnosisPageEvents();
        }

        /**
         * 绑定全局事件
         */
        bindEvents() {
            // 监听诊断完成事件
            document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, (e) => {
                this.handleDiagnosisComplete(e.detail);
            });

            // 监听导航到诊断事件
            document.addEventListener(CONFIG.EVENTS.NAVIGATE_TO_DIAGNOSIS, (e) => {
                this.handleNavigateToDiagnosis(e.detail);
            });

            // 监听查看历史事件
            document.addEventListener(CONFIG.EVENTS.DIAGNOSIS_HISTORY, () => {
                this.showHistory();
            });

            // 监听次数检查事件
            document.addEventListener(CONFIG.EVENTS.CREDITS_CHECK, (e) => {
                this.handleCreditsCheck(e.detail);
            });

            // 监听付费引导事件
            document.addEventListener(CONFIG.EVENTS.PAYMENT_GUIDE, () => {
                this.showPaymentGuide();
            });

            // 监听政策引用点击事件
            document.addEventListener(CONFIG.EVENTS.POLICY_REFERENCE_CLICK, (e) => {
                this.handlePolicyReferenceClick(e.detail);
            });
        }

        /**
         * 绑定查询页面事件
         */
        bindQueryPageEvents() {
            // 监听查询表单提交
            const queryForm = document.getElementById('query-form');
            if (queryForm) {
                queryForm.addEventListener('submit', (e) => {
                    // 捕获查询上下文
                    const formData = new FormData(queryForm);
                    const context = {
                        query: formData.get('query') || '',
                        grade: formData.get('grade') || '',
                        region: formData.get('region') || '',
                        schoolType: formData.get('school_type') || '',
                        additionalInfo: formData.get('additional_info') || ''
                    };
                    this.saveContext(context);
                });
            }

            // 监听查询结果中的诊断引导按钮点击
            document.addEventListener('click', (e) => {
                const target = e.target.closest(`.${CONFIG.UI.GUIDE_BUTTON_CLASS}`);
                if (target) {
                    e.preventDefault();
                    const contextData = target.dataset.context;
                    if (contextData) {
                        const context = safeParseJSON(contextData);
                        if (context) {
                            this.saveContext(context);
                        }
                    }
                    this.navigateToDiagnosis();
                }
            });
        }

        /**
         * 绑定诊断页面事件
         */
        bindDiagnosisPageEvents() {
            // 监听诊断表单提交
            const diagnosisForm = document.getElementById('diagnosis-form');
            if (diagnosisForm) {
                diagnosisForm.addEventListener('submit', (e) => {
                    e.preventDefault();
                    this.startDiagnosis();
                });
            }

            // 监听一键重新诊断按钮
            const reDiagnoseBtn = document.getElementById('re-diagnose-btn');
            if (reDiagnoseBtn) {
                reDiagnoseBtn.addEventListener('click', () => {
                    this.clearContext();
                    window.location.href = CONFIG.QUERY_PATH;
                });
            }

            // 监听政策引用链接点击
            document.addEventListener('click', (e) => {
                const target = e.target.closest(`.${CONFIG.UI.POLICY_REFERENCE_CLASS}`);
                if (target) {
                    e.preventDefault();
                    const policyId = target.dataset.policyId;
                    if (policyId) {
                        this.viewPolicyDetail(policyId);
                    }
                }
            });
        }

        /**
         * 渲染引导栏（查询结果页底部）
         */
        renderGuideBar() {
            // 检查是否已存在
            if (document.querySelector(`.${CONFIG.UI.GUIDE_BAR_CLASS}`)) return;

            const guideBar = document.createElement('div');
            guideBar.className = CONFIG.UI.GUIDE_BAR_CLASS;
            guideBar.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:15px 20px;text-align:center;z-index:1000;box-shadow:0 -2px 10px rgba(0,0,0,0.1);';

            const text = document.createElement('p');
            text.textContent = '想要更精准的升学建议？试试AI智能诊断！';
            text.style.cssText = 'margin:0 0 10px 0;font-size:16px;';

            const btn = document.createElement('button');
            btn.className = CONFIG.UI.GUIDE_BUTTON_CLASS;
            btn.textContent = '开始诊断';
            btn.style.cssText = 'background:#fff;color:#667eea;border:none;padding:10px 30px;border-radius:25px;font-size:16px;cursor:pointer;font-weight:bold;transition:transform 0.2s;';
            btn.addEventListener('mouseenter', () => {
                btn.style.transform = 'scale(1.05)';
            });
            btn.addEventListener('mouseleave', () => {
                btn.style.transform = 'scale(1)';
            });
            btn.addEventListener('click', () => {
                this.navigateToDiagnosis();
            });

            guideBar.appendChild(text);
            guideBar.appendChild(btn);
            document.body.appendChild(guideBar);
        }

        /**
         * 渲染上下文徽章（诊断页面）
         */
        renderContextBadge() {
            if (!this.context) return;

            const badgeContainer = document.getElementById('context-badge-container');
            if (!badgeContainer) return;

            const badge = document.createElement('div');
            badge.className = CONFIG.UI.CONTEXT_BADGE_CLASS;
            badge.style.cssText = 'background:#f0f4ff;border:1px solid #d0d7ff;border-radius:8px;padding:12px 16px;margin-bottom:20px;';

            const title = document.createElement('h4');
            title.textContent = '📋 诊断上下文';
            title.style.cssText = 'margin:0 0 8px 0;color:#333;font-size:14px;';

            const content = document.createElement('div');
            content.style.cssText = 'font-size:13px;color:#666;line-height:1.6;';

            if (this.context.query) {
                const p = document.createElement('p');
                p.innerHTML = `<strong>查询内容：</strong>${this.context.query}`;
                content.appendChild(p);
            }
            if (this.context.grade) {
                const p = document.createElement('p');
                p.innerHTML = `<strong>年级：</strong>${this.context.grade}`;
                content.appendChild(p);
            }
            if (this.context.region) {
                const p = document.createElement('p');
                p.innerHTML = `<strong>区域：</strong>${this.context.region}`;
                content.appendChild(p);
            }

            badge.appendChild(title);
            badge.appendChild(content);
            badgeContainer.appendChild(badge);
        }

        /**
         * 导航到诊断页面
         */
        navigateToDiagnosis() {
            // 触发导航事件
            const event = new CustomEvent(CONFIG.EVENTS.NAVIGATE_TO_DIAGNOSIS, {
                detail: { context: this.context }
            });
            document.dispatchEvent(event);

            // 页面跳转
            window.location.href = CONFIG.DIAGNOSIS_PATH;
        }

        /**
         * 处理导航到诊断事件
         * @param {Object} detail - 事件详情
         */
        handleNavigateToDiagnosis(detail) {
            if (detail && detail.context) {
                this.saveContext(detail.context);
            }
        }

        /**
         * 检查诊断次数
         * @returns {Promise<Object>} 检查结果
         */
        async checkCredits() {
            if (this.creditsCheckInProgress) {
                return { available: false, message: '检查中，请稍候...' };
            }

            this.creditsCheckInProgress = true;
            showLoading('检查诊断次数...');

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
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();
                return data;
            } catch (error) {
                console.error('[diagnosis_bridge] 检查诊断次数失败:', error);
                return {
                    available: false,
                    message: '检查诊断次数失败，请稍后重试',
                    error: error.message
                };
            } finally {
                this.creditsCheckInProgress = false;
                hideLoading();
            }
        }

        /**
         * 处理次数检查事件
         * @param {Object} detail - 事件详情
         */
        async handleCreditsCheck(detail) {
            const result = await this.checkCredits();
            
            if (result.available) {
                // 次数充足，显示确认弹窗
                this.showConfirmModal(result);
            } else {
                // 次数不足，触发付费引导
                const event = new CustomEvent(CONFIG.EVENTS.CREDITS_INSUFFICIENT, {
                    detail: result
                });
                document.dispatchEvent(event);
                this.showPaymentGuide(result);
            }
        }

        /**
         * 显示确认弹窗
         * @param {Object} creditsInfo - 次数信息
         */
        showConfirmModal(creditsInfo) {
            // 移除已存在的弹窗
            this.removeConfirmModal();

            const overlay = document.createElement('div');
            overlay.className = CONFIG.UI.CONFIRM_MODAL_OVERLAY_CLASS;
            overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9998;display:flex;align-items:center;justify-content:center;';

            const modal = document.createElement('div');
            modal.className = CONFIG.UI.CONFIRM_MODAL_CLASS;
            modal.style.cssText = 'background:#fff;border-radius:12px;padding:24px;max-width:400px;width:90%;box-shadow:0 10px 40px rgba(0,0,0,0.2);position:relative;';

            // 标题
            const title = document.createElement('h3');
            title.textContent = '🔍 确认诊断';
            title.style.cssText = 'margin:0 0 16px 0;color:#333;font-size:18px;text-align:center;';

            // 次数信息
            const info = document.createElement('div');
            info.style.cssText = 'background:#f8f9ff;border-radius:8px;padding:12px;margin-bottom:16px;font-size:14px;color:#666;';
            info.innerHTML = `
                <p style="margin:0 0 8px 0;"><strong>当前剩余次数：</strong>${creditsInfo.balance || 0} 次</p>
                <p style="margin:0;"><strong>本次诊断消耗：</strong>${CONFIG.PAYMENT.MIN_CREDITS_REQUIRED} 次</p>
                <p style="margin:8px 0 0 0;color:#999;font-size:12px;">诊断后将扣除 ${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS} 元/次</p>
            `;

            // 按钮组
            const btnGroup = document.createElement('div');
            btnGroup.style.cssText = 'display:flex;gap:12px;justify-content:center;';

            const cancelBtn = document.createElement('button');
            cancelBtn.textContent = '取消';
            cancelBtn.style.cssText = 'padding:10px 24px;border:1px solid #ddd;border-radius:6px;background:#fff;color:#666;cursor:pointer;font-size:14px;';
            cancelBtn.addEventListener('click', () => {
                this.removeConfirmModal();
            });

            const confirmBtn = document.createElement('button');
            confirmBtn.textContent = '确认诊断';
            confirmBtn.style.cssText = 'padding:10px 24px;border:none;border-radius:6px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;cursor:pointer;font-size:14px;font-weight:bold;';
            confirmBtn.addEventListener('click', () => {
                this.removeConfirmModal();
                this.startDiagnosis();
            });

            btnGroup.appendChild(cancelBtn);
            btnGroup.appendChild(confirmBtn);

            modal.appendChild(title);
            modal.appendChild(info);
            modal.appendChild(btnGroup);
            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // 点击遮罩关闭
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    this.removeConfirmModal();
                }
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
         * 显示付费引导
         * @param {Object} creditsInfo - 次数信息
         */
        showPaymentGuide(creditsInfo) {
            // 触发付费引导事件
            const event = new CustomEvent(CONFIG.EVENTS.PAYMENT_GUIDE, {
                detail: creditsInfo
            });
            document.dispatchEvent(event);

            // 移除已存在的引导
            const existingGuide = document.getElementById('payment-guide-modal');
            if (existingGuide) {
                existingGuide.remove();
            }

            const overlay = document.createElement('div');
            overlay.id = 'payment-guide-modal';
            overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;';

            const modal = document.createElement('div');
            modal.style.cssText = 'background:#fff;border-radius:12px;padding:24px;max-width:400px;width:90%;box-shadow:0 10px 40px rgba(0,0,0,0.2);';

            // 标题
            const title = document.createElement('h3');
            title.textContent = '💡 诊断次数不足';
            title.style.cssText = 'margin:0 0 16px 0;color:#333;font-size:18px;text-align:center;';

            // 信息
            const info = document.createElement('div');
            info.style.cssText = 'background:#fff3f3;border-radius:8px;padding:12px;margin-bottom:16px;font-size:14px;color:#666;';
            info.innerHTML = `
                <p style="margin:0 0 8px 0;"><strong>当前剩余次数：</strong>${creditsInfo ? creditsInfo.balance : 0} 次</p>
                <p style="margin:0;"><strong>每次诊断需消耗：</strong>${CONFIG.PAYMENT.MIN_CREDITS_REQUIRED} 次</p>
                <p style="margin:8px 0 0 0;color:#e74c3c;font-size:13px;">请购买诊断次数后再进行诊断</p>
            `;

            // 套餐推荐
            const packages = document.createElement('div');
            packages.style.cssText = 'margin-bottom:16px;';
            packages.innerHTML = `
                <h4 style="margin:0 0 8px 0;color:#333;font-size:14px;">推荐套餐</h4>
                <div style="background:#f8f9ff;border-radius:8px;padding:12px;">
                    <p style="margin:0 0 4px 0;color:#667eea;font-weight:bold;">单次诊断：¥${CONFIG.PAYMENT.PRICE_PER_DIAGNOSIS}</p>
                    <p style="margin:0;color:#999;font-size:12px;">适合偶尔需要诊断的用户</p>
                </div>
                <div style="background:#f0fff4;border-radius:8px;padding:12px;margin-top:8px;">
                    <p style="margin:0 0 4px 0;color:#27ae60;font-weight:bold;">10次套餐：¥79.0（省20%）</p>
                    <p style="margin:0;color:#999;font-size:12px;">适合经常需要诊断的用户</p>
                </div>
            `;

            // 按钮组
            const btnGroup = document.createElement('div');
            btnGroup.style.cssText = 'display:flex;gap:12px;justify-content:center;';

            const closeBtn = document.createElement('button');
            closeBtn.textContent = '稍后再说';
            closeBtn.style.cssText = 'padding:10px 24px;border:1px solid #ddd;border-radius:6px;background:#fff;color:#666;cursor:pointer;font-size:14px;';
            closeBtn.addEventListener('click', () => {
                overlay.remove();
            });

            const buyBtn = document.createElement('button');
            buyBtn.textContent = '去购买';
            buyBtn.style.cssText = 'padding:10px 24px;border:none;border-radius:6px;background:linear-gradient(135deg,#e74c3c 0%,#c0392b 100%);color:#fff;cursor:pointer;font-size:14px;font-weight:bold;';
            buyBtn.addEventListener('click', () => {
                overlay.remove();
                window.location.href = CONFIG.PAYMENT.PACKAGE_URL;
            });

            btnGroup.appendChild(closeBtn);
            btnGroup.appendChild(buyBtn);

            modal.appendChild(title);
            modal.appendChild(info);
            modal.appendChild(packages);
            modal.appendChild(btnGroup);
            overlay.appendChild(modal);
            document.body.appendChild(overlay);

            // 点击遮罩关闭
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    overlay.remove();
                }
            });
        }

        /**
         * 开始诊断
         */
        async startDiagnosis() {
            // 先检查次数
            const creditsResult = await this.checkCredits();
            
            if (!creditsResult.available) {
                this.showPaymentGuide(creditsResult);
                return;
            }

            showLoading('正在生成诊断结果...');

            try {
                // 收集诊断表单数据
                const formData = new FormData(document.getElementById('diagnosis-form'));
                const diagnosisData = {
                    query: formData.get('query') || (this.context ? this.context.query : ''),
                    grade: formData.get('grade') || (this.context ? this.context.grade : ''),
                    region: formData.get('region') || (this.context ? this.context.region : ''),
                    schoolType: formData.get('school_type') || (this.context ? this.context.schoolType : ''),
                    additionalInfo: formData.get('additional_info') || (this.context ? this.context.additionalInfo : ''),
                    contextId: this.context ? this.context.id : null
                };

                // 调用诊断API
                const response = await fetch(CONFIG.API.DIAGNOSIS_START, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify(diagnosisData)
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const result = await response.json();

                // 保存诊断结果到历史
                this.saveDiagnosisResult(result);

                // 触发诊断完成事件
                const event = new CustomEvent(CONFIG.EVENTS.DIAGNOSIS_COMPLETE, {
                    detail: result
                });
                document.dispatchEvent(event);

                // 显示诊断结果
                this.displayDiagnosisResult(result);

            } catch (error) {
                console.error('[diagnosis_bridge] 诊断失败:', error);
                showError('诊断失败，请稍后重试');
            } finally {
                hideLoading();
            }
        }

        /**
         * 处理诊断完成事件
         * @param {Object} result - 诊断结果
         */
        handleDiagnosisComplete(result) {
            if (result && result.diagnosisId) {
                // 清除上下文
                this.clearContext();
            }
        }

        /**
         * 保存诊断结果到历史
         * @param {Object} result - 诊断结果
         */
        saveDiagnosisResult(result) {
            if (!result || !result.diagnosisId) return;

            const stored = localStorage.getItem(CONFIG.RESULT_STORAGE_KEY);
            const history = stored ? safeParseJSON(stored, []) : [];

            // 添加新结果
            history.unshift({
                id: result.diagnosisId,
                timestamp: Date.now(),
                summary: result.summary || '诊断结果',
                query: result.query || (this.context ? this.context.query : ''),
                result: result
            });

            // 限制历史记录数量
            if (history.length > CONFIG.MAX_HISTORY) {
                history.length = CONFIG.MAX_HISTORY;
            }

            localStorage.setItem(CONFIG.RESULT_STORAGE_KEY, JSON.stringify(history));
        }

        /**
         * 显示诊断结果
         * @param {Object} result - 诊断结果
         */
        displayDiagnosisResult(result) {
            const resultContainer = document.getElementById('diagnosis-result');
            if (!resultContainer) return;

            // 清空容器
            resultContainer.innerHTML = '';

            // 创建结果卡片
            const card = document.createElement('div');
            card.className = 'diagnosis-result-card';
            card.style.cssText = 'background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,0.08);';

            // 标题
            const title = document.createElement('h3');
            title.textContent = '📊 诊断结果';
            title.style.cssText = 'margin:0 0 16px 0;color:#333;font-size:18px;';

            // 诊断ID
            const idInfo = document.createElement('p');
            idInfo.textContent = `诊断ID: ${result.diagnosisId}`;
            idInfo.style.cssText = 'font-size:12px;color:#999;margin:0 0 12px 0;';

            // 摘要
            if (result.summary) {
                const summary = document.createElement('div');
                summary.style.cssText = 'background:#f8f9ff;border-radius:8px;padding:12px;margin-bottom:16px;';
                summary.innerHTML = `<strong>摘要：</strong>${result.summary}`;
                card.appendChild(summary);
            }

            // 详细建议
            if (result.suggestions && result.suggestions.length > 0) {
                const suggestionsTitle = document.createElement('h4');
                suggestionsTitle.textContent = '💡 建议';
                suggestionsTitle.style.cssText = 'margin:16px 0 8px 0;color:#333;font-size:15px;';
                card.appendChild(suggestionsTitle);

                const list = document.createElement('ul');
                list.style.cssText = 'padding-left:20px;margin:0;';
                result.suggestions.forEach(suggestion => {
                    const li = document.createElement('li');
                    li.style.cssText = 'margin-bottom:8px;line-height:1.6;color:#555;';
                    li.textContent = suggestion;
                    list.appendChild(li);
                });
                card.appendChild(list);
            }

            // 政策引用
            if (result.policyReferences && result.policyReferences.length > 0) {
                const refTitle = document.createElement('h4');
                refTitle.textContent = '📜 相关政策';
                refTitle.style.cssText = 'margin:16px 0 8px 0;color:#333;font-size:15px;';
                card.appendChild(refTitle);

                result.policyReferences.forEach(ref => {
                    const refLink = document.createElement('a');
                    refLink.className = CONFIG.UI.POLICY_REFERENCE_CLASS;
                    refLink.href = '#';
                    refLink.dataset.policyId = ref.id;
                    refLink.textContent = ref.title || `政策 #${ref.id}`;
                    refLink.style.cssText = 'display:block;padding:8px 12px;margin-bottom:4px;background:#f0f4ff;border-radius:6px;color:#667eea;text-decoration:none;font-size:13px;';
                    refLink.addEventListener('click', (e) => {
                        e.preventDefault();
                        this.viewPolicyDetail(ref.id);
                    });
                    card.appendChild(refLink);
                });
            }

            // 操作按钮
            const btnGroup = document.createElement('div');
            btnGroup.style.cssText = 'display:flex;gap:12px;margin-top:20px;';

            const backBtn = document.createElement('button');
            backBtn.textContent = '返回查询';
            backBtn.style.cssText = 'padding:10px 24px;border:1px solid #ddd;border-radius:6px;background:#fff;color:#666;cursor:pointer;font-size:14px;';
            backBtn.addEventListener('click', () => {
                window.location.href = CONFIG.QUERY_PATH;
            });

            const reDiagnoseBtn = document.createElement('button');
            reDiagnoseBtn.textContent = '重新诊断';
            reDiagnoseBtn.style.cssText = 'padding:10px 24px;border:none;border-radius:6px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;cursor:pointer;font-size:14px;font-weight:bold;';
            reDiagnoseBtn.addEventListener('click', () => {
                this.clearContext();
                window.location.href = CONFIG.DIAGNOSIS_PATH;
            });

            btnGroup.appendChild(backBtn);
            btnGroup.appendChild(reDiagnoseBtn);

            card.appendChild(title);
            card.appendChild(idInfo);
            card.appendChild(btnGroup);
            resultContainer.appendChild(card);
        }

        /**
         * 查看政策详情
         * @param {string} policyId - 政策ID
         */
        async viewPolicyDetail(policyId) {
            showLoading('加载政策详情...');

            try {
                const response = await fetch(`${CONFIG.API.GET_POLICY}${policyId}`, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
