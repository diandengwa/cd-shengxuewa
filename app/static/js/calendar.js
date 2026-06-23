```javascript
/**
 * 升学日历前端交互脚本
 * 包含时间线渲染、事件详情、筛选、提醒等功能
 * 用于成都K12升学参谋项目
 * 版本: 2.0.0
 */

// ============================================================
// 全局配置
// ============================================================
const CALENDAR_CONFIG = {
    apiBase: '/api/v1/calendar',
    dateFormat: 'YYYY-MM-DD',
    timeFormat: 'HH:mm',
    animationDuration: 300,
    pageSize: 20,
    defaultView: 'timeline', // timeline | list | month
    eventTypes: {
        policy: { label: '政策发布', color: '#1890ff', icon: '📋' },
        exam: { label: '考试安排', color: '#52c41a', icon: '📝' },
        registration: { label: '报名截止', color: '#faad14', icon: '⏰' },
        result: { label: '成绩公布', color: '#722ed1', icon: '📊' },
        consultation: { label: '咨询活动', color: '#13c2c2', icon: '💬' },
        other: { label: '其他', color: '#eb2f96', icon: '📌' }
    },
    storageKeys: {
        reminders: 'k12_calendar_reminders',
        viewPreference: 'k12_calendar_view',
        filterPreference: 'k12_calendar_filter'
    }
};

// ============================================================
// 工具函数
// ============================================================
const CalendarUtils = {
    /**
     * 格式化日期
     * @param {string|Date} date - 日期对象或字符串
     * @param {string} format - 格式模板
     * @returns {string} 格式化后的日期字符串
     */
    formatDate(date, format = CALENDAR_CONFIG.dateFormat) {
        try {
            if (!date) return '';
            const d = new Date(date);
            if (isNaN(d.getTime())) return '';
            
            const pad = (num) => String(num).padStart(2, '0');
            const map = {
                'YYYY': d.getFullYear(),
                'MM': pad(d.getMonth() + 1),
                'DD': pad(d.getDate()),
                'HH': pad(d.getHours()),
                'mm': pad(d.getMinutes()),
                'ss': pad(d.getSeconds())
            };
            
            return format.replace(/YYYY|MM|DD|HH|mm|ss/g, (match) => map[match]);
        } catch (error) {
            console.error('日期格式化失败:', error);
            return '';
        }
    },

    /**
     * 获取相对时间描述
     * @param {string|Date} date - 日期
     * @returns {string} 相对时间描述
     */
    getRelativeTime(date) {
        try {
            const now = new Date();
            const target = new Date(date);
            const diff = target - now;
            const days = Math.floor(diff / (1000 * 60 * 60 * 24));
            
            if (days < 0) return `已过${Math.abs(days)}天`;
            if (days === 0) return '今天';
            if (days === 1) return '明天';
            if (days <= 7) return `${days}天后`;
            if (days <= 30) return `${Math.floor(days / 7)}周后`;
            return `${Math.floor(days / 30)}个月后`;
        } catch (error) {
            console.error('获取相对时间失败:', error);
            return '';
        }
    },

    /**
     * 获取事件类型配置
     * @param {string} type - 事件类型
     * @returns {object} 事件类型配置
     */
    getEventTypeConfig(type) {
        return CALENDAR_CONFIG.eventTypes[type] || CALENDAR_CONFIG.eventTypes.other;
    },

    /**
     * 防抖函数
     * @param {Function} fn - 要执行的函数
     * @param {number} delay - 延迟时间(ms)
     * @returns {Function} 防抖后的函数
     */
    debounce(fn, delay = 300) {
        let timer = null;
        return function (...args) {
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => {
                fn.apply(this, args);
                timer = null;
            }, delay);
        };
    },

    /**
     * 显示加载状态
     * @param {HTMLElement} container - 容器元素
     * @param {boolean} show - 是否显示
     */
    toggleLoading(container, show) {
        if (!container) return;
        try {
            let loader = container.querySelector('.calendar-loading');
            
            if (show) {
                if (!loader) {
                    loader = document.createElement('div');
                    loader.className = 'calendar-loading';
                    loader.innerHTML = '<div class="loading-spinner"><i class="fas fa-spinner fa-spin"></i> 加载中...</div>';
                    container.appendChild(loader);
                }
                loader.style.display = 'flex';
            } else {
                if (loader) {
                    loader.style.display = 'none';
                }
            }
        } catch (error) {
            console.error('切换加载状态失败:', error);
        }
    },

    /**
     * 显示错误提示
     * @param {string} message - 错误消息
     * @param {number} duration - 显示时长(ms)
     */
    showError(message, duration = 3000) {
        try {
            const toast = document.createElement('div');
            toast.className = 'calendar-toast calendar-toast-error';
            toast.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
            document.body.appendChild(toast);
            
            setTimeout(() => {
                toast.classList.add('fade-out');
                setTimeout(() => toast.remove(), 300);
            }, duration);
        } catch (error) {
            console.error('显示错误提示失败:', error);
        }
    },

    /**
     * 显示成功提示
     * @param {string} message - 成功消息
     * @param {number} duration - 显示时长(ms)
     */
    showSuccess(message, duration = 2000) {
        try {
            const toast = document.createElement('div');
            toast.className = 'calendar-toast calendar-toast-success';
            toast.innerHTML = `<i class="fas fa-check-circle"></i> ${message}`;
            document.body.appendChild(toast);
            
            setTimeout(() => {
                toast.classList.add('fade-out');
                setTimeout(() => toast.remove(), 300);
            }, duration);
        } catch (error) {
            console.error('显示成功提示失败:', error);
        }
    }
};

// ============================================================
// 日历数据管理
// ============================================================
class CalendarDataManager {
    constructor() {
        this.events = [];
        this.filters = {
            types: Object.keys(CALENDAR_CONFIG.eventTypes),
            dateRange: { start: null, end: null },
            keyword: ''
        };
        this.currentPage = 1;
        this.totalPages = 1;
        this.reminders = this.loadReminders();
    }

    /**
     * 从本地存储加载提醒设置
     * @returns {Array} 提醒列表
     */
    loadReminders() {
        try {
            const stored = localStorage.getItem(CALENDAR_CONFIG.storageKeys.reminders);
            return stored ? JSON.parse(stored) : [];
        } catch (error) {
            console.error('加载提醒设置失败:', error);
            return [];
        }
    }

    /**
     * 保存提醒设置到本地存储
     */
    saveReminders() {
        try {
            localStorage.setItem(CALENDAR_CONFIG.storageKeys.reminders, JSON.stringify(this.reminders));
        } catch (error) {
            console.error('保存提醒设置失败:', error);
        }
    }

    /**
     * 从API获取事件列表
     * @param {object} params - 请求参数
     * @returns {Promise<Array>} 事件列表
     */
    async fetchEvents(params = {}) {
        try {
            const queryParams = new URLSearchParams({
                page: this.currentPage,
                page_size: CALENDAR_CONFIG.pageSize,
                ...params
            });

            // 添加筛选条件
            if (this.filters.types.length < Object.keys(CALENDAR_CONFIG.eventTypes).length) {
                queryParams.append('types', this.filters.types.join(','));
            }
            if (this.filters.dateRange.start) {
                queryParams.append('start_date', this.filters.dateRange.start);
            }
            if (this.filters.dateRange.end) {
                queryParams.append('end_date', this.filters.dateRange.end);
            }
            if (this.filters.keyword) {
                queryParams.append('keyword', this.filters.keyword);
            }

            const response = await fetch(`${CALENDAR_CONFIG.apiBase}/events?${queryParams}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            this.events = data.events || [];
            this.totalPages = data.total_pages || 1;
            this.currentPage = data.current_page || 1;

            return this.events;
        } catch (error) {
            console.error('获取事件列表失败:', error);
            CalendarUtils.showError('获取升学日历数据失败，请稍后重试');
            throw error;
        }
    }

    /**
     * 获取事件详情
     * @param {number} eventId - 事件ID
     * @returns {Promise<object>} 事件详情
     */
    async fetchEventDetail(eventId) {
        try {
            const response = await fetch(`${CALENDAR_CONFIG.apiBase}/events/${eventId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('获取事件详情失败:', error);
            CalendarUtils.showError('获取事件详情失败，请稍后重试');
            throw error;
        }
    }

    /**
     * 设置提醒
     * @param {number} eventId - 事件ID
     * @param {number} minutesBefore - 提前提醒分钟数
     * @returns {Promise<boolean>} 是否成功
     */
    async setReminder(eventId, minutesBefore = 30) {
        try {
            // 检查是否已设置提醒
            const existing = this.reminders.find(r => r.eventId === eventId);
            if (existing) {
                CalendarUtils.showSuccess('已设置过提醒');
                return true;
            }

            // 调用API设置提醒
            const response = await fetch(`${CALENDAR_CONFIG.apiBase}/reminders`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    event_id: eventId,
                    minutes_before: minutesBefore
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            
            // 保存到本地存储
            this.reminders.push({
                eventId,
                minutesBefore,
                createdAt: new Date().toISOString()
            });
            this.saveReminders();

            CalendarUtils.showSuccess('提醒设置成功');
            return true;
        } catch (error) {
            console.error('设置提醒失败:', error);
            CalendarUtils.showError('设置提醒失败，请稍后重试');
            return false;
        }
    }

    /**
     * 取消提醒
     * @param {number} eventId - 事件ID
     * @returns {Promise<boolean>} 是否成功
     */
    async cancelReminder(eventId) {
        try {
            // 调用API取消提醒
            const response = await fetch(`${CALENDAR_CONFIG.apiBase}/reminders/${eventId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            // 从本地存储移除
            this.reminders = this.reminders.filter(r => r.eventId !== eventId);
            this.saveReminders();

            CalendarUtils.showSuccess('提醒已取消');
            return true;
        } catch (error) {
            console.error('取消提醒失败:', error);
            CalendarUtils.showError('取消提醒失败，请稍后重试');
            return false;
        }
    }

    /**
     * 检查事件是否已设置提醒
     * @param {number} eventId - 事件ID
     * @returns {boolean} 是否已设置提醒
     */
    hasReminder(eventId) {
        return this.reminders.some(r => r.eventId === eventId);
    }

    /**
     * 更新筛选条件
     * @param {object} newFilters - 新的筛选条件
     */
    updateFilters(newFilters) {
        this.filters = { ...this.filters, ...newFilters };
        this.currentPage = 1;
        
        // 保存筛选偏好到本地存储
        try {
            localStorage.setItem(CALENDAR_CONFIG.storageKeys.filterPreference, JSON.stringify(this.filters));
        } catch (error) {
            console.error('保存筛选偏好失败:', error);
        }
    }

    /**
     * 加载保存的筛选偏好
     */
    loadFilterPreference() {
        try {
            const stored = localStorage.getItem(CALENDAR_CONFIG.storageKeys.filterPreference);
            if (stored) {
                const parsed = JSON.parse(stored);
                this.filters = { ...this.filters, ...parsed };
            }
        } catch (error) {
            console.error('加载筛选偏好失败:', error);
        }
    }

    /**
     * 切换页面
     * @param {number} page - 页码
     */
    setPage(page) {
        if (page < 1 || page > this.totalPages) return;
        this.currentPage = page;
    }
}

// ============================================================
// 日历渲染器
// ============================================================
class CalendarRenderer {
    constructor(containerId, dataManager) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            throw new Error(`容器元素 #${containerId} 不存在`);
        }
        this.dataManager = dataManager;
        this.currentView = this.loadViewPreference();
        this.init();
    }

    /**
     * 加载视图偏好
     * @returns {string} 视图类型
     */
    loadViewPreference() {
        try {
            return localStorage.getItem(CALENDAR_CONFIG.storageKeys.viewPreference) || CALENDAR_CONFIG.defaultView;
        } catch (error) {
            console.error('加载视图偏好失败:', error);
            return CALENDAR_CONFIG.defaultView;
        }
    }

    /**
     * 保存视图偏好
     * @param {string} view - 视图类型
     */
    saveViewPreference(view) {
        try {
            localStorage.setItem(CALENDAR_CONFIG.storageKeys.viewPreference, view);
        } catch (error) {
            console.error('保存视图偏好失败:', error);
        }
    }

    /**
     * 初始化渲染器
     */
    init() {
        try {
            this.renderViewControls();
            this.renderFilterBar();
            this.renderEvents();
            this.bindEvents();
        } catch (error) {
            console.error('初始化日历渲染器失败:', error);
            CalendarUtils.showError('日历加载失败，请刷新页面重试');
        }
    }

    /**
     * 渲染视图切换控件
     */
    renderViewControls() {
        try {
            const controls = this.container.querySelector('.calendar-view-controls');
            if (!controls) return;

            const views = [
                { key: 'timeline', label: '时间线', icon: 'fa-stream' },
                { key: 'list', label: '列表', icon: 'fa-list' },
                { key: 'month', label: '月历', icon: 'fa-calendar-alt' }
            ];

            controls.innerHTML = views.map(view => `
                <button class="view-btn ${this.currentView === view.key ? 'active' : ''}" 
                        data-view="${view.key}"
                        title="${view.label}视图">
                    <i class="fas ${view.icon}"></i>
                    <span>${view.label}</span>
                </button>
            `).join('');
        } catch (error) {
            console.error('渲染视图控件失败:', error);
        }
    }

    /**
     * 渲染筛选栏
     */
    renderFilterBar() {
        try {
            const filterBar = this.container.querySelector('.calendar-filter-bar');
            if (!filterBar) return;

            // 事件类型筛选
            const typeFilters = Object.entries(CALENDAR_CONFIG.eventTypes).map(([key, config]) => `
                <label class="filter-chip ${this.dataManager.filters.types.includes(key) ? 'active' : ''}" 
                       data-type="${key}"
                       style="--filter-color: ${config.color}">
                    <input type="checkbox" 
                           ${this.dataManager.filters.types.includes(key) ? 'checked' : ''} 
                           style="display:none">
                    <span>${config.icon} ${config.label}</span>
                </label>
            `).join('');

            // 日期范围筛选
            const dateRange = `
                <div class="filter-date-range">
                    <input type="date" class="filter-date-start" 
                           value="${this.dataManager.filters.dateRange.start || ''}" 
                           placeholder="开始日期">
                    <span>至</span>
                    <input type="date" class="filter-date-end" 
                           value="${this.dataManager.filters.dateRange.end || ''}" 
                           placeholder="结束日期">
                </div>
            `;

            // 关键词搜索
            const searchInput = `
                <div class="filter-search">
                    <i class="fas fa-search"></i>
                    <input type="text" class="filter-keyword" 
                           value="${this.dataManager.filters.keyword}" 
                           placeholder="搜索事件...">
                    ${this.dataManager.filters.keyword ? '<button class="filter-clear"><i class="fas fa-times"></i></button>' : ''}
                </div>
            `;

            filterBar.innerHTML = `
                <div class="filter-types">${typeFilters}</div>
                ${dateRange}
                ${searchInput}
            `;
        } catch (error) {
            console.error('渲染筛选栏失败:', error);
        }
    }

    /**
     * 渲染事件列表
     */
    renderEvents() {
        try {
            const eventsContainer = this.container.querySelector('.calendar-events');
            if (!eventsContainer) return;

            const events = this.dataManager.events;
            
            if (!events || events.length === 0) {
                eventsContainer.innerHTML = `
                    <div class="calendar-empty">
                        <i class="fas fa-calendar-times"></i>
                        <p>暂无升学事件</p>
                        <p class="text-muted">调整筛选条件试试</p>
                    </div>
                `;
                return;
            }

            switch (this.currentView) {
                case 'timeline':
                    this.renderTimelineView(eventsContainer, events);
                    break;
                case 'list':
                    this.renderListView(eventsContainer, events);
                    break;
                case 'month':
                    this.renderMonthView(eventsContainer, events);
                    break;
                default:
                    this.renderTimelineView(eventsContainer, events);
            }

            // 渲染分页
            this.renderPagination();
        } catch (error) {
            console.error('渲染事件列表失败:', error);
        }
    }

    /**
     * 渲染时间线视图
     * @param {HTMLElement} container - 容器元素
     * @param {Array} events - 事件列表
     */
    renderTimelineView(container, events) {
        try {
            // 按日期分组
            const grouped = {};
            events.forEach(event => {
                const dateKey = CalendarUtils.formatDate(event.event_date);
                if (!grouped[dateKey]) {
                    grouped[dateKey] = [];
                }
                grouped[dateKey].push(event);
            });

            const sortedDates = Object.keys(grouped).sort();

            container.innerHTML = `
                <div class="timeline-container">
                    ${sortedDates.map(date => `
                        <div class="timeline-date-group">
                            <div class="timeline-date-header">
                                <span class="date-label">${date}</span>
                                <span class="date-relative">${CalendarUtils.getRelativeTime(date)}</span>
                            </div>
                            <div class="timeline-events">
                                ${grouped[date].map(event => this.renderEventCard(event)).join('')}
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        } catch (error) {
            console.error('渲染时间线视图失败:', error);
        }
    }

    /**
     * 渲染列表视图
     * @param {HTMLElement} container - 容器元素
     * @param {Array} events - 事件列表
     */
    renderListView(container, events) {
        try {
            container.innerHTML = `
                <div class="list-container">
                    <table class="calendar-table">
                        <thead>
                            <tr>
                                <th>日期</th>
                                <th>类型</th>
                                <th>事件名称</th>
                                <th>状态</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${events.map(event => `
                                <tr class="event-row" data-event-id="${event.id}">
                                    <td>${CalendarUtils.formatDate(event.event_date)}</td>
                                    <td>
                                        <span class="event-type-badge" 
                                              style="background: ${CalendarUtils.getEventTypeConfig(event.event_type).color}20;
                                                     color: ${CalendarUtils.getEventTypeConfig(event.event_type).color}">
                                            ${CalendarUtils.getEventTypeConfig(event.event_type).icon}
                                            ${CalendarUtils.getEventTypeConfig(event.event_type).label}
                                        </span>
                                    </td>
                                    <td>
                                        <a href="#" class="event-link" data-event-id="${event.id}">
                                            ${event.title}
                                        </a>
                                    </td>
                                    <td>
                                        <span class="event-status ${event.status}">
                                            ${event.status === 'upcoming' ? '即将开始' : 
                                              event.status === 'ongoing' ? '进行中' : '已结束'}
                                        </span>
                                    </td>
                                    <td>
                                        <button class="btn-reminder ${this.dataManager.hasReminder(event.id) ? 'active' : ''}" 
                                                data-event-id="${event.id}">
                                            <i class="fas ${this.dataManager.hasReminder(event.id) ? 'fa-bell' : 'fa-bell-slash'}"></i>
                                        </button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (error) {
            console.error('渲染列表视图失败:', error);
        }
    }

    /**
     * 渲染月历视图
     * @param {HTMLElement} container - 容器元素
     * @param {Array} events - 事件列表
     */
    renderMonthView(container, events) {
        try {
            const now = new Date();
            const year = now.getFullYear();
            const month = now.getMonth();
            
            // 获取当月第一天和最后一天
            const firstDay = new Date(year, month, 1);
            const lastDay = new Date(year, month + 1, 0);
            
            // 获取当月所有日期
            const days = [];
            for (let d = 1; d <= lastDay.getDate(); d++) {
                const date = new Date(year, month, d);
                const dateStr = CalendarUtils.formatDate(date);
                const dayEvents = events.filter(e => 
                    CalendarUtils.formatDate(e.event_date) === dateStr
                );
                days.push({
                    date: d,
                    dateStr,
                    isToday: dateStr === CalendarUtils.formatDate(new Date()),
                    events: dayEvents
                });
            }

            // 获取星期标签
            const weekDays = ['日', '一', '二', '三', '四', '五', '六'];

            container.innerHTML = `
                <div class="month-container">
                    <div class="month-header">
                        <button class="month-nav prev"><i class="fas fa-chevron-left"></i></button>
                        <h3>${year}年${month + 1}月</h3>
                        <button class="month-nav next"><i class="fas fa-chevron-right"></i></button>
                    </div>
                    <div class="month-grid">
                        <div class="month-weekdays">
                            ${weekDays.map(day => `<div class="weekday">${day}</div>`).join('')}
                        </div>
                        <div class="month-days">
                            ${days.map(day => `
                                <div class="month-day ${day.isToday ? 'today' : ''} ${day.events.length > 0 ? 'has-events' : ''}"
                                     data-date="${day.dateStr}">
                                    <span class="day-number">${day.date}</span>
                                    ${day.events.length > 0 ? `
                                        <div class="day-events">
                                            ${day.events.slice(0, 3).map(event => `
                                                <div class="day-event" 
                                                     style="background: ${CalendarUtils.getEventTypeConfig(event.event_type).color}"
                                                     title="${event.title}">
                                                </div>
                                            `).join('')}
                                            ${day.events.length > 3 ? `<span class="more-events">+${day.events.length - 3}</span>` : ''}
                                        </div>
                                    ` : ''}
                                </div>
                            `).join('')}
                        </div>
                    </div>
                </div>
            `;
        } catch (error) {
            console.error('渲染月历视图失败:', error);
        }
    }

    /**
     * 渲染事件卡片
     * @param {object} event - 事件对象
     * @returns {string} HTML字符串
     */
    renderEventCard(event) {
        try {
            const typeConfig = CalendarUtils.getEventTypeConfig(event.event_type);
            const hasReminder = this.dataManager.hasReminder(event.id);
            
            return `
                <div class="event-card" data-event-id="${event.id}" 
                     style="border-left-color: ${typeConfig.color}">
                    <div class="event-card-header">
                        <span class="event-type" style="color: ${typeConfig.color}">
                            ${typeConfig.icon} ${typeConfig.label}
                        </span>
                        <span class="event-time">
                            <i class="far fa-clock"></i>
                            ${CalendarUtils.formatDate(event.event_date, 'HH:mm')}
                        </span>
                    </div>
                    <div class="event-card-body">
                        <h4 class="event-title">
                            <a href="#" class="event-link" data-event-id="${event.id}">
                                ${event.title}
                            </a>
                        </h4>
                        ${event.description ? `<p class="event-desc">${event.description}</p>` : ''}
                        <div class="event-meta">
                            <span class="event-relative">${CalendarUtils.getRelativeTime(event.event_date)}</span>
                            ${event.grade ? `<span class="event-grade">${event.grade}</span>` : ''}
                        </div>
                    </div>
                    <div class="event-card-footer">
                        <button class="btn-reminder ${hasReminder ? 'active' : ''}" 
                                data-event-id="${event.id}"
                                title="${hasReminder ? '取消提醒' : '设置提醒'}">
                            <i class="fas ${hasReminder ? 'fa-bell' : 'fa-bell-slash'}"></i>
                            <span>${hasReminder ? '已提醒' : '提醒我'}</span>
                        </button>
                        <button class="btn-detail" data-event-id="${event.id}">
                            <i class="fas fa-info-circle"></i>
                            <span>详情</span>
                        </button>
                    </div>
                </div>
            `;
        } catch (error) {
            console.error('渲染事件卡片失败:', error);
            return '';
        }
    }

    /**
     * 渲染分页控件
     */
    renderPagination() {
        try {
            const pagination = this.container.querySelector('.calendar-pagination');
            if (!pagination) return;

            const { currentPage, totalPages } = this.dataManager;
            
            if (totalPages <= 1) {
                pagination.innerHTML = '';
                return;
            }

            const pages = [];
            const maxVisible = 5;
            let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
            let end = Math.min(totalPages, start + maxVisible - 1);
            
            if (end - start + 1 < maxVisible) {
                start = Math.max(1, end - maxVisible + 1);
            }

            if (start > 1) {
                pages.push(1);
                if (start > 2) pages.push('...');
            }

            for (let i = start; i <= end; i++) {
                pages.push(i);
            }

            if (end < totalPages) {
                if (end < totalPages - 1) pages.push('...');
                pages.push(totalPages);
            }

            pagination.innerHTML = `
                <button class="page-btn prev" ${currentPage <= 1 ? 'disabled' : ''}>
                    <i class="fas fa-chevron-left"></i>
                </button>
                ${pages.map(page => {
                    if (page === '...') {
                        return '<span class="page-ellipsis">...</span>';
                    }
                    return `<button class="page-btn ${page === currentPage ? 'active' : ''}" data-page="${page}">${page}</button>`;
                }).join('')}
                <button class="page-btn next" ${currentPage >= totalPages ? 'disabled' : ''}>
                    <i class="fas fa-chevron-right"></i>
                </button>
            `;
        } catch (error) {
            console.error('渲染分页控件失败:', error);
        }
    }

    /**
     * 绑定事件处理
     */
    bindEvents() {
        try {
            // 视图切换
            const viewBtns = this.container.querySelectorAll('.view-btn');
            viewBtns.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const view = btn.dataset.view;
                    this.currentView = view;
                    this.saveViewPreference(view);
                    
                    // 更新按钮状态
                    viewBtns.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    
                    // 重新渲染事件
                    this.renderEvents();
                });
            });

            // 事件类型筛选
            const filterChips = this.container.querySelectorAll('.filter-chip');
            filterChips.forEach(chip => {
                chip.addEventListener('click', (e) => {
                    const type = chip.dataset.type;
                    const checkbox = chip.querySelector('input[type="checkbox"]');
                    
                    if (checkbox) {
                        checkbox.checked = !checkbox.checked;
                        chip.classList.toggle('active');
                        
                        // 更新筛选条件
                        const types = Array.from(filterChips)
                            .filter(c => c.querySelector('input[type="checkbox"]')?.checked)
                            .map(c => c.dataset.type);
                        
                        this.dataManager.updateFilters({ types });
                        this.loadEvents();
                    }
                });
            });

            // 日期范围筛选
            const dateStart = this.container.querySelector('.filter-date-start');
            const dateEnd = this.container.querySelector('.filter-date-end');
            
            if (dateStart) {
                dateStart.addEventListener('change', CalendarUtils.debounce(() => {
                    this.dataManager.updateFilters({
                        dateRange: {
                            start: dateStart.value || null,
                            end: dateEnd?.value || null
                        }
                    });
                    this.loadEvents();
                }, 500));
            }
            
            if (dateEnd) {
                dateEnd.addEventListener('change', CalendarUtils.debounce(() => {
                    this.dataManager.updateFilters({
                        dateRange: {
                            start: dateStart?.value || null,
                            end: dateEnd.value || null
                        }
                    });
                    this.loadEvents();
                }, 500));
            }

            // 关键词搜索
            const keywordInput = this.container.querySelector('.filter-keyword');
            const clearBtn = this.container.querySelector('.filter-clear');
            
            if (keywordInput) {
                keywordInput.addEventListener('input', CalendarUtils.debounce((e) => {
                    this.dataManager.updateFilters({ keyword: e.target.value });
                    this.loadEvents();
                }, 500));
            }
            
            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    if (keywordInput) {
                        keywordInput.value = '';
                        this.dataManager.updateFilters({ keyword: '' });
                        this.loadEvents();
                    }
                });
            }

            // 事件详情链接（事件委托）
            this.container.addEventListener('click', (e) => {
                const eventLink = e.target.closest('.event-link');
                if (eventLink) {
                    e.preventDefault();
                    const eventId = eventLink.dataset.eventId;
                    if (eventId) {
                        this.showEventDetail(eventId);
                    }
                }
            });

            // 提醒按钮（事件委托）
            this.container.addEventListener('click', async (e) => {
                const reminderBtn = e.target.closest('.btn-reminder');
                if (reminderBtn) {
                    e.preventDefault();
                    const eventId = reminderBtn.dataset.eventId;
                    if (eventId) {
                        const hasReminder = this.dataManager.hasReminder(eventId);
                        if (hasReminder) {
                            await this.dataManager.cancelReminder(eventId);
                        } else {
                            await this.dataManager.setReminder(eventId);
                        }
                        // 刷新当前视图
                        this.renderEvents();
                    }
                }
            });

            // 详情按钮（事件委托）
            this.container.addEventListener('click', (e) => {
                const detailBtn = e.target.closest('.btn-detail');
                if (detailBtn) {
                    e.preventDefault();
                    const eventId = detailBtn.dataset.eventId;
                    if (eventId) {
                        this.showEventDetail(eventId);
                    }
                }
            });

            // 分页按钮（事件委托）
            this.container.addEventListener('click', (e) => {
                const pageBtn = e.target.closest('.page-btn');
                if (pageBtn && !pageBtn.disabled) {
                    e.preventDefault();
                    const page = pageBtn.dataset.page;
                    if (page) {
                        this.dataManager.setPage(parseInt(page));
                        this.loadEvents();
                    } else if (pageBtn.classList.contains('prev')) {
                        this.dataManager.setPage(this.dataManager.currentPage - 1);
                        this.loadEvents();
                    } else if (pageBtn.classList.contains('next')) {
                        this.dataManager.setPage(this.dataManager.currentPage + 1);
                        this.loadEvents();
                    }
                }
            });

            // 月历导航
            const monthNav = this.container.querySelectorAll('.month-nav');
            monthNav.forEach(btn => {
                btn.addEventListener('click', () => {
                    // TODO: 实现月历导航
                    console.log('月历导航功能待实现');
                });
            });

            // 月历日期点击
            const monthDays = this.container.querySelectorAll('.month-day');
            monthDays.forEach(day => {
                day.addEventListener('click', () => {
                    const date = day.dataset.date;
                    if (date) {
                        // 切换到该日期的事件列表
                        this.dataManager.updateFilters({
                            dateRange: { start: date, end: date }
                        });
                        this.currentView = 'list';
                        this