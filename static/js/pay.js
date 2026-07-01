/* ============================================
   点灯蛙 支付页逻辑 v2.0
   对齐后端：/api/payment/price-tiers, /api/payment/purchase-diagnoses
   ============================================ */

function payPage() {
  return {
    paying: false,
    priceTiers: [],
    faqOpen: 0,

    init() {
      // 加载定价信息
      this.loadPriceTiers();

      // 检查URL参数（支付回调）
      const params = new URLSearchParams(window.location.search);
      const status = params.get('status');
      const msg = params.get('msg');

      if (status === 'success') {
        alert('支付成功！诊断次数已到账。');
        window.location.href = '/app?tab=profile';
      } else if (status === 'fail') {
        alert('支付失败：' + (msg || '请重试'));
        window.history.replaceState({}, '', '/pay');
      }
    },

    async loadPriceTiers() {
      try {
        const res = await API.getPriceTiers();
        if (Array.isArray(res)) {
          this.priceTiers = res;
        } else if (res.tiers) {
          this.priceTiers = res.tiers;
        }
      } catch (e) {
        console.error('Load price tiers error:', e);
      }
    },

    async purchase(credits) {
      if (!Alpine.store('app').user.isLoggedIn) {
        if (confirm('请先通过微信登录后再购买。是否前往登录？')) {
          API.redirectToAuth();
        }
        return;
      }

      this.paying = true;

      try {
        const res = await API.purchaseDiagnoses(credits);

        // 后端返回支付参数
        if (res.pay_url) {
          // H5支付跳转
          window.location.href = res.pay_url;
        } else if (res.jsapi_params || res.jsApiParams) {
          // JSAPI 支付
          const params = res.jsapi_params || res.jsApiParams;
          if (typeof WeixinJSBridge !== 'undefined') {
            WeixinJSBridge.invoke('getBrandWCPayRequest', params, (r) => {
              if (r.err_msg === 'get_brand_wcpay_request:ok') {
                window.location.href = '/pay?status=success';
              } else {
                this.paying = false;
                window.location.href = '/pay?status=fail&msg=' + encodeURIComponent(r.err_msg);
              }
            });
          } else {
            // 非微信环境，提示扫码或跳转
            this.paying = false;
            alert('请在微信中打开此页面完成支付');
          }
        } else if (res.qrcode_url) {
          // 扫码支付
          this.paying = false;
          window.open(res.qrcode_url, '_blank');
        } else {
          // 模拟模式或未知响应
          this.paying = false;
          alert('支付功能正在配置中，请稍后重试。');
        }
      } catch (e) {
        this.paying = false;
        alert('支付请求失败：' + e.message);
      }
    },

    toggleFaq(idx) {
      this.faqOpen = this.faqOpen === idx ? 0 : idx;
    }
  };
}
