/**
 * policy.js - 政策查询模块前端交互脚本
 * 成都K12升学参谋 - 政策查询+诊断一站式设计方案
 * 包含筛选、分页、搜索、诊断引导等功能
 * Issue #27: Task B - 产品闭环整合
 */

// ============================================================
// 全局状态管理
// ============================================================
const PolicyState = {
    currentPage: 1,
    pageSize: 10,
    totalPages: 1,
    totalItems: 0,
    filters: {
        keyword: '',
        region: '',
        grade: '',
        category: '',
        year: '',
        status: ''
    },
    sortBy: 'publish_date',
    sortOrder: 'desc',
    isLoading: false,
    data: []
};

// ============================================================
// DOM 缓存
// ============================================================
const DOM = {
    // 搜索相关
    searchForm: null,
    searchInput: null,
    searchBtn: null,
    clearSearchBtn: null,

    // 筛选相关
    regionFilter: null,
    gradeFilter: null,
    categoryFilter: null,
    yearFilter: null,
    statusFilter: null,
    applyFilterBtn: null,
    resetFilterBtn: null,

    // 排序相关
    sortSelect: null,
    sortOrderBtn: null,

    // 列表相关
    policyList: null,
    policyCount: null,
    loadingSpinner: null,
    emptyState: null,

    // 分页相关
    pagination: null,
    pageInfo: null,
    prevBtn: null,
    nextBtn: null,
    pageSizeSelect: null,

    // 诊断引导相关
    diagnoseBtn: null,
    diagnoseModal: null,
    diagnoseForm: null,
    diagnoseResult: null
};

// ============================================================
// 初始化函数
// ============================================================
function initPolicyModule() {
    try {
        // 缓存DOM元素
        cacheDOMElements();
        
        // 绑定事件
        bindEvents();
        
        // 加载初始数据
        loadPolicyData();
        
        console.log('[Policy] 模块初始化完成');
    } catch (error) {
        console.error('[Policy] 初始化失败:', error);
        showErrorMessage('政策模块加载失败，请刷新页面重试');
    }
}

// ============================================================
// DOM元素缓存
// ============================================================
function cacheDOMElements() {
    DOM.searchForm = document.getElementById('policy-search-form');
    DOM.searchInput = document.getElementById('policy-search-input');
    DOM.searchBtn = document.getElementById('policy-search-btn');
    DOM.clearSearchBtn = document.getElementById('policy-clear-search');

    DOM.regionFilter = document.getElementById('policy-region-filter');
    DOM.gradeFilter = document.getElementById('policy-grade-filter');
    DOM.categoryFilter = document.getElementById('policy-category-filter');
    DOM.yearFilter = document.getElementById('policy-year-filter');
    DOM.statusFilter = document.getElementById('policy-status-filter');
    DOM.applyFilterBtn = document.getElementById('policy-apply-filter');
    DOM.resetFilterBtn = document.getElementById('policy-reset-filter');

    DOM.sortSelect = document.getElementById('policy-sort-select');
    DOM.sortOrderBtn = document.getElementById('policy-sort-order');

    DOM.policyList = document.getElementById('policy-list');
    DOM.policyCount = document.getElementById('policy-count');
    DOM.loadingSpinner = document.getElementById('policy-loading');
    DOM.emptyState = document.getElementById('policy-empty');

    DOM.pagination = document.getElementById('policy-pagination');
    DOM.pageInfo = document.getElementById('policy-page-info');
    DOM.prevBtn = document.getElementById('policy-prev-btn');
    DOM.nextBtn = document.getElementById('policy-next-btn');
    DOM.pageSizeSelect = document.getElementById('policy-page-size');

    // 诊断引导相关
    DOM.diagnoseBtn = document.getElementById('policy-diagnose-btn');
    DOM.diagnoseModal = document.getElementById('policy-diagnose-modal');
    DOM.diagnoseForm = document.getElementById('policy-diagnose-form');
    DOM.diagnoseResult = document.getElementById('policy-diagnose-result');
}

