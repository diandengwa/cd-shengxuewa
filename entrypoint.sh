#!/bin/bash
# OPC Content Factory - Production Pipeline Entrypoint
# 运行实际的生产流水线（替代纯健康检查循环）

# NOTE: Do NOT use 'set -e' — health check failures must not kill the container

export OPC_ROOT=/app
export PYTHONPATH=/app
export LOG_LEVEL=${LOG_LEVEL:-INFO}
export DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}

echo "=========================================="
echo "OPC Content Factory - Production Mode"
echo "Time: $(date)"
echo "=========================================="

# 健康检查（启动前验证）
echo "[$(date)] Running health check..."
python /app/scripts/health_check.py || echo "[$(date)] WARNING: Health check reported issues, continuing anyway..."

# 创建日志目录
mkdir -p /app/logs
PIPELINE_LOG="/app/logs/pipeline_$(date +%Y%m%d).log"

echo "[$(date)] Starting production pipeline..." | tee -a $PIPELINE_LOG

# 定义执行锁文件（防止重复执行）
LOCK_DIR="/app/logs/locks"

mkdir -p $LOCK_DIR

# 采集阶段
run_collect() {
    LOCK_FILE="$LOCK_DIR/.collect_done_$(date +%Y%m%d)"
    if [ -f "$LOCK_FILE" ]; then
        echo "[$(date)] SKIP: opc_collect already run today" | tee -a $PIPELINE_LOG
        return 0
    fi
    
    echo "[$(date)] === STAGE 1: opc_collect ===" | tee -a $PIPELINE_LOG
    python /app/scripts/opc_collect.py 2>&1 | tee -a $PIPELINE_LOG
    echo "[$(date)] === STAGE 1 COMPLETE ===" | tee -a $PIPELINE_LOG
    touch "$LOCK_FILE"
}

# 采矿阶段
run_mine() {
    LOCK_FILE="$LOCK_DIR/.mine_done_$(date +%Y%m%d)"
    if [ -f "$LOCK_FILE" ]; then
        echo "[$(date)] SKIP: opc_mine already run today" | tee -a $PIPELINE_LOG
        return 0
    fi
    
    echo "[$(date)] === STAGE 2: opc_mine ===" | tee -a $PIPELINE_LOG
    python /app/scripts/opc_mine.py 2>&1 | tee -a $PIPELINE_LOG
    echo "[$(date)] === STAGE 2 COMPLETE ===" | tee -a $PIPELINE_LOG
    touch "$LOCK_FILE"
}

# 生成阶段
run_generate() {
    LOCK_FILE="$LOCK_DIR/.generate_done_$(date +%Y%m%d)"
    if [ -f "$LOCK_FILE" ]; then
        echo "[$(date)] SKIP: opc_generate already run today" | tee -a $PIPELINE_LOG
        return 0
    fi
    
    echo "[$(date)] === STAGE 3: opc_generate ===" | tee -a $PIPELINE_LOG
    python /app/scripts/opc_generate.py 2>&1 | tee -a $PIPELINE_LOG
    echo "[$(date)] === STAGE 3 COMPLETE ===" | tee -a $PIPELINE_LOG
    touch "$LOCK_FILE"
}

# 审稿阶段
run_review() {
    LOCK_FILE="$LOCK_DIR/.review_done_$(date +%Y%m%d)"
    if [ -f "$LOCK_FILE" ]; then
        echo "[$(date)] SKIP: opc_review already run today" | tee -a $PIPELINE_LOG
        return 0
    fi
    
    echo "[$(date)] === STAGE 4: opc_review ===" | tee -a $PIPELINE_LOG
    python /app/scripts/opc_pipeline.py review_stage 2>&1 | tee -a $PIPELINE_LOG
    echo "[$(date)] === STAGE 4 COMPLETE ===" | tee -a $PIPELINE_LOG
    touch "$LOCK_FILE"
}

# 发布准备阶段
run_publish_prep() {
    LOCK_FILE="$LOCK_DIR/.publish_done_$(date +%Y%m%d)"
    if [ -f "$LOCK_FILE" ]; then
        echo "[$(date)] SKIP: opc_publish_prep already run today" | tee -a $PIPELINE_LOG
        return 0
    fi
    
    echo "[$(date)] === STAGE 5: opc_publish_prep ===" | tee -a $PIPELINE_LOG
    python /app/scripts/opc_pipeline.py publish_prep_stage 2>&1 | tee -a $PIPELINE_LOG
    echo "[$(date)] === STAGE 5 COMPLETE ===" | tee -a $PIPELINE_LOG
    touch "$LOCK_FILE"
}

# 主循环：按时间表执行pipeline
echo "[$(date)] Entering main loop..." | tee -a $PIPELINE_LOG

while true; do
    CURRENT_HOUR=$(date +%H)
    CURRENT_MIN=$(date +%M)
    
    # 17:00 执行采集
    if [ "$CURRENT_HOUR" = "17" ] && [ "$CURRENT_MIN" -ge "0" ] && [ "$CURRENT_MIN" -lt "5" ]; then
        run_collect
    
    # 17:30 执行采矿
    elif [ "$CURRENT_HOUR" = "17" ] && [ "$CURRENT_MIN" -ge "30" ] && [ "$CURRENT_MIN" -lt "35" ]; then
        run_mine
    
    # 18:00 执行生成
    elif [ "$CURRENT_HOUR" = "18" ] && [ "$CURRENT_MIN" -ge "0" ] && [ "$CURRENT_MIN" -lt "5" ]; then
        run_generate
    
    # 18:30 执行审稿
    elif [ "$CURRENT_HOUR" = "18" ] && [ "$CURRENT_MIN" -ge "30" ] && [ "$CURRENT_MIN" -lt "35" ]; then
        run_review
    
    # 18:50 执行发布准备
    elif [ "$CURRENT_HOUR" = "18" ] && [ "$CURRENT_MIN" -ge "50" ]; then
        run_publish_prep
    fi
    
    # 每5分钟执行一次健康检查（后台）
    if [ $(( $(date +%M) % 5 )) -eq 0 ]; then
        python /app/scripts/health_check.py > /dev/null 2>&1 || true
    fi
    
    sleep 60
done
