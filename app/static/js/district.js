```javascript
/**
 * district.js - 划片查询前端交互脚本
 * 成都K12升学参谋 - 政策查询+诊断一站式解决方案
 * 
 * 功能：地址输入、自动补全、结果展示、学区划片查询、地图集成
 * Issue #27: Task B - 产品闭环整合
 */

(function() {
    'use strict';

    // ============================================================
    // 配置常量
    // ============================================================
    const CONFIG = {
        // API 端点
        API_BASE: '/api/v1',
        AUTOCOMPLETE_ENDPOINT: '/district/autocomplete',
        QUERY_ENDPOINT: '/district/query',
        DIAGNOSIS_ENDPOINT: '/diagnosis/start',
        
        // 自动补全延迟（毫秒）
        AUTOCOMPLETE_DELAY: 300,
        
        // 最小输入字符数
        MIN_INPUT_LENGTH: 2,
        
        // 最大结果数
        MAX_RESULTS: 10,
        
        // 选择器
        SELECTORS: {
            addressInput: '#address-input',
            autocompleteList: '#autocomplete-list',
            searchButton: '#search-btn',
            resultContainer: '#result-container',
            loadingIndicator: '#loading-indicator',
            errorMessage: '#error-message',
            schoolList: '#school-list',
            districtInfo: '#district-info',
            mapContainer: '#map-container',
            clearButton: '#clear-btn',
            recentSearches: '#recent-searches',
            searchForm: '#search-form',
            addressDetail: '#address-detail',
            schoolCard: '.school-card',
            districtBoundary: '#district-boundary',
            diagnosisButton: '#diagnosis-btn',
            historyList: '#history-list',
            paginationContainer: '#pagination-container',
            resultCount: '#result-count',
            highlightToggle: '#highlight-toggle',
            mapToggle: '#map-toggle'
        },

        // 地图配置
        MAP: {
            center: [30.5728, 104.0668], // 成都中心坐标
            zoom: 12,
            maxZoom: 18,
            minZoom: 10,
            tileLayer: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
            markerIcon: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
            markerIconRetina: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
            markerShadow: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png'
        },

        // 本地存储键
        STORAGE_KEYS: {
            recentSearches: 'cd_shengxuewa_recent_searches',
            userPreferences: 'cd_shengxuewa_user_prefs',
            searchHistory: 'cd_shengxuewa_search_history'
        },

        // 最近搜索最大数量
        MAX_RECENT_SEARCHES: 5,

        // 地址验证正则
        ADDRESS_PATTERN: /^[\u4e00-\u9fa5a-zA-Z0-9\s\-#（）()]+$/,

        // 门牌号验证
        DOOR_PATTERN: /^\d+[#\-]?\d*$|^\d+号$/,

        // 高亮颜色
        HIGHLIGHT_COLORS: {
            primary: '#FFD700',
            secondary: '#FFA500',
            tertiary: '#FF6347'
        },

        // 错误消息
        ERROR_MESSAGES: {
            network: '网络连接失败，请检查网络后重试',
            server: '服务器错误，请稍后重试',
            invalidInput: '请输入有效的地址信息',
            noResults: '未找到匹配的学区信息',
            mapLoadFailed: '地图加载失败，请刷新页面重试',
            diagnosisFailed: '诊断启动失败，请稍后重试'
        }
    };

    // ============================================================
    // 状态管理
    // ============================================================
    const State = {
        currentQuery: '',
        autocompleteTimer: null,
        isSearching: false,
        selectedAddress: null,
        results: [],
        map: null,
        mapMarkers: [],
        mapInitialized: false,
        currentPage: 1,
        totalPages: 1,
        pageSize: 10,
        searchHistory: [],
        highlightEnabled: true,
        mapVisible: false
    };

    // ============================================================
    // DOM 缓存
    // ============================================================
    let DOM = {};

    /**
     * 初始化 DOM 缓存
     */
    function initDOM() {
        const selectors = CONFIG.SELECTORS;
        DOM = {
            addressInput: document.querySelector(selectors.addressInput),
            autocompleteList: document.querySelector(selectors.autocompleteList),
            searchButton: document.querySelector(selectors.searchButton),
            resultContainer: document.querySelector(selectors.resultContainer),
            loadingIndicator: document.querySelector(selectors.loadingIndicator),
            errorMessage: document.querySelector(selectors.errorMessage),
            schoolList: document.querySelector(selectors.schoolList),
            districtInfo: document.querySelector(selectors.districtInfo),
            mapContainer: document.querySelector(selectors.mapContainer),
            clearButton: document.querySelector(selectors.clearButton),
            recentSearches: document.querySelector(selectors.recentSearches),
            searchForm: document.querySelector(selectors.searchForm),
            addressDetail: document.querySelector(selectors.addressDetail),
            districtBoundary: document.querySelector(selectors.districtBoundary),
            diagnosisButton: document.querySelector(selectors.diagnosisButton),
            historyList: document.querySelector(selectors.historyList),
            paginationContainer: document.querySelector(selectors.paginationContainer),
            resultCount: document.querySelector(selectors.resultCount),
            highlightToggle: document.querySelector(selectors.highlightToggle),
            mapToggle: document.querySelector(selectors.mapToggle)
        };
    }

    /**
     * 检查所有必需的 DOM 元素是否存在
     * @returns {boolean} 是否所有必需元素都存在
     */
    function checkRequiredElements() {
        const required = ['addressInput', 'searchButton', 'resultContainer', 'loadingIndicator', 'errorMessage'];
        for (const key of required) {
            if (!DOM[key]) {
                console.error(`[district.js] 必需元素 ${key} 未找到`);
                return false;
            }
        }
        return true;
    }

    // ============================================================
    // 工具函数
    // ============================================================

    /**
     * 防抖函数
     * @param {Function} func - 要执行的函数
     * @param {number} delay - 延迟时间（毫秒）
     * @returns {Function} 防抖后的函数
     */
    function debounce(func, delay) {
        let timer = null;
        return function(...args) {
            if (timer) {
                clearTimeout(timer);
            }
            timer = setTimeout(() => {
                func.apply(this, args);
                timer = null;
            }, delay);
        };
    }

    /**
     * 显示加载状态
     */
    function showLoading() {
        if (DOM.loadingIndicator) {
            DOM.loadingIndicator.style.display = 'block';
        }
        if (DOM.searchButton) {
            DOM.searchButton.disabled = true;
            DOM.searchButton.innerHTML = '<span class="spinner"></span> 查询中...';
        }
    }

    /**
     * 隐藏加载状态
     */
    function hideLoading() {
        if (DOM.loadingIndicator) {
            DOM.loadingIndicator.style.display = 'none';
        }
        if (DOM.searchButton) {
            DOM.searchButton.disabled = false;
            DOM.searchButton.innerHTML = '<i class="fas fa-search"></i> 查询';
        }
    }

    /**
     * 显示错误消息
     * @param {string} message - 错误消息
     */
    function showError(message) {
        if (DOM.errorMessage) {
            DOM.errorMessage.textContent = message;
            DOM.errorMessage.style.display = 'block';
            DOM.errorMessage.classList.add('fade-in');
            setTimeout(() => {
                DOM.errorMessage.classList.remove('fade-in');
            }, 300);
        }
    }

    /**
     * 隐藏错误消息
     */
    function hideError() {
        if (DOM.errorMessage) {
            DOM.errorMessage.style.display = 'none';
            DOM.errorMessage.textContent = '';
        }
    }

    /**
     * 显示结果容器
     */
    function showResultContainer() {
        if (DOM.resultContainer) {
            DOM.resultContainer.style.display = 'block';
            DOM.resultContainer.classList.add('fade-in');
        }
    }

    /**
     * 隐藏结果容器
     */
    function hideResultContainer() {
        if (DOM.resultContainer) {
            DOM.resultContainer.style.display = 'none';
        }
    }

    /**
     * 验证地址输入
     * @param {string} address - 地址字符串
     * @returns {boolean} 是否有效
     */
    function validateAddress(address) {
        if (!address || address.trim().length < CONFIG.MIN_INPUT_LENGTH) {
            return false;
        }
        return CONFIG.ADDRESS_PATTERN.test(address.trim());
    }

    /**
     * 格式化地址显示
     * @param {Object} address - 地址对象
     * @returns {string} 格式化后的地址字符串
     */
    function formatAddress(address) {
        if (!address) return '';
        const parts = [];
        if (address.district) parts.push(address.district);
        if (address.street) parts.push(address.street);
        if (address.door) parts.push(address.door + '号');
        return parts.join(' ');
    }

    /**
     * 高亮搜索结果中的匹配文本
     * @param {string} text - 原始文本
     * @param {string} query - 查询关键词
     * @returns {string} 高亮后的HTML
     */
    function highlightText(text, query) {
        if (!query || !text) return text || '';
        const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escapedQuery})`, 'gi');
        return text.replace(regex, '<mark class="highlight">$1</mark>');
    }

    // ============================================================
    // 本地存储管理
    // ============================================================

    /**
     * 从本地存储获取最近搜索
     * @returns {Array} 最近搜索列表
     */
    function getRecentSearches() {
        try {
            const data = localStorage.getItem(CONFIG.STORAGE_KEYS.recentSearches);
            return data ? JSON.parse(data) : [];
        } catch (e) {
            console.error('[district.js] 读取本地存储失败:', e);
            return [];
        }
    }

    /**
     * 保存最近搜索到本地存储
     * @param {Array} searches - 搜索列表
     */
    function saveRecentSearches(searches) {
        try {
            localStorage.setItem(CONFIG.STORAGE_KEYS.recentSearches, JSON.stringify(searches));
        } catch (e) {
            console.error('[district.js] 保存本地存储失败:', e);
        }
    }

    /**
     * 添加搜索记录
     * @param {string} query - 搜索关键词
     * @param {Object} result - 搜索结果
     */
    function addToRecentSearches(query, result) {
        let searches = getRecentSearches();
        const searchEntry = {
            query: query,
            result: result,
            timestamp: new Date().toISOString()
        };
        
        // 移除重复项
        searches = searches.filter(s => s.query !== query);
        
        // 添加到开头
        searches.unshift(searchEntry);
        
        // 限制数量
        if (searches.length > CONFIG.MAX_RECENT_SEARCHES) {
            searches = searches.slice(0, CONFIG.MAX_RECENT_SEARCHES);
        }
        
        saveRecentSearches(searches);
        renderRecentSearches();
    }

    /**
     * 渲染最近搜索列表
     */
    function renderRecentSearches() {
        if (!DOM.recentSearches) return;
        
        const searches = getRecentSearches();
        if (searches.length === 0) {
            DOM.recentSearches.style.display = 'none';
            return;
        }
        
        DOM.recentSearches.style.display = 'block';
        DOM.recentSearches.innerHTML = `
            <h4 class="recent-searches-title">最近搜索</h4>
            <ul class="recent-searches-list">
                ${searches.map((s, index) => `
                    <li class="recent-search-item" data-index="${index}">
                        <span class="recent-search-query">${escapeHtml(s.query)}</span>
                        <span class="recent-search-time">${formatTimeAgo(s.timestamp)}</span>
                    </li>
                `).join('')}
            </ul>
        `;
        
        // 绑定点击事件
        DOM.recentSearches.querySelectorAll('.recent-search-item').forEach(item => {
            item.addEventListener('click', function() {
                const index = parseInt(this.dataset.index);
                const searches = getRecentSearches();
                if (searches[index]) {
                    DOM.addressInput.value = searches[index].query;
                    handleSearch(searches[index].query);
                }
            });
        });
    }

    /**
     * 转义HTML特殊字符
     * @param {string} text - 原始文本
     * @returns {string} 转义后的文本
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * 格式化时间显示（显示为多久以前）
     * @param {string} timestamp - ISO时间戳
     * @returns {string} 格式化后的时间字符串
     */
    function formatTimeAgo(timestamp) {
        const now = new Date();
        const date = new Date(timestamp);
        const diff = now - date;
        
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);
        
        if (minutes < 1) return '刚刚';
        if (minutes < 60) return `${minutes}分钟前`;
        if (hours < 24) return `${hours}小时前`;
        if (days < 7) return `${days}天前`;
        return date.toLocaleDateString('zh-CN');
    }

    // ============================================================
    // API 调用
    // ============================================================

    /**
     * 发送API请求
     * @param {string} endpoint - API端点
     * @param {Object} params - 查询参数
     * @returns {Promise} 请求结果
     */
    async function apiRequest(endpoint, params = {}) {
        const url = new URL(`${CONFIG.API_BASE}${endpoint}`, window.location.origin);
        Object.keys(params).forEach(key => {
            if (params[key] !== undefined && params[key] !== null) {
                url.searchParams.append(key, params[key]);
            }
        });
        
        try {
            const response = await fetch(url.toString(), {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || CONFIG.ERROR_MESSAGES.server);
            }
            
            return await response.json();
        } catch (error) {
            if (error.name === 'TypeError' && error.message.includes('fetch')) {
                throw new Error(CONFIG.ERROR_MESSAGES.network);
            }
            throw error;
        }
    }

    /**
     * 获取自动补全建议
     * @param {string} query - 查询关键词
     * @returns {Promise<Array>} 建议列表
     */
    async function fetchAutocomplete(query) {
        const data = await apiRequest(CONFIG.AUTOCOMPLETE_ENDPOINT, {
            q: query,
            limit: CONFIG.MAX_RESULTS
        });
        return data.suggestions || [];
    }

    /**
     * 执行学区查询
     * @param {string} address - 地址
     * @param {number} page - 页码
     * @param {number} pageSize - 每页数量
     * @returns {Promise<Object>} 查询结果
     */
    async function fetchDistrictQuery(address, page = 1, pageSize = 10) {
        return await apiRequest(CONFIG.QUERY_ENDPOINT, {
            address: address,
            page: page,
            page_size: pageSize
        });
    }

    /**
     * 启动诊断
     * @param {Object} districtData - 学区数据
     * @returns {Promise<Object>} 诊断结果
     */
    async function startDiagnosis(districtData) {
        try {
            const response = await fetch(`${CONFIG.API_BASE}${CONFIG.DIAGNOSIS_ENDPOINT}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    district_id: districtData.id,
                    school_ids: districtData.schools.map(s => s.id),
                    address: districtData.address
                })
            });
            
            if (!response.ok) {
                throw new Error(CONFIG.ERROR_MESSAGES.diagnosisFailed);
            }
            
            return await response.json();
        } catch (error) {
            console.error('[district.js] 诊断启动失败:', error);
            throw error;
        }
    }

    // ============================================================
    // 自动补全功能
    // ============================================================

    /**
     * 处理自动补全输入
     */
    const handleAutocompleteInput = debounce(async function() {
        const query = DOM.addressInput.value.trim();
        
        if (query.length < CONFIG.MIN_INPUT_LENGTH) {
            hideAutocomplete();
            return;
        }
        
        try {
            const suggestions = await fetchAutocomplete(query);
            renderAutocomplete(suggestions, query);
        } catch (error) {
            console.error('[district.js] 自动补全失败:', error);
            hideAutocomplete();
        }
    }, CONFIG.AUTOCOMPLETE_DELAY);

    /**
     * 渲染自动补全列表
     * @param {Array} suggestions - 建议列表
     * @param {string} query - 查询关键词
     */
    function renderAutocomplete(suggestions, query) {
        if (!DOM.autocompleteList) return;
        
        if (!suggestions || suggestions.length === 0) {
            hideAutocomplete();
            return;
        }
        
        DOM.autocompleteList.innerHTML = suggestions.map(s => `
            <div class="autocomplete-item" data-address="${escapeHtml(s.address)}">
                <div class="autocomplete-address">${highlightText(s.address, query)}</div>
                <div class="autocomplete-detail">
                    <span class="autocomplete-district">${escapeHtml(s.district || '')}</span>
                    <span class="autocomplete-school">${escapeHtml(s.school || '')}</span>
                </div>
            </div>
        `).join('');
        
        DOM.autocompleteList.style.display = 'block';
        
        // 绑定点击事件
        DOM.autocompleteList.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', function() {
                const address = this.dataset.address;
                DOM.addressInput.value = address;
                hideAutocomplete();
                handleSearch(address);
            });
        });
    }

    /**
     * 隐藏自动补全列表
     */
    function hideAutocomplete() {
        if (DOM.autocompleteList) {
            DOM.autocompleteList.style.display = 'none';
            DOM.autocompleteList.innerHTML = '';
        }
    }

    // ============================================================
    // 搜索功能
    // ============================================================

    /**
     * 处理搜索
     * @param {string} query - 查询关键词
     */
    async function handleSearch(query) {
        if (!query) {
            query = DOM.addressInput.value.trim();
        }
        
        if (!validateAddress(query)) {
            showError(CONFIG.ERROR_MESSAGES.invalidInput);
            return;
        }
        
        if (State.isSearching) return;
        
        State.isSearching = true;
        State.currentQuery = query;
        State.currentPage = 1;
        
        hideError();
        showLoading();
        hideResultContainer();
        
        try {
            const result = await fetchDistrictQuery(query, State.currentPage, State.pageSize);
            State.results = result;
            State.totalPages = result.total_pages || 1;
            
            if (result.schools && result.schools.length > 0) {
                renderResults(result, query);
                addToRecentSearches(query, result);
                showResultContainer();
                
                if (State.mapVisible) {
                    updateMap(result);
                }
            } else {
                showError(CONFIG.ERROR_MESSAGES.noResults);
            }
        } catch (error) {
            console.error('[district.js] 查询失败:', error);
            showError(error.message || CONFIG.ERROR_MESSAGES.server);
        } finally {
            State.isSearching = false;
            hideLoading();
        }
    }

    /**
     * 渲染搜索结果
     * @param {Object} result - 查询结果
     * @param {string} query - 查询关键词
     */
    function renderResults(result, query) {
        // 更新结果计数
        if (DOM.resultCount) {
            DOM.resultCount.textContent = `找到 ${result.total || 0} 个结果`;
        }
        
        // 渲染学区信息
        if (DOM.districtInfo && result.district) {
            DOM.districtInfo.innerHTML = `
                <div class="district-info-card">
                    <h3 class="district-name">${highlightText(result.district.name, query)}</h3>
                    <div class="district-details">
                        <p><strong>所属区域：</strong>${escapeHtml(result.district.area || '')}</p>
                        <p><strong>学区范围：</strong>${escapeHtml(result.district.range || '')}</p>
                        <p><strong>对口学校：</strong>${result.schools ? result.schools.length : 0}所</p>
                    </div>
                </div>
            `;
        }
        
        // 渲染学校列表
        if (DOM.schoolList && result.schools) {
            DOM.schoolList.innerHTML = result.schools.map((school, index) => `
                <div class="school-card ${State.highlightEnabled ? 'highlightable' : ''}" 
                     data-school-id="${school.id}"
                     style="animation-delay: ${index * 0.1}s">
                    <div class="school-header">
                        <h4 class="school-name">${highlightText(school.name, query)}</h4>
                        <span class="school-type ${school.type}">${getSchoolTypeLabel(school.type)}</span>
                    </div>
                    <div class="school-info">
                        <p><i class="fas fa-map-marker-alt"></i> ${escapeHtml(school.address || '')}</p>
                        <p><i class="fas fa-phone"></i> ${escapeHtml(school.phone || '暂无')}</p>
                        <p><i class="fas fa-star"></i> 评级：${getRatingStars(school.rating || 0)}</p>
                    </div>
                    <div class="school-actions">
                        <button class="btn btn-sm btn-outline-primary view-detail-btn" 
                                data-school-id="${school.id}">
                            查看详情
                        </button>
                        <button class="btn btn-sm btn-primary diagnosis-btn" 
                                data-school-id="${school.id}">
                            诊断分析
                        </button>
                    </div>
                </div>
            `).join('');
            
            // 绑定学校卡片事件
            bindSchoolCardEvents();
        }
        
        // 渲染分页
        renderPagination(result);
        
        // 渲染地址详情
        if (DOM.addressDetail && result.address) {
            DOM.addressDetail.innerHTML = `
                <div class="address-detail-card">
                    <h4>查询地址</h4>
                    <p>${escapeHtml(formatAddress(result.address))}</p>
                    <p class="address-coordinates" data-lat="${result.address.lat || ''}" 
                       data-lng="${result.address.lng || ''}">
                        坐标：${result.address.lat ? result.address.lat.toFixed(6) : '未知'}, 
                        ${result.address.lng ? result.address.lng.toFixed(6) : '未知'}
                    </p>
                </div>
            `;
        }
    }

    /**
     * 获取学校类型标签
     * @param {string} type - 学校类型
     * @returns {string} 类型标签
     */
    function getSchoolTypeLabel(type) {
        const labels = {
            'primary': '小学',
            'middle': '初中',
            'high': '高中',
            'nine_year': '九年一贯制',
            'kindergarten': '幼儿园'
        };
        return labels[type] || type || '未知';
    }

    /**
     * 获取评级星星HTML
     * @param {number} rating - 评级（1-5）
     * @returns {string} 星星HTML
     */
    function getRatingStars(rating) {
        const fullStars = Math.floor(rating);
        const halfStar = rating % 1 >= 0.5;
        const emptyStars = 5 - fullStars - (halfStar ? 1 : 0);
        
        let stars = '';
        for (let i = 0; i < fullStars; i++) {
            stars += '<i class="fas fa-star"></i>';
        }
        if (halfStar) {
            stars += '<i class="fas fa-star-half-alt"></i>';
        }
        for (let i = 0; i < emptyStars; i++) {
            stars += '<i class="far fa-star"></i>';
        }
        return stars;
    }

    /**
     * 绑定学校卡片事件
     */
    function bindSchoolCardEvents() {
        // 查看详情按钮
        document.querySelectorAll('.view-detail-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const schoolId = this.dataset.schoolId;
                showSchoolDetail(schoolId);
            });
        });
        
        // 诊断按钮
        document.querySelectorAll('.diagnosis-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const schoolId = this.dataset.schoolId;
                handleDiagnosis(schoolId);
            });
        });
        
        // 学校卡片点击
        document.querySelectorAll('.school-card').forEach(card => {
            card.addEventListener('click', function(e) {
                if (e.target.closest('button')) return;
                this.classList.toggle('expanded');
            });
        });
    }

    /**
     * 显示学校详情
     * @param {number} schoolId - 学校ID
     */
    function showSchoolDetail(schoolId) {
        const school = State.results.schools.find(s => s.id == schoolId);
        if (!school) return;
        
        // 创建模态框
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">${escapeHtml(school.name)}</h5>
                        <button type="button" class="close" data-dismiss="modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="school-detail-grid">
                            <div class="detail-item">
                                <label>学校类型</label>
                                <span>${getSchoolTypeLabel(school.type)}</span>
                            </div>
                            <div class="detail-item">
                                <label>地址</label>
                                <span>${escapeHtml(school.address || '暂无')}</span>
                            </div>
                            <div class="detail-item">
                                <label>联系电话</label>
                                <span>${escapeHtml(school.phone || '暂无')}</span>
                            </div>
                            <div class="detail-item">
                                <label>评级</label>
                                <span>${getRatingStars(school.rating || 0)}</span>
                            </div>
                            <div class="detail-item full-width">
                                <label>简介</label>
                                <p>${escapeHtml(school.description || '暂无简介')}</p>
                            </div>
                            <div class="detail-item full-width">
                                <label>划片范围</label>
                                <p>${escapeHtml(school.district_range || '暂无信息')}</p>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-primary diagnosis-btn" 
                                data-school-id="${school.id}">
                            诊断分析
                        </button>
                        <button type="button" class="btn btn-secondary" data-dismiss="modal">关闭</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        $(modal).modal('show');
        
        // 绑定诊断按钮
        modal.querySelector('.diagnosis-btn').addEventListener('click', function() {
            $(modal).modal('hide');
            handleDiagnosis(schoolId);
        });
        
        // 模态框关闭后移除
        $(modal).on('hidden.bs.modal', function() {
            modal.remove();
        });
    }

    /**
     * 处理诊断
     * @param {number} schoolId - 学校ID
     */
    async function handleDiagnosis(schoolId) {
        try {
            showLoading();
            const districtData = {
                id: State.results.district.id,
                address: State.currentQuery,
                schools: State.results.schools
            };
            
            const diagnosisResult = await startDiagnosis(districtData);
            
            // 跳转到诊断页面
            if (diagnosisResult.redirect_url) {
                window.location.href = diagnosisResult.redirect_url;
            } else {
                // 显示诊断结果
                showDiagnosisResult(diagnosisResult);
            }
        } catch (error) {
            console.error('[district.js] 诊断失败:', error);
            showError(error.message || CONFIG.ERROR_MESSAGES.diagnosisFailed);
        } finally {
            hideLoading();
        }
    }

    /**
     * 显示诊断结果
     * @param {Object} result - 诊断结果
     */
    function showDiagnosisResult(result) {
        // 创建诊断结果模态框
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">诊断分析结果</h5>
                        <button type="button" class="close" data-dismiss="modal">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="diagnosis-result">
                            <div class="diagnosis-summary">
                                <h4>${escapeHtml(result.title || '升学诊断报告')}</h4>
                                <p class="diagnosis-score">
                                    综合评分：<span class="score">${result.score || 0}</span>分
                                </p>
                            </div>
                            <div class="diagnosis-details">
                                ${result.details ? result.details.map(detail => `
                                    <div class="diagnosis-item">
                                        <h5>${escapeHtml(detail.title)}</h5>
                                        <p>${escapeHtml(detail.description)}</p>
                                        <div class="progress">
                                            <div class="progress-bar" style="width: ${detail.score}%">
                                                ${detail.score}%
                                            </div>
                                        </div>
                                    </div>
                                `).join('') : '<p>暂无详细分析</p>'}
                            </div>
                            <div class="diagnosis-recommendations">
                                <h4>建议</h4>
                                <ul>
                                    ${result.recommendations ? result.recommendations.map(rec => `
                                        <li>${escapeHtml(rec)}</li>
                                    `).join('') : '<li>暂无建议</li>'}
                                </ul>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-primary" onclick="window.print()">打印报告</button>
                        <button type="button" class="btn btn-secondary" data-dismiss="modal">关闭</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        $(modal).modal('show');
        
        $(modal).on('hidden.bs.modal', function() {
            modal.remove();
        });
    }

    // ============================================================
    // 分页功能
    // ============================================================

    /**
     * 渲染分页
     * @param {Object} result - 查询结果
     */
    function renderPagination(result) {
        if (!DOM.paginationContainer) return;
        
        const totalPages = result.total_pages || 1;
        const currentPage = result.page || 1;
        
        if (totalPages <= 1) {
            DOM.paginationContainer.innerHTML = '';
            return;
        }
        
        let paginationHTML = '<nav><ul class="pagination">';
        
        // 上一页
        paginationHTML += `
            <li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage - 1}">上一页</a>
            </li>
        `;
        
        // 页码
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, currentPage + 2);
        
        if (startPage > 1) {
            paginationHTML += `
                <li class="page-item">
                    <a class="page-link" href="#" data-page="1">1</a>
                </li>
            `;
            if (startPage > 2) {
                paginationHTML += '<li class="page-item disabled"><span class="page-link">...</span></li>';
            }
        }
        
        for (let i = startPage; i <= endPage; i++) {
            paginationHTML += `
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `;
        }
        
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                paginationHTML += '<li class="page-item disabled"><span class="page-link">...</span></li>';
            }
            paginationHTML += `
                <li class="page-item">
                    <a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a>
                </li>
            `;
        }
        
        // 下一页
        paginationHTML += `
            <li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${currentPage + 1}">下一页</a>
            </li>
        `;
        
        paginationHTML += '</ul></nav>';
        DOM.paginationContainer.innerHTML = paginationHTML;
        
        // 绑定分页事件
        DOM.paginationContainer.querySelectorAll('.page-link').forEach(link => {
           