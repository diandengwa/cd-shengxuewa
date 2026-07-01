/* ============================================
   点灯蛙 工作台主逻辑 v2.0
   诊断 / 政策 / 我的
   对齐后端：POST /api/diagnose, POST /api/jargon/translate
   ============================================ */

function appPage() {
  return {
    // === 状态 ===
    activeTab: 'diagnosis',
    inputText: '',
    showDisclaimer: false,
    jargonInput: '',
    jargonResult: null,
    historyReports: [],

    // 全局引用
    get user() { return Alpine.store('app').user; },
    get profile() { return Alpine.store('app').profile; },
    get diagnosis() { return Alpine.store('app').diagnosis; },
    get policy() { return Alpine.store('app').policy; },

    // 学段选项（对齐后端 stage 字段值）
    stages: [
      { key: 'youshengxiao', label: '幼升小' },
      { key: 'xiaoshengchu', label: '小升初' },
      { key: 'suiqian', label: '随迁入学' },
      { key: 'zhongkao', label: '中考' }
    ],

    // 热门黑话
    popularJargon: ['大摇号', '小摇号', '统筹', '调剂', '锁区', '一对一', '直升'],

    // === 初始化 ===
    init() {
      const store = Alpine.store('app');
      store.init();

      // 首次显示免责声明
      if (!localStorage.getItem('ddw_disclaimer_shown')) {
        this.showDisclaimer = true;
        localStorage.setItem('ddw_disclaimer_shown', '1');
      }

      // 加载历史报告
      this.loadHistory();

      // 检查URL参数
      const params = new URLSearchParams(window.location.search);
      const tab = params.get('tab');
      if (tab) this.activeTab = tab;

      // 已登录则拉取余额
      if (this.user.isLoggedIn) {
        this.refreshBalance();
      }
    },

    // === 诊断 ===
    selectStage(stage) {
      Alpine.store('app').setStage(stage);
    },

    async sendMessage() {
      const text = this.inputText.trim();
      if (!text || this.diagnosis.isDiagnosing) return;

      if (!this.diagnosis.currentStage) {
        alert('请先选择升学阶段');
        return;
      }

      // 检查登录
      if (!this.user.isLoggedIn) {
        if (confirm('请先通过微信登录，登录后可免费体验3次诊断。是否前往登录？')) {
          API.redirectToAuth();
        }
        return;
      }

      Alpine.store('app').addMessage('user', text);
      this.inputText = '';

      try {
        Alpine.store('app').setDiagnosing(true);

        const res = await API.diagnose(
          text,
          this.diagnosis.currentStage,
          this.diagnosis.messages
        );

        Alpine.store('app').setDiagnosing(false);

        // 后端 DiagnosisResult: { result: {...}, credits_used, credits_remaining }
        if (res.result) {
          // 提取参谋回复文本
          const replyText = res.result.preliminary_conclusion
            || res.result.next_steps
            || res.result.situation_type
            || '研判完成，请查看下方详细报告。';

          Alpine.store('app').addMessage('assistant', replyText);

          // 设置诊断结果
          Alpine.store('app').setDiagnosisResult(res.result);
        }

        // 更新积分余额
        if (typeof res.credits_remaining === 'number') {
          Alpine.store('app').setCredits(res.credits_remaining);
        }
      } catch (e) {
        Alpine.store('app').setDiagnosing(false);
        if (e.message.includes('未登录')) return;
        if (e.message.includes('积分不足')) {
          Alpine.store('app').addMessage('assistant', '您的免费诊断次数已用完，请前往充值页面购买更多诊断次数。');
          return;
        }
        Alpine.store('app').addMessage('assistant', '抱歉，研判服务暂时不可用，请稍后重试。');
        console.error('Diagnose error:', e);
      }
    },

    quickAsk(question) {
      this.inputText = question;
      this.sendMessage();
    },

    async refreshBalance() {
      try {
        const res = await API.getBalance();
        if (typeof res.diagnosis_credits === 'number') {
          Alpine.store('app').setCredits(res.diagnosis_credits);
        }
      } catch (e) {
        console.error('Balance fetch error:', e);
      }
    },

    showPaywall() {
      if (confirm('免费次数已用完。充值后可继续使用深度诊断。是否前往充值？')) {
        window.location.href = '/pay';
      }
    },

    newDiagnosis() {
      Alpine.store('app').clearMessages();
    },

    saveReport() {
      if (!this.diagnosis.diagnosisResult) return;
      const report = {
        id: Date.now(),
        title: `${this.getStageLabel(this.diagnosis.currentStage)} · ${this.profile.hukouDistrict || '未填写'}→${this.profile.liveDistrict || '未填写'}`,
        timestamp: Date.now(),
        data: this.diagnosis.diagnosisResult
      };
      this.historyReports.unshift(report);
      try {
        localStorage.setItem('ddw_reports', JSON.stringify(this.historyReports.slice(0, 20)));
      } catch (e) {}
      alert('报告已保存到历史记录');
    },

    toggleChecklist(idx) {
      if (this.diagnosis.diagnosisResult?.step4?.action_items?.[idx]) {
        this.diagnosis.diagnosisResult.step4.action_items[idx].done =
          !this.diagnosis.diagnosisResult.step4.action_items[idx].done;
        Alpine.store('app').saveMessages();
      }
    },

    viewReport(report) {
      Alpine.store('app').setDiagnosisResult(report.data);
      this.activeTab = 'diagnosis';
    },

    loadHistory() {
      try {
        const saved = localStorage.getItem('ddw_reports');
        if (saved) {
          this.historyReports = JSON.parse(saved);
        }
      } catch (e) {}
    },

    // === 政策 ===
    getCalendarEvents(month) {
      const events = {
        3: [
          { date: '3月1日', title: '小升初信息采集开始', level: 'orange' },
          { date: '3月15日', title: '随迁子女入学申请开放', level: 'green' }
        ],
        4: [
          { date: '4月10日', title: '小升初信息采集截止', level: 'red' },
          { date: '4月20日', title: '学区划分方案公示', level: 'green' }
        ],
        5: [
          { date: '5月15日', title: '大摇号报名开始', level: 'red' },
          { date: '5月20日', title: '随迁子女申请截止', level: 'orange' },
          { date: '5月25日', title: '学区划分公布', level: 'green' }
        ],
        6: [
          { date: '6月23日', title: '大摇号录取', level: 'red' },
          { date: '6月24日', title: '民办摇号录取', level: 'red' }
        ],
        7: [
          { date: '7月3-4日', title: '学位确认', level: 'red' },
          { date: '7月10-11日', title: '新生报到', level: 'orange' }
        ]
      };
      return events[month] || [];
    },

    async translateJargon() {
      const term = this.jargonInput.trim();
      if (!term) return;

      try {
        const res = await API.translateJargon(term);
        // 后端响应: { success, original, translation, source, related_terms }
        this.jargonResult = {
          term: res.original || term,
          explanation: res.translation || '暂无解释',
          scenario: res.source ? `来源：${res.source}` : '',
          policyRef: (res.related_terms && res.related_terms.length) 
            ? '相关术语：' + res.related_terms.join('、') : ''
        };
      } catch (e) {
        // Fallback to local dictionary
        this.jargonResult = this.localJargon(term);
      }
    },

    localJargon(term) {
      const dict = {
        '大摇号': { term: '大摇号', explanation: '即市级摇号，指成都市教育局统一组织的电脑随机录取，覆盖市直属学校（如石室联中、七中育才、树德实验等）的招生。' },
        '小摇号': { term: '小摇号', explanation: '即区级摇号，指各区教育局组织的电脑随机录取，覆盖区属公办初中的招生。' },
        '统筹': { term: '统筹', explanation: '指教育部门根据学位余量和家庭实际情况，统一安排入学，通常不是第一志愿学校。' },
        '调剂': { term: '调剂', explanation: '在摇号未被录取时，由教育部门安排到有空余学位的学校就读。' },
        '锁区': { term: '锁区', explanation: '指学生只能在户籍所在区入学，不能跨区选择公办学校。' },
        '一对一': { term: '一对一', explanation: '指一个小区对口一所学校，即"单校划片"，直接升入对口学校。' },
        '直升': { term: '直升', explanation: '指九年一贯制学校的学生小学毕业后直接升入本校初中部，无需参加摇号。' }
      };
      return dict[term] || { term, explanation: '暂无解释，请尝试在诊断中咨询参谋。' };
    },

    // === 我的 ===
    login() {
      API.redirectToAuth();
    },

    logout() {
      Alpine.store('app').logout();
    },

    // === 工具 ===
    getStageLabel(stage) {
      return API.getStageLabel(stage);
    },

    getPlanLabel(plan) {
      return API.getPlanLabel(plan);
    },

    formatTime(timestamp) {
      return API.formatTime(timestamp);
    },

    formatMessage(content) {
      if (!content) return '';
      let html = content
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
      return html;
    }
  };
}

// Store 注册由 store.js 统一处理（兼容 app.html 和 pay.html）
