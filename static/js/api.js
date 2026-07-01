/* ============================================
   点灯蛙 API Layer v2.0
   对齐后端实际端点：/api/diagnose, /api/jargon/translate, /api/payment/*
   认证方式：X-OpenID header（微信OAuth回调返回uid）
   ============================================ */

const API = {
  baseUrl: '',

  // 获取用户标识（OAuth回调设置的uid）
  getUid() {
    try {
      const user = JSON.parse(localStorage.getItem('ddw_user') || '{}');
      return user.openid || '';
    } catch { return ''; }
  },

  async request(path, options = {}) {
    const uid = this.getUid();
    const headers = {
      'Content-Type': 'application/json',
      ...(uid && { 'X-OpenID': uid }),
      ...options.headers
    };

    try {
      const res = await fetch(this.baseUrl + path, {
        ...options,
        headers,
        credentials: 'same-origin'
      });

      if (res.status === 401) {
        this.redirectToAuth();
        throw new Error('未登录');
      }

      if (res.status === 402) {
        const err = await res.json().catch(() => ({}));
        const msg = typeof err.detail === 'object' ? err.detail?.message : err.detail;
        throw new Error(msg || '积分不足，请充值后继续使用');
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = typeof err.detail === 'object' ? err.detail?.message || JSON.stringify(err.detail) : err.detail;
        throw new Error(msg || err.message || `请求失败 (${res.status})`);
      }

      return await res.json();
    } catch (e) {
      if (e.message === 'Failed to fetch') {
        throw new Error('网络连接失败，请检查网络后重试');
      }
      throw e;
    }
  },

  // === 诊断（核心接口） ===
  // 后端 POST /diagnose，nginx重写 /api/diagnose → /diagnose
  // DiagnosisRequest: { question, stage, conversation_history, plan }
  // DiagnosisResult: { result, credits_used, credits_remaining, created_at }
  async diagnose(question, stage, conversationHistory = []) {
    return this.request('/api/diagnose', {
      method: 'POST',
      body: JSON.stringify({
        question,
        stage,
        conversation_history: conversationHistory.map(m => ({
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content
        }))
      })
    });
  },

  // === 黑话翻译 ===
  // 后端 POST /jargon/translate，nginx重写 /api/jargon/translate → /jargon/translate
  // 请求: { text: "大摇号" } → 响应: { success, original, translation, source, related_terms }
  async translateJargon(term) {
    return this.request('/api/jargon/translate', {
      method: 'POST',
      body: JSON.stringify({ text: term })
    });
  },

  // === 升学日历 ===
  // 后端 GET /calendar/events
  async getCalendarEvents(year, grade) {
    const params = new URLSearchParams();
    if (year) params.set('year', year);
    if (grade) params.set('grade', grade);
    return this.request(`/api/calendar/events?${params}`);
  },

  async getUpcomingEvents(days = 30) {
    return this.request(`/api/calendar/events/upcoming?days=${days}`);
  },

  // === 支付 ===
  // 后端 GET /payment/price-tiers → 三档定价信息
  // 响应: { success, data: { price_tiers: { basic, standard, premium } } }
  async getPriceTiers() {
    const res = await this.request('/api/payment/price-tiers');
    return res.data?.price_tiers || res.price_tiers || res;
  },

  // 后端 GET /payment/plans → 套餐列表
  // 响应: { success, data: { plans: { basic, standard, premium } } }
  async getPlans() {
    const res = await this.request('/api/payment/plans');
    return res.data?.plans || res.plans || res;
  },

  // 后端 POST /payment/purchase-diagnoses → 按次购买诊断次数
  async purchaseDiagnoses(credits) {
    return this.request('/api/payment/purchase-diagnoses', {
      method: 'POST',
      body: JSON.stringify({
        user_id: this.getUid(),
        credits,
        payment_method: 'wechat'
      })
    });
  },

  // 后端 POST /payment/create-order → 套餐购买
  async createOrder(plan) {
    return this.request('/api/payment/create-order', {
      method: 'POST',
      body: JSON.stringify({
        user_id: this.getUid(),
        plan
      })
    });
  },

  // 后端 GET /payment/balance/{user_id} → 余额查询
  // 响应: { success, data: { diagnosis_credits, ... } }
  async getBalance() {
    const uid = this.getUid();
    if (!uid) return { diagnosis_credits: 0 };
    const res = await this.request(`/api/payment/balance/${uid}`);
    return res.data || res;
  },

  // 后端 GET /payment/orders/{user_id} → 订单历史
  async getOrders() {
    const uid = this.getUid();
    if (!uid) return [];
    return this.request(`/api/payment/orders/${uid}`);
  },

  // === 微信支付配置 ===
  // 后端 GET /wechat/wechat/payment/config
  async getPaymentConfig() {
    return this.request('/wechat/wechat/payment/config');
  },

  // === Auth ===
  // 后端 GET /wechat/wechat/auth?return_to=xxx → 重定向到微信OAuth
  redirectToAuth() {
    const currentPath = window.location.pathname + window.location.search;
    sessionStorage.setItem('ddw_redirect', currentPath);
    window.location.href = '/wechat/wechat/auth?return_to=' + encodeURIComponent(currentPath);
  },

  // === 工具方法 ===
  formatTime(timestamp) {
    const d = new Date(timestamp);
    const month = d.getMonth() + 1;
    const day = d.getDate();
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    return `${month}月${day}日 ${hours}:${minutes}`;
  },

  getStageLabel(stage) {
    const labels = {
      'youshengxiao': '幼升小',
      'xiaoshengchu': '小升初',
      'suiqian': '随迁入学',
      'zhongkao': '中考'
    };
    return labels[stage] || '未选择';
  },

  getPlanLabel(plan) {
    const labels = { 'free': '免费版', 'lite': 'LITE版', 'max': 'MAX版' };
    return labels[(plan || '').toLowerCase()] || '免费版';
  }
};
