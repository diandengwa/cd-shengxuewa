-- ============================================================
-- migrations/002_add_diagnosis_credits.sql
-- 付费模式重构 — 按次诊断计费方案
-- 功能: 在 family_profiles 表新增 diagnosis_credits 字段，
--       并创建 payment_records 表记录支付流水
-- ============================================================

-- 开启事务
BEGIN TRANSACTION;

-- ============================================================
-- 1. 检查并添加 diagnosis_credits 字段到 family_profiles 表
-- ============================================================
-- 如果字段不存在则添加，默认值为 0（免费用户初始额度）
-- 字段说明: 剩余诊断次数，每次诊断消耗 1 次
ALTER TABLE family_profiles ADD COLUMN diagnosis_credits INTEGER NOT NULL DEFAULT 0;

-- 为已有用户设置默认初始额度（可选，根据业务需求调整）
-- 此处设置所有现有用户初始额度为 3 次（体验额度）
UPDATE family_profiles SET diagnosis_credits = 3 WHERE diagnosis_credits IS NULL OR diagnosis_credits = 0;

-- ============================================================
-- 2. 创建 payment_records 表
-- ============================================================
-- 表说明: 记录所有支付流水，包括微信支付、支付宝等
-- 字段说明:
--   id: 主键，自增
--   family_id: 关联 family_profiles 表的用户ID
--   order_no: 商户订单号，唯一
--   transaction_id: 第三方支付平台交易号（微信/支付宝）
--   payment_method: 支付方式（wechat/alipay/balance）
--   amount: 支付金额（单位：分，避免浮点数精度问题）
--   credits_purchased: 购买的诊断次数
--   status: 支付状态（pending/success/failed/refunded）
--   pay_time: 支付完成时间
--   created_at: 记录创建时间
--   updated_at: 记录更新时间
--   remark: 备注信息（如套餐名称、活动信息等）
CREATE TABLE IF NOT EXISTS payment_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id INTEGER NOT NULL,
    order_no VARCHAR(64) NOT NULL UNIQUE,
    transaction_id VARCHAR(128) DEFAULT NULL,
    payment_method VARCHAR(20) NOT NULL DEFAULT 'wechat',
    amount INTEGER NOT NULL COMMENT '金额单位：分',
    credits_purchased INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    pay_time DATETIME DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    remark TEXT DEFAULT NULL,
    FOREIGN KEY (family_id) REFERENCES family_profiles(id) ON DELETE CASCADE
);

-- 创建索引以加速查询
CREATE INDEX IF NOT EXISTS idx_payment_records_family_id ON payment_records(family_id);
CREATE INDEX IF NOT EXISTS idx_payment_records_order_no ON payment_records(order_no);
CREATE INDEX IF NOT EXISTS idx_payment_records_status ON payment_records(status);
CREATE INDEX IF NOT EXISTS idx_payment_records_created_at ON payment_records(created_at);

-- ============================================================
-- 3. 创建触发器：支付成功后自动更新用户诊断次数
-- ============================================================
-- 当 payment_records 状态更新为 'success' 时，
-- 自动增加对应用户的 diagnosis_credits
CREATE TRIGGER IF NOT EXISTS trg_payment_success_update_credits
AFTER UPDATE OF status ON payment_records
WHEN NEW.status = 'success' AND OLD.status != 'success'
BEGIN
    UPDATE family_profiles
    SET diagnosis_credits = diagnosis_credits + NEW.credits_purchased,
        updated_at = datetime('now', 'localtime')
    WHERE id = NEW.family_id;
END;

-- ============================================================
-- 4. 创建触发器：记录更新时间
-- ============================================================
CREATE TRIGGER IF NOT EXISTS trg_payment_records_updated_at
AFTER UPDATE ON payment_records
BEGIN
    UPDATE payment_records SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

-- ============================================================
-- 5. 数据迁移说明（注释）
-- ============================================================
-- 注意：此迁移脚本执行后，需要同步更新以下内容：
--   - app/models.py: 更新 FamilyProfile 模型，添加 diagnosis_credits 字段
--   - app/schemas.py: 更新 Pydantic 模型
--   - app/services/payment_service.py: 实现支付逻辑
--   - app/routers/diagnosis.py: 诊断前检查次数并扣减
--   - app/routers/payment.py: 支付相关接口
--   - app/templates/: 更新前端页面显示剩余次数

-- 提交事务
COMMIT;

-- ============================================================
-- 回滚脚本（用于迁移失败时回滚）
-- ============================================================
-- 如需回滚，执行以下语句：
-- BEGIN TRANSACTION;
-- DROP TRIGGER IF EXISTS trg_payment_success_update_credits;
-- DROP TRIGGER IF EXISTS trg_payment_records_updated_at;
-- DROP TABLE IF EXISTS payment_records;
-- -- 注意：删除字段需要重建表，此处仅作注释
-- -- ALTER TABLE family_profiles DROP COLUMN diagnosis_credits; -- SQLite 不支持直接删除列
-- COMMIT;