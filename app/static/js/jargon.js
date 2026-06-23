/**
 * K12 Rocket v2.0 — 点灯蛙·成都K12升学参谋
 * 黑话翻译器前端交互脚本
 * 功能：输入、翻译、热门术语展示、历史记录管理
 */

(function() {
    'use strict';

    // ============================================================
    // 配置
    // ============================================================
    const CONFIG = {
        apiEndpoint: '/api/jargon/translate',
        historyEndpoint: '/api/jargon/history',
        hotTermsEndpoint: '/api/jargon/hot-terms',
        maxHistoryItems: 50,
        debounceDelay: 300,
        minInputLength: 1,
        maxInputLength: 200,
        hotTermsCount: 10
    };

    // ============================================================
    // DOM 缓存
    // ============================================================
    const DOM = {
        input: document.getElementById('jargon-input'),
        translateBtn: document.getElementById('jargon-translate-btn'),
        result: document.getElementById('jargon-result'),
        resultText: document.getElementById('jargon-result-text'),
        resultSource: document.getElementById('jargon-result-source'),
        historyList: document.getElementById('jargon-history-list'),
        clearHistoryBtn: document.getElementById('jargon-clear-history'),
        loading: document.getElementById('jargon-loading'),
        error: document.getElementById('jargon-error'),
        errorMessage: document.getElementById('jargon-error-message'),
        emptyState: document.getElementById('jargon-empty-state'),
        charCount: document.getElementById('jargon-char-count'),
        hotTermsContainer: document.getElementById('jargon-hot-terms'),
        copyBtn: document.getElementById('jargon-copy-btn'),
        clearInputBtn: document.getElementById('jargon-clear-input')
    };

    // ============================================================
    // 状态管理
    // ============================================================
    const state = {
        isTranslating: false,
        history: [],
        currentResult: null,
        debounceTimer: null,
        hotTerms: []
    };

    // ============================================================
    // 工具函数
    // ============================================================
    const utils = {
        /**
         * 防抖函数
         * @param {Function} fn - 要执行的函数
         * @param {number} delay - 延迟时间（毫秒）
         * @returns {Function} 防抖后的函数
         */
        debounce: function(fn, delay) {
            let timer = null;
            return function(...args) {
                if (timer) {
                    clearTimeout(timer);
                }
                timer = setTimeout(() => {
                    fn.apply(this, args);
                    timer = null;
                }, delay);
            };
        },

        /**
         * 显示加载状态
         */
        showLoading: function() {
            if (DOM.loading) {
                DOM.loading.classList.remove('hidden');
            }
            if (DOM.result) {
                DOM.result.classList.add('hidden');
            }
            if (DOM.error) {
                DOM.error.classList.add('hidden');
            }
            if (DOM.emptyState) {
                DOM.emptyState.classList.add('hidden');
            }
        },

        /**
         * 隐藏加载状态
         */
        hideLoading: function() {
            if (DOM.loading) {
                DOM.loading.classList.add('hidden');
            }
        },

        /**
         * 显示错误信息
         * @param {string} message - 错误消息
         */
        showError: function(message) {
            this.hideLoading();
            if (DOM.error && DOM.errorMessage) {
                DOM.errorMessage.textContent = message || '翻译失败，请稍后重试';
                DOM.error.classList.remove('hidden');
            }
            if (DOM.result) {
                DOM.result.classList.add('hidden');
            }
            if (DOM.emptyState) {
                DOM.emptyState.classList.add('hidden');
            }
        },

        /**
         * 隐藏错误信息
         */
        hideError: function() {
            if (DOM.error) {
                DOM.error.classList.add('hidden');
            }
        },

        /**
         * 显示结果
         * @param {Object} data - 翻译结果数据
         */
        showResult: function(data) {
            this.hideLoading();
            this.hideError();
            if (DOM.result && DOM.resultText && DOM.resultSource) {
                DOM.resultText.textContent = data.translation || '';
                DOM.resultSource.textContent = data.source ? `来源: ${data.source}` : '';
                DOM.result.classList.remove('hidden');
            }
            if (DOM.emptyState) {
                DOM.emptyState.classList.add('hidden');
            }
            state.currentResult = data;
        },

        /**
         * 显示空状态
         */
        showEmptyState: function() {
            this.hideLoading();
            this.hideError();
            if (DOM.result) {
                DOM.result.classList.add('hidden');
            }
            if (DOM.emptyState) {
                DOM.emptyState.classList.remove('hidden');
            }
            state.currentResult = null;
        },

        /**
         * 更新字符计数
         */
        updateCharCount: function() {
            if (DOM.input && DOM.charCount) {
                const length = DOM.input.value.length;
                DOM.charCount.textContent = `${length}/${CONFIG.maxInputLength}`;
                if (length > CONFIG.maxInputLength) {
                    DOM.charCount.classList.add('text-danger');
                } else {
                    DOM.charCount.classList.remove('text-danger');
                }
            }
        },

        /**
         * 清空输入
         */
        clearInput: function() {
            if (DOM.input) {
                DOM.input.value = '';
                this.updateCharCount();
                this.showEmptyState();
                DOM.input.focus();
            }
        },

        /**
         * 复制结果到剪贴板
         */
        copyResult: async function() {
            if (state.currentResult && DOM.resultText) {
                try {
                    await navigator.clipboard.writeText(state.currentResult.translation);
                    if (DOM.copyBtn) {
                        DOM.copyBtn.textContent = '已复制';
                        setTimeout(() => {
                            DOM.copyBtn.textContent = '复制';
                        }, 2000);
                    }
                } catch (err) {
                    console.error('复制失败:', err);
                }
            }
        },

        /**
         * 格式化时间
         * @param {string} dateStr - ISO日期字符串
         * @returns {string} 格式化后的时间
         */
        formatTime: function(dateStr) {
            try {
                const date = new Date(dateStr);
                const now = new Date();
                const diff = now - date;
                
                if (diff < 60000) {
                    return '刚刚';
                } else if (diff < 3600000) {
                    return `${Math.floor(diff / 60000)}分钟前`;
                } else if (diff < 86400000) {
                    return `${Math.floor(diff / 3600000)}小时前`;
                } else {
                    return `${date.getMonth() + 1}月${date.getDate()}日`;
                }
            } catch (e) {
                return dateStr;
            }
        },

        /**
         * 高亮搜索关键词
         * @param {string} text - 原始文本
         * @param {string} keyword - 关键词
         * @returns {string} 高亮后的HTML
         */
        highlightKeyword: function(text, keyword) {
            if (!keyword) return text;
            const regex = new RegExp(`(${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
            return text.replace(regex, '<mark>$1</mark>');
        }
    };

    // ============================================================
    // API 调用
    // ============================================================
    const api = {
        /**
         * 翻译请求
         * @param {string} text - 要翻译的文本
         * @returns {Promise<Object>} 翻译结果
         */
        translate: async function(text) {
            const response = await fetch(CONFIG.apiEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ text: text })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `请求失败 (${response.status})`);
            }

            return await response.json();
        },

        /**
         * 获取历史记录
         * @returns {Promise<Array>} 历史记录列表
         */
        getHistory: async function() {
            const response = await fetch(CONFIG.historyEndpoint);
            if (!response.ok) {
                throw new Error('获取历史记录失败');
            }
            return await response.json();
        },

        /**
         * 获取热门术语
         * @returns {Promise<Array>} 热门术语列表
         */
        getHotTerms: async function() {
            const response = await fetch(CONFIG.hotTermsEndpoint);
            if (!response.ok) {
                throw new Error('获取热门术语失败');
            }
            return await response.json();
        },

        /**
         * 清除历史记录
         * @returns {Promise<void>}
         */
        clearHistory: async function() {
            const response = await fetch(CONFIG.historyEndpoint, {
                method: 'DELETE'
            });
            if (!response.ok) {
                throw new Error('清除历史记录失败');
            }
        }
    };

    // ============================================================
    // 核心功能
    // ============================================================
    const app = {
        /**
         * 执行翻译
         */
        performTranslate: async function() {
            if (state.isTranslating) return;

            const text = DOM.input ? DOM.input.value.trim() : '';
            
            if (!text) {
                utils.showEmptyState();
                return;
            }

            if (text.length > CONFIG.maxInputLength) {
                utils.showError(`输入内容不能超过${CONFIG.maxInputLength}个字符`);
                return;
            }

            state.isTranslating = true;
            if (DOM.translateBtn) {
                DOM.translateBtn.disabled = true;
                DOM.translateBtn.textContent = '翻译中...';
            }

            utils.showLoading();

            try {
                const result = await api.translate(text);
                utils.showResult(result);
                await app.loadHistory();
            } catch (error) {
                console.error('翻译失败:', error);
                utils.showError(error.message || '翻译失败，请稍后重试');
            } finally {
                state.isTranslating = false;
                if (DOM.translateBtn) {
                    DOM.translateBtn.disabled = false;
                    DOM.translateBtn.textContent = '翻译';
                }
            }
        },

        /**
         * 加载历史记录
         */
        loadHistory: async function() {
            try {
                const history = await api.getHistory();
                state.history = history.slice(0, CONFIG.maxHistoryItems);
                app.renderHistory();
            } catch (error) {
                console.error('加载历史记录失败:', error);
            }
        },

        /**
         * 渲染历史记录
         */
        renderHistory: function() {
            if (!DOM.historyList) return;

            if (state.history.length === 0) {
                DOM.historyList.innerHTML = '<div class="text-muted text-center py-3">暂无历史记录</div>';
                return;
            }

            DOM.historyList.innerHTML = state.history.map(item => `
                <div class="history-item" data-id="${item.id}">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="history-content flex-grow-1">
                            <div class="history-original text-truncate">
                                <strong>原文：</strong>${utils.highlightKeyword(item.original_text, DOM.input ? DOM.input.value.trim() : '')}
                            </div>
                            <div class="history-translation text-truncate">
                                <strong>译文：</strong>${item.translation}
                            </div>
                            <div class="history-meta text-muted small">
                                <span>${utils.formatTime(item.created_at)}</span>
                                ${item.source ? `<span class="ms-2">来源: ${item.source}</span>` : ''}
                            </div>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary ms-2 history-use-btn" 
                                data-text="${item.original_text}">
                            使用
                        </button>
                    </div>
                </div>
            `).join('');

            // 绑定历史记录使用按钮事件
            DOM.historyList.querySelectorAll('.history-use-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    const text = this.getAttribute('data-text');
                    if (DOM.input) {
                        DOM.input.value = text;
                        utils.updateCharCount();
                        app.performTranslate();
                    }
                });
            });
        },

        /**
         * 加载热门术语
         */
        loadHotTerms: async function() {
            try {
                const terms = await api.getHotTerms();
                state.hotTerms = terms.slice(0, CONFIG.hotTermsCount);
                app.renderHotTerms();
            } catch (error) {
                console.error('加载热门术语失败:', error);
            }
        },

        /**
         * 渲染热门术语
         */
        renderHotTerms: function() {
            if (!DOM.hotTermsContainer) return;

            if (state.hotTerms.length === 0) {
                DOM.hotTermsContainer.innerHTML = '<div class="text-muted text-center py-2">暂无热门术语</div>';
                return;
            }

            DOM.hotTermsContainer.innerHTML = state.hotTerms.map(term => `
                <span class="badge bg-light text-dark me-2 mb-2 hot-term-badge" 
                      data-term="${term.term}"
                      role="button"
                      title="${term.definition || ''}">
                    ${term.term}
                    ${term.count ? `<small class="ms-1 text-muted">(${term.count})</small>` : ''}
                </span>
            `).join('');

            // 绑定热门术语点击事件
            DOM.hotTermsContainer.querySelectorAll('.hot-term-badge').forEach(badge => {
                badge.addEventListener('click', function() {
                    const term = this.getAttribute('data-term');
                    if (DOM.input) {
                        DOM.input.value = term;
                        utils.updateCharCount();
                        app.performTranslate();
                    }
                });
            });
        },

        /**
         * 清除历史记录
         */
        clearHistory: async function() {
            try {
                await api.clearHistory();
                state.history = [];
                app.renderHistory();
                // 显示成功提示
                if (DOM.clearHistoryBtn) {
                    const originalText = DOM.clearHistoryBtn.textContent;
                    DOM.clearHistoryBtn.textContent = '已清除';
                    setTimeout(() => {
                        DOM.clearHistoryBtn.textContent = originalText;
                    }, 2000);
                }
            } catch (error) {
                console.error('清除历史记录失败:', error);
                utils.showError('清除历史记录失败');
            }
        },

        /**
         * 初始化事件绑定
         */
        initEventListeners: function() {
            // 翻译按钮点击事件
            if (DOM.translateBtn) {
                DOM.translateBtn.addEventListener('click', () => {
                    app.performTranslate();
                });
            }

            // 输入框事件
            if (DOM.input) {
                // 输入事件 - 实时更新字符计数和防抖翻译
                DOM.input.addEventListener('input', () => {
                    utils.updateCharCount();
                    
                    // 清除之前的防抖定时器
                    if (state.debounceTimer) {
                        clearTimeout(state.debounceTimer);
                    }
                    
                    // 设置新的防抖定时器
                    state.debounceTimer = setTimeout(() => {
                        const text = DOM.input.value.trim();
                        if (text.length >= CONFIG.minInputLength) {
                            app.performTranslate();
                        } else {
                            utils.showEmptyState();
                        }
                    }, CONFIG.debounceDelay);
                });

                // 回车键触发翻译
                DOM.input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        if (state.debounceTimer) {
                            clearTimeout(state.debounceTimer);
                        }
                        app.performTranslate();
                    }
                });

                // 焦点事件
                DOM.input.addEventListener('focus', () => {
                    // 可以在这里添加额外的UI反馈
                });
            }

            // 清空输入按钮
            if (DOM.clearInputBtn) {
                DOM.clearInputBtn.addEventListener('click', () => {
                    utils.clearInput();
                });
            }

            // 复制结果按钮
            if (DOM.copyBtn) {
                DOM.copyBtn.addEventListener('click', () => {
                    utils.copyResult();
                });
            }

            // 清除历史记录按钮
            if (DOM.clearHistoryBtn) {
                DOM.clearHistoryBtn.addEventListener('click', () => {
                    if (confirm('确定要清除所有历史记录吗？')) {
                        app.clearHistory();
                    }
                });
            }

            // 错误关闭按钮
            const errorCloseBtn = document.querySelector('#jargon-error .btn-close');
            if (errorCloseBtn) {
                errorCloseBtn.addEventListener('click', () => {
                    utils.hideError();
                });
            }
        },

        /**
         * 初始化应用
         */
        init: async function() {
            try {
                // 初始化字符计数
                utils.updateCharCount();
                
                // 显示空状态
                utils.showEmptyState();
                
                // 加载历史记录
                await app.loadHistory();
                
                // 加载热门术语
                await app.loadHotTerms();
                
                // 初始化事件绑定
                app.initEventListeners();
                
                console.log('黑话翻译器初始化完成');
            } catch (error) {
                console.error('初始化失败:', error);
                utils.showError('初始化失败，请刷新页面重试');
            }
        }
    };

    // ============================================================
    // 启动应用
    // ============================================================
    // 等待DOM完全加载后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            app.init();
        });
    } else {
        app.init();
    }

})();