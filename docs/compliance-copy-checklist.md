# 点灯蛙 合规文案检查清单

> 每次PR提交前必须逐项检查，确认无违规文案。检查人：提交者 + Reviewer。

## 一、禁用词检查

| 禁用词 | 替换为 | 检查范围 |
|--------|--------|----------|
| AI诊断 | 参谋诊断 / 专家研判 | 全部HTML/JS/PY |
| AI助手 | 升学参谋 / 点灯蛙参谋 | 全部HTML/JS/PY |
| AI分析 | 规则匹配与模型辅助分析 | 全部HTML/JS/PY |
| 我是AI | 我是点灯蛙参谋 | 全部HTML/JS/PY |
| 作为AI | 作为升学参谋 | 全部HTML/JS/PY |
| 人工智能诊断 | 参谋研判 | 全部HTML/JS/PY |

**例外**：法规名称《生成式人工智能服务管理暂行办法》、公司全称"北京深度求索人工智能基础技术研究有限公司"属法定名称，可保留。

## 二、免责声明检查

以下页面必须包含免责声明（"不构成录取保证或入学承诺"表述）：

- [ ] `app.html` 诊断声明弹窗
- [ ] `app.html` 诊断结果区域
- [ ] `pay.html` 底部免责声明
- [ ] `compliance.html` Section D
- [ ] `terms.html` Section E
- [ ] `about.html` 价值观卡片
- [ ] `index.html` 套餐区脚注

## 三、模型信息公示检查

`compliance.html` Section B 必须包含：
- [ ] 模型名称：DeepSeek大语言模型
- [ ] 提供方：北京深度求索人工智能基础技术研究有限公司
- [ ] 算法备案号：网信算备110108970550101240011号
- [ ] 数据不入训练承诺

## 四、未成年人保护检查

- [ ] 无采集孩子姓名/身份证号的输入框
- [ ] 家庭画像字段使用枚举（下拉/标签），无自由文本
- [ ] 无诱导未成年人消费的文案

## 五、内容安全检查

- [ ] `answerer.py` 输入端 `filter_prohibited()` 已调用
- [ ] `answerer.py` 输出端 Step2/Step3/Step4 已调用 `filter_prohibited()`
- [ ] `compliance.html` 关于"对用户输入和模型输出进行敏感词检测"的声明与实现一致

## 六、备案信息检查

所有页面页脚必须包含：
- [ ] ICP备案号：蜀ICP备2026032729号
- [ ] 公安联网备案号：川公网安备51015602001931号
- [ ] 公安备案链接指向：https://beian.mps.gov.cn/#/query/webSearch?code=51015602001931

## 七、拟人化互动检查

- [ ] 表情符号仅表达任务状态（💡分析中、✅完成、⚠️风险）
- [ ] 无表达亲密关系的表情（❤️😘🤗等）
- [ ] 参谋角色定位为"专业顾问"，不模拟真人情感关系
- [ ] system prompt 中无"我是你的朋友/伙伴"等拟人化表述

## 八、域名一致性检查

- [ ] `.env` 中 CORS_ORIGINS = https://www.diandengwa.com
- [ ] `.env` 中 PAY_NOTIFY_URL = https://www.diandengwa.com/...
- [ ] `docker-compose.yml` 中 BASE_URL = https://www.diandengwa.com
- [ ] HTML中所有内部链接使用相对路径或 diandengwa.com

---

**检查日期**：2026-07-01  
**版本**：v1.0  
**维护人**：点灯蛙开发团队
