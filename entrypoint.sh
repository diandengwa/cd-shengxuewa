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
mkdir -p /app/logs /app/pipeline-logs /app/logs/locks
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

# === 启动时立即执行当天未完成的流水线 ===
echo "[$(date)] Running pending stages from today..." | tee -a $PIPELINE_LOG
run_collect
run_mine
run_generate
run_review
run_publish_prep
echo "[$(date)] All pending stages completed. Entering watch loop." | tee -a $PIPELINE_LOG

# === 主循环：每小时检查是否需要重新执行 ===
# 每个整点检查，如果当天还有未完成的stage则执行
echo "[$(date)] Entering main loop..." | tee -a $PIPELINE_LOG

while true; do
    CURRENT_HOUR=$(date +%H)
    CURRENT_MIN=$(date +%M)
    
    # 每个整点（0-5分）检查并执行未完成的stage
    if [ "$CURRENT_MIN" -ge "0" ] && [ "$CURRENT_MIN" -lt "5" ]; then
        # 检查是否有未完成的stage
        TODAY=$(date +%Y%m%d)
        ALL_DONE=1
        for stage in collect mine generate review publish; do
            if [ ! -f "$LOCK_DIR/.${stage}_done_$TODAY" ]; then
                ALL_DONE=0
                break
            fi
        done
        
        if [ "$ALL_DONE" = "0" ]; then
            echo "[$(date)] Found incomplete stages, running pipeline..." | tee -a $PIPELINE_LOG
            run_collect
            run_mine
            run_generate
            run_review
            run_publish_prep
        fi
    fi
    
    # 每5分钟执行一次健康检查（后台）
    if [ $(( $(date +%M) % 5 )) -eq 0 ]; then
        python /app/scripts/health_check.py > /dev/null 2>&1 || true
    fi
    
    sleep 60
done
