/* ============================================
   点灯蛙 Global Store v2.0
   全局状态管理（Alpine.store）
   用户 / 画像 / 诊断 / 政策 / Tab
   认证：微信OAuth回调返回uid（openid哈希）
   ============================================ */

function initStore() {
  Alpine.store('app', {
    // === 用户与套餐 ===
    user: {
      openid: null,       // OAuth回调设置的uid（openid的SHA256哈希）
      nickname: '家长用户',
      avatar: '',
      plan: 'free',
      credits: 0,          // 诊断剩余次数
      isLoggedIn: false
    },

    // === 家庭画像 ===
    profile: {
      stage: '',           // youshengxiao / xiaoshengchu / suiqian / zhongkao
      hukouType: '',
      hukouDistrict: '',
      liveDistrict: '',
      socialSecurity: '',
      targetSchool: ''
    },

    // === 对话诊断 ===
    diagnosis: {
      messages: [],
      currentStage: '',
      isDiagnosing: false,
      diagnosisResult: null,
      activeStep: 0
    },

    // === 政策工具 ===
    policy: {
      activeSubTab: 'calendar',
      calendarMonth: new Date().getMonth() + 1,
      jargonHistory: []
    },

    // === 当前Tab ===
    activeTab: 'diagnosis',

    // === Actions ===
    setTab(tab) {
      this.activeTab = tab;
    },

    setStage(stage) {
      this.diagnosis.currentStage = stage;
      this.profile.stage = stage;
      this.saveProfile();
    },

    addMessage(role, content) {
      this.diagnosis.messages.push({ role, content, timestamp: Date.now() });
      this.saveMessages();
    },

    clearMessages() {
      this.diagnosis.messages = [];
      this.diagnosis.diagnosisResult = null;
      this.diagnosis.activeStep = 0;
      localStorage.removeItem('ddw_messages');
    },

    setDiagnosing(val) {
      this.diagnosis.isDiagnosing = val;
    },

    setActiveStep(step) {
      this.diagnosis.activeStep = step;
    },

    setDiagnosisResult(result) {
      this.diagnosis.diagnosisResult = result;
      this.saveMessages();
    },

    setCredits(remaining) {
      this.user.credits = remaining;
      this.saveUser();
    },

    // === OAuth 回调处理 ===
    handleOAuthCallback() {
      const params = new URLSearchParams(window.location.search);
      const uid = params.get('uid');
      if (uid) {
        this.user.openid = uid;
        this.user.isLoggedIn = true;
        this.saveUser();
        // 清理URL参数
        window.history.replaceState({}, '', window.location.pathname);
        return true;
      }
      return false;
    },

    // === Persistence ===
    saveMessages() {
      try {
        localStorage.setItem('ddw_messages', JSON.stringify(this.diagnosis.messages));
      } catch (e) {}
    },

    loadMessages() {
      try {
        const saved = localStorage.getItem('ddw_messages');
        if (saved) {
          this.diagnosis.messages = JSON.parse(saved);
        }
      } catch (e) {}
    },

    saveProfile() {
      try {
        localStorage.setItem('ddw_profile', JSON.stringify(this.profile));
      } catch (e) {}
    },

    loadProfile() {
      try {
        const saved = localStorage.getItem('ddw_profile');
        if (saved) {
          this.profile = { ...this.profile, ...JSON.parse(saved) };
        }
      } catch (e) {}
    },

    saveUser() {
      try {
        localStorage.setItem('ddw_user', JSON.stringify(this.user));
      } catch (e) {}
    },

    loadUser() {
      try {
        const saved = localStorage.getItem('ddw_user');
        if (saved) {
          this.user = { ...this.user, ...JSON.parse(saved) };
        }
      } catch (e) {}
    },

    getUid() {
      return this.user.openid || '';
    },

    logout() {
      localStorage.removeItem('ddw_user');
      localStorage.removeItem('ddw_messages');
      this.user.isLoggedIn = false;
      this.user.openid = null;
      this.user.credits = 0;
    },

    // === Init ===
    init() {
      this.loadUser();
      this.loadProfile();
      this.loadMessages();
      this.handleOAuthCallback();
    }
  });

  Alpine.store('app').init();
}

// 注册Store（在Alpine加载前定义）
// 同时兼容 app.html 和 pay.html（两者都引入 store.js）
document.addEventListener('alpine:init', () => {
  initStore();
});