// ============================================================
// 事件绑定
// ============================================================
function bindEvents() {
    try {
        // 搜索表单提交
        if (DOM.searchForm) {
            DOM.searchForm.addEventListener('submit', function(e) {
                e.preventDefault();
                handleSearch();
            });
        }

        // 搜索按钮点击
        if (DOM.searchBtn) {
            DOM.searchBtn.addEventListener('click', function(e) {
                e.preventDefault();
                handleSearch();
            });
        }

        // 清除搜索
        if (DOM.clearSearchBtn) {
            DOM.clearSearchBtn.addEventListener('click', function() {
                if (DOM.searchInput) {
                    DOM.searchInput.value = '';
                }
                PolicyState.filters.keyword = '';
                PolicyState.currentPage = 1;
                loadPolicyData();
            });
        }

        // 搜索输入框回车
        if (DOM.searchInput) {
            DOM.searchInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    handleSearch();
                }
            });
        }

        // 筛选条件变更
        const filterElements = [
            DOM.regionFilter,
            DOM.gradeFilter,
            DOM.categoryFilter,
            DOM.yearFilter,
            DOM.statusFilter
        ];

        filterElements.forEach(function(el) {
            if (el) {
                el.addEventListener('change', function() {
                    // 自动应用筛选（可选：也可以等待用户点击"应用筛选"按钮）
                    // handleFilterChange();
                });
            }
        });

        // 应用筛选按钮
        if (DOM.applyFilterBtn) {
            DOM.applyFilterBtn.addEventListener('click', function() {
                handleFilterChange();
            });
        }

        // 重置筛选按钮
        if (DOM.resetFilterBtn) {
            DOM.resetFilterBtn.addEventListener('click', function() {
                resetFilters();
            });
        }

        // 排序变更
        if (DOM.sortSelect) {
            DOM.sortSelect.addEventListener('change', function() {
                PolicyState.sortBy = DOM.sortSelect.value;
                PolicyState.currentPage = 1;
                loadPolicyData();
            });
        }

        // 排序顺序切换
        if (DOM.sortOrderBtn) {
            DOM.sortOrderBtn.addEventListener('click', function() {
                PolicyState.sortOrder = PolicyState.sortOrder === 'desc' ? 'asc' : 'desc';
                updateSortOrderIcon();
                PolicyState.currentPage = 1;
                loadPolicyData();
            });
        }

        // 分页按钮
        if (DOM.prevBtn) {
            DOM.prevBtn.addEventListener('click', function() {
                if (PolicyState.currentPage > 1) {
                    PolicyState.currentPage--;
                    loadPolicyData();
                }
            });
        }

        if (DOM.nextBtn) {
            DOM.nextBtn.addEventListener('click', function() {
                if (PolicyState.currentPage < PolicyState.totalPages) {
                    PolicyState.currentPage++;
                    loadPolicyData();
                }
            });
        }

        // 每页条数变更
        if (DOM.pageSizeSelect) {
            DOM.pageSizeSelect.addEventListener('change', function() {
                PolicyState.pageSize = parseInt(DOM.pageSizeSelect.value) || 10;
                PolicyState.currentPage = 1;
                loadPolicyData();
            });
        }

        // 诊断引导按钮
        if (DOM.diagnoseBtn) {
            DOM.diagnoseBtn.addEventListener('click', function() {
                openDiagnoseModal();
            });
        }

        // 诊断表单提交
        if (DOM.diagnoseForm) {
            DOM.diagnoseForm.addEventListener('submit', function(e) {
                e.preventDefault();
                handleDiagnoseSubmit();
            });
        }

        // 诊断模态框关闭
        const closeBtns = document.querySelectorAll('[data-dismiss="modal"]');
        closeBtns.forEach(function(btn) {
            btn.addEventListener('click', function() {
                closeDiagnoseModal();
            });
        });

        // 点击模态框外部关闭
        if (DOM.diagnoseModal) {
            DOM.diagnoseModal.addEventListener('click', function(e) {
                if (e.target === DOM.diagnoseModal) {
                    closeDiagnoseModal();
                }
            });
        }

        console.log('[Policy] 事件绑定完成');
    } catch (error) {
        console.error('[Policy] 事件绑定失败:', error);
    }
}

// ============================================================
// 搜索处理
// ============================================================
function handleSearch() {
    try {
        const keyword = DOM.searchInput ? DOM.searchInput.value.trim() : '';
        PolicyState.filters.keyword = keyword;
        PolicyState.currentPage = 1;
        loadPolicyData();
    } catch (error) {
        console.error('[Policy] 搜索处理失败:', error);
    }
}

// ============================================================
// 筛选变更处理
// ============================================================
function handleFilterChange() {
    try {
        // 获取各筛选条件值
        PolicyState.filters.region = DOM.regionFilter ? DOM.regionFilter.value : '';
        PolicyState.filters.grade = DOM.gradeFilter ? DOM.gradeFilter.value : '';
        PolicyState.filters.category = DOM.categoryFilter ? DOM.categoryFilter.value : '';
        PolicyState.filters.year = DOM.yearFilter ? DOM.yearFilter.value : '';
        PolicyState.filters.status = DOM.statusFilter ? DOM.statusFilter.value : '';

        PolicyState.currentPage = 1;
        loadPolicyData();
    } catch (error) {
        console.error('[Policy] 筛选处理失败:', error);
    }
}

// ============================================================
// 重置筛选条件
// ============================================================
function resetFilters() {
    try {
        // 重置筛选下拉框
        const filterElements = [
            DOM.regionFilter,
            DOM.gradeFilter,
            DOM.categoryFilter,
            DOM.yearFilter,
            DOM.statusFilter
        ];

        filterElements.forEach(function(el) {
            if (el) {
                el.value = '';
            }
        });

        // 重置搜索框
        if (DOM.searchInput) {
            DOM.searchInput.value = '';
        }

        // 重置状态
        PolicyState.filters = {
            keyword: '',
            region: '',
            grade: '',
            category: '',
            year: '',
            status: ''
        };

        PolicyState.currentPage = 1;
        loadPolicyData();

        console.log('[Policy] 筛选条件已重置');
    } catch (error) {
        console.error('[Policy] 重置筛选失败:', error);
    }
}

// ============================================================
// 更新排序图标
// ============================================================
function updateSortOrderIcon() {
    try {
        if (DOM.sortOrderBtn) {
            const icon = DOM.sortOrderBtn.querySelector('i');
            if (icon) {
                if (PolicyState.sortOrder === 'desc') {
                    icon.className = 'bi bi-sort-down';
                } else {
                    icon.className = 'bi bi-sort-up';
                }
            }
        }
    } catch (error) {
        console.error('[Policy] 更新排序图标失败:', error);
    }
}

// ============================================================
// 加载政策数据（核心API请求）
// ============================================================
function loadPolicyData() {
    // 防止重复请求
    if (PolicyState.isLoading) {
        return;
    }

    PolicyState.isLoading = true;
    showLoading();

    try {
        // 构建请求参数
        const params = new URLSearchParams();
        params.append('page', PolicyState.currentPage);
        params.append('page_size', PolicyState.pageSize);
        params.append('sort_by', PolicyState.sortBy);
        params.append('sort_order', PolicyState.sortOrder);

        // 添加筛选条件
        if (PolicyState.filters.keyword) {
            params.append('keyword', PolicyState.filters.keyword);
        }
        if (PolicyState.filters.region) {
            params.append('region', PolicyState.filters.region);
        }
        if (PolicyState.filters.grade) {
            params.append('grade', PolicyState.filters.grade);
        }
        if (PolicyState.filters.category) {
            params.append('category', PolicyState.filters.category);
        }
        if (PolicyState.filters.year) {
            params.append('year', PolicyState.filters.year);
        }
        if (PolicyState.filters.status) {
            params.append('status', PolicyState.filters.status);
        }

        // 发起API请求
        fetch('/api/policies?' + params.toString(), {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(function(response) {
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.json();
        })
        .then(function(data) {
            // 更新状态
            PolicyState.data = data.items || [];
            PolicyState.totalItems = data.total || 0;
            PolicyState.totalPages = data.total_pages || 1;
            PolicyState.currentPage = data.page || 1;

            // 渲染数据
            renderPolicyList();
            renderPagination();
            updatePolicyCount();

            PolicyState.isLoading = false;
            hideLoading();
        })
        .catch(function(error) {
            console.error('[Policy] 数据加载失败:', error);
            PolicyState.isLoading = false;
            hideLoading();
            showErrorMessage('政策数据加载失败，请稍后重试');
        });

    } catch (error) {
        console.error('[Policy] 请求构建失败:', error);
        PolicyState.isLoading = false;
        hideLoading();
        showErrorMessage('请求构建失败，请检查网络连接');
    }
}

// ============================================================
// 渲染政策列表
// ============================================================
function renderPolicyList() {
    try {
        if (!DOM.policyList) return;

        // 清空列表
        DOM.policyList.innerHTML = '';

        // 检查是否有数据
        if (!PolicyState.data || PolicyState.data.length === 0) {
            showEmptyState();
            return;
        }

        // 隐藏空状态
        hideEmptyState();

        // 遍历数据生成列表项
        PolicyState.data.forEach(function(item) {
            const listItem = createPolicyListItem(item);
            if (listItem) {
                DOM.policyList.appendChild(listItem);
            }
        });

        console.log('[Policy] 渲染了 ' + PolicyState.data.length + ' 条政策');
    } catch (error) {
        console.error('[Policy] 渲染列表失败:', error);
    }
}

// ============================================================
// 创建单个政策列表项
// ============================================================
function createPolicyListItem(item) {
    try {
        if (!item) return null;

        const div = document.createElement('div');
        div.className = 'policy-item card mb-3';
        div.dataset.id = item.id || '';

        // 格式化日期
        const publishDate = item.publish_date ? formatDate(item.publish_date) : '未知日期';

        // 构建标签
        const tags = [];
        if (item.region) {
            tags.push('<span class="badge bg-info me-1">' + escapeHtml(item.region) + '</span>');
        }
        if (item.grade) {
            tags.push('<span class="badge bg-success me-1">' + escapeHtml(item.grade) + '</span>');
        }
        if (item.category) {
            tags.push('<span class="badge bg-warning text-dark me-1">' + escapeHtml(item.category) + '</span>');
        }
        if (item.status) {
            const statusClass = item.status === '有效' ? 'bg-primary' : 'bg-secondary';
            tags.push('<span class="badge ' + statusClass + '">' + escapeHtml(item.status) + '</span>');
        }

        // 构建摘要
        const summary = item.summary || item.content ? (item.content.substring(0, 150) + '...') : '暂无摘要';

        div.innerHTML = `
            <div class="card-body">
                <div class="d-flex justify-content-between align-items-start">
                    <h5 class="card-title mb-1">
                        <a href="/policy/${item.id || '#'}" class="text-decoration-none">
                            ${escapeHtml(item.title || '未命名政策')}
                        </a>
                    </h5>
                    <small class="text-muted">${publishDate}</small>
                </div>
                <div class="mb-2">
                    ${tags.join(' ')}
                </div>
                <p class="card-text text-muted">${escapeHtml(summary)}</p>
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <span class="text-muted small">
                            <i class="bi bi-eye me-1"></i>${item.view_count || 0} 次阅读
                        </span>
                        ${item.source ? '<span class="ms-3 text-muted small"><i class="bi bi-building me-1"></i>' + escapeHtml(item.source) + '</span>' : ''}
                    </div>
                    <a href="/policy/${item.id || '#'}" class="btn btn-sm btn-outline-primary">
                        查看详情 <i class="bi bi-arrow-right"></i>
                    </a>
                </div>
            </div>
        `;

        // 添加点击事件跳转详情
        const titleLink = div.querySelector('.card-title a');
        if (titleLink) {
            titleLink.addEventListener('click', function(e) {
                e.preventDefault();
                const policyId = item.id;
                if (policyId) {
                    window.location.href = '/policy/' + policyId;
                }
            });
        }

        return div;
    } catch (error) {
        console.error('[Policy] 创建列表项失败:', error);
        return null;
    }
}

// ============================================================
// 渲染分页
// ============================================================
function renderPagination() {
    try {
        if (!DOM.pagination || !DOM.pageInfo || !DOM.prevBtn || !DOM.nextBtn) return;

        // 更新页码信息
        DOM.pageInfo.textContent = '第 ' + PolicyState.currentPage + ' / ' + PolicyState.totalPages + ' 页';

        // 更新按钮状态
        DOM.prevBtn.disabled = PolicyState.currentPage <= 1;
        DOM.nextBtn.disabled = PolicyState.currentPage >= PolicyState.totalPages;

        // 生成页码按钮（最多显示5个）
        const pageNumbers = DOM.pagination.querySelector('.page-numbers');
        if (pageNumbers) {
            pageNumbers.innerHTML = '';
            
            const maxVisible = 5;
            let startPage = Math.max(1, PolicyState.currentPage - Math.floor(maxVisible / 2));
            let endPage = Math.min(PolicyState.totalPages, startPage + maxVisible - 1);

            if (endPage - startPage + 1 < maxVisible) {
                startPage = Math.max(1, endPage - maxVisible + 1);
            }

            for (let i = startPage; i <= endPage; i++) {
                const pageBtn = document.createElement('button');
                pageBtn.className = 'btn btn-sm ' + (i === PolicyState.currentPage ? 'btn-primary' : 'btn-outline-primary');
                pageBtn.textContent = i;
                pageBtn.dataset.page = i;

                pageBtn.addEventListener('click', function() {
                    PolicyState.currentPage = i;
                    loadPolicyData();
                });

                pageNumbers.appendChild(pageBtn);
            }
        }

        console.log('[Policy] 分页渲染完成');
    } catch (error) {
        console.error('[Policy] 渲染分页失败:', error);
    }
}

// ============================================================
// 更新政策总数显示
// ============================================================
function updatePolicyCount() {
    try {
        if (DOM.policyCount) {
            DOM.policyCount.textContent = '共 ' + PolicyState.totalItems + ' 条政策';
        }
    } catch (error) {
        console.error('[Policy] 更新计数失败:', error);
    }
}

// ============================================================
// 显示/隐藏加载状态
// ============================================================
function showLoading() {
    try {
        if (DOM.loadingSpinner) {
            DOM.loadingSpinner.style.display = 'block';
        }
        if (DOM.policyList) {
            DOM.policyList.style.opacity = '0.5';
        }
    } catch (error) {
        console.error('[Policy] 显示加载状态失败:', error);
    }
}

function hideLoading() {
    try {
        if (DOM.loadingSpinner) {
            DOM.loadingSpinner.style.display = 'none';
        }
        if (DOM.policyList) {
            DOM.policyList.style.opacity = '1';
        }
    } catch (error) {
        console.error('[Policy] 隐藏加载状态失败:', error);
    }
}

// ============================================================
// 显示/隐藏空状态
// ============================================================
function showEmptyState() {
    try {
        if (DOM.emptyState) {
            DOM.emptyState.style.display = 'block';
        }
        if (DOM.pagination) {
            DOM.pagination.style.display = 'none';
        }
    } catch (error) {
        console.error('[Policy] 显示空状态失败:', error);
    }
}

function hideEmptyState() {
    try {
        if (DOM.emptyState) {
            DOM.emptyState.style.display = 'none';
        }
        if (DOM.pagination) {
            DOM.pagination.style.display = 'flex';
        }
    } catch (error) {
        console.error('[Policy] 隐藏空状态失败:', error);
    }
}

// ============================================================
// 显示错误消息
// ============================================================
function showErrorMessage(message) {
    try {
        // 尝试使用全局通知组件
        if (typeof showToast === 'function') {
            showToast(message, 'error');
            return;
        }

        // 回退：创建临时错误提示
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-danger alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3';
        alertDiv.style.zIndex = '9999';
        alertDiv.innerHTML = `
            <strong>错误：</strong> ${escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(alertDiv);

        // 3秒后自动移除
        setTimeout(function() {
            if (alertDiv.parentNode) {
                alertDiv.parentNode.removeChild(alertDiv);
            }
        }, 3000);
    } catch (error) {
        console.error('[Policy] 显示错误消息失败:', error);
    }
}

// ============================================================
// 诊断引导功能
// ============================================================
function openDiagnoseModal() {
    try {
        if (DOM.diagnoseModal) {
            DOM.diagnoseModal.style.display = 'block';
            document.body.style.overflow = 'hidden';
        }
    } catch (error) {
        console.error('[Policy] 打开诊断模态框失败:', error);
    }
}

function closeDiagnoseModal() {
    try {
        if (DOM.diagnoseModal) {
            DOM.diagnoseModal.style.display = 'none';
            document.body.style.overflow = '';
        }
        // 清空表单和结果
        if (DOM.diagnoseForm) {
            DOM.diagnoseForm.reset();
        }
        if (DOM.diagnoseResult) {
            DOM.diagnoseResult.innerHTML = '';
            DOM.diagnoseResult.style.display = 'none';
        }
    } catch (error) {
        console.error('[Policy] 关闭诊断模态框失败:', error);
    }
}

function handleDiagnoseSubmit() {
    try {
        if (!DOM.diagnoseForm) return;

        // 收集表单数据
        const formData = new FormData(DOM.diagnoseForm);
        const diagnoseData = {
            grade: formData.get('grade') || '',
            region: formData.get('region') || '',
            school_type: formData.get('school_type') || '',
            current_score: formData.get('current_score') || '',
            target_school: formData.get('target_school') || '',
            special_needs: formData.get('special_needs') || ''
        };

        // 验证必填字段
        if (!diagnoseData.grade || !diagnoseData.region) {
            showErrorMessage('请填写年级和区域信息');
            return;
        }

        // 显示加载状态
        const submitBtn = DOM.diagnoseForm.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>诊断中...';
        }

        // 发送诊断请求
        fetch('/api/diagnose', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(diagnoseData)
        })
        .then(function(response) {
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.json();
        })
        .then(function(result) {
            // 显示诊断结果
            showDiagnoseResult(result);
            
            // 恢复按钮状态
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '开始诊断';
            }
        })
        .catch(function(error) {
            console.error('[Policy] 诊断请求失败:', error);
            showErrorMessage('诊断服务暂时不可用，请稍后重试');
            
            // 恢复按钮状态
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '开始诊断';
            }
        });

    } catch (error) {
        console.error('[Policy] 诊断提交处理失败:', error);
        showErrorMessage('诊断提交失败，请重试');
    }
}

function showDiagnoseResult(result) {
    try {
        if (!DOM.diagnoseResult) return;

        // 清空之前的结果
        DOM.diagnoseResult.innerHTML = '';
        DOM.diagnoseResult.style.display = 'block';

        // 构建结果HTML
        const resultHtml = `
            <div class="diagnose-result-card">
                <div class="result-header mb-3">
                    <h5 class="text-success">
                        <i class="bi bi-check-circle me-2"></i>诊断完成
                    </h5>
                </div>
                <div class="result-body">
                    <div class="row mb-3">
                        <div class="col-md-6">
                            <strong>诊断等级：</strong>
                            <span class="badge ${getLevelBadgeClass(result.level)}">${escapeHtml(result.level || '待评估')}</span>
                        </div>
                        <div class="col-md-6">
                            <strong>匹配政策数：</strong>
                            <span class="badge bg-info">${result.matched_policies || 0} 条</span>
                        </div>
                    </div>
                    <div class="result-summary mb-3">
                        <h6>诊断摘要</h6>
                        <p>${escapeHtml(result.summary || '暂无诊断摘要')}</p>
                    </div>
                    ${result.recommendations ? `
                    <div class="result-recommendations mb-3">
                        <h6>推荐建议</h6>
                        <ul>
                            ${result.recommendations.map(function(rec) {
                                return '<li>' + escapeHtml(rec) + '</li>';
                            }).join('')}
                        </ul>
                    </div>
                    ` : ''}
                    <div class="result-actions mt-3">
                        <button class="btn btn-primary me-2" onclick="window.location.href='/policies?diagnose_id=${result.id || ''}'">
                            <i class="bi bi-search me-1"></i>查看相关政策
                        </button>
                        <button class="btn btn-outline-secondary" onclick="closeDiagnoseModal()">
                            <i class="bi bi-x me-1"></i>关闭
                        </button>
                    </div>
                </div>
            </div>
        `;

        DOM.diagnoseResult.innerHTML = resultHtml;

        console.log('[Policy] 诊断结果已显示');
    } catch (error) {
        console.error('[Policy] 显示诊断结果失败:', error);
        showErrorMessage('诊断结果展示失败');
    }
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 获取诊断等级对应的CSS类
 */
function getLevelBadgeClass(level) {
    const levelMap = {
        '紧急': 'bg-danger',
        '重要': 'bg-warning text-dark',
        '一般': 'bg-info',
        '待评估': 'bg-secondary'
    };
    return levelMap[level] || 'bg-secondary';
}

/**
 * HTML转义，防止XSS攻击
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * 格式化日期
 */
function formatDate(dateStr) {
    try {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return dateStr;
        
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return year + '-' + month + '-' + day;
    } catch (error) {
        console.error('[Policy] 日期格式化失败:', error);
        return dateStr || '';
    }
}

// ============================================================
// 页面加载完成后初始化
// ============================================================
document.addEventListener('DOMContentLoaded', function() {
    // 检查是否在政策页面
    const policyContainer = document.getElementById('policy-module-container');
    if (policyContainer) {
        initPolicyModule();
    }
});

// 导出模块（如果使用模块系统）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        initPolicyModule: initPolicyModule,
        PolicyState: PolicyState
    };
}