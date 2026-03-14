#!/bin/bash
# Docker 容器出口带宽限速脚本
# 使用 nsenter + tc HTB 进行容器出向流量限速
#
# GitHub: https://github.com/yang12535/xiaomi-camera-pipeline
# Version: v1.2.4
#
# 用法:
#   ./limit-container-bandwidth.sh <容器名> [限速] [操作]
#
# 参数:
#   容器名    Docker 容器名称（必填）
#   限速      限速值，如 10mbit, 1mbit, 100kbit（默认: 10mbit）
#   操作      setup(设置), clear(清除), status(查看状态)（默认: setup）
#
# 示例:
#   ./limit-container-bandwidth.sh openlist-test 10mbit setup
#   ./limit-container-bandwidth.sh openlist-test 10mbit status
#   ./limit-container-bandwidth.sh openlist-test clear

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# 参数解析
CONTAINER_NAME="${1:-}"
LIMIT_RATE="${2:-10mbit}"
ACTION="${3:-setup}"

# 验证参数
if [ -z "$CONTAINER_NAME" ]; then
    log_error "请指定容器名称"
    echo "用法: $0 <容器名> [限速] [setup|clear|status]"
    echo "示例: $0 openlist-test 10mbit setup"
    exit 1
fi

# 检查容器是否运行
if ! docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    log_error "容器 '${CONTAINER_NAME}' 未运行"
    exit 1
fi

# 获取容器信息
CONTAINER_ID=$(docker inspect -f "{{.Id}}" "${CONTAINER_NAME}" | head -c 12)
CONTAINER_PID=$(docker inspect -f "{{.State.Pid}}" "${CONTAINER_NAME}")

log_debug "容器: ${CONTAINER_NAME} (${CONTAINER_ID})"
log_debug "PID: ${CONTAINER_PID}"
log_debug "限速: ${LIMIT_RATE}"

# 在容器内执行 tc 命令
ns_tc() {
    nsenter -t "${CONTAINER_PID}" -n tc "$@"
}

# 清理限速规则
clear_limit() {
    log_info "清理 ${CONTAINER_NAME} 的限速规则..."
    
    if ns_tc qdisc del dev eth0 root 2>/dev/null; then
        log_info "限速规则已清除"
    else
        log_warn "没有可清除的限速规则"
    fi
}

# 设置限速规则（使用 HTB）
setup_limit_htb() {
    log_info "设置 HTB 限速: ${LIMIT_RATE}..."
    
    # 清理旧规则
    ns_tc qdisc del dev eth0 root 2>/dev/null || true
    
    # 添加 HTB qdisc
    ns_tc qdisc add dev eth0 root handle 1: htb default 10
    
    # 添加限速 class
    ns_tc class add dev eth0 parent 1: classid 1:10 htb \
        rate "${LIMIT_RATE}" \
        ceil "${LIMIT_RATE}" \
        burst 1600b \
        cburst 1600b
    
    log_info "限速已设置完成"
}

# 显示状态
show_status() {
    echo ""
    echo "=== ${CONTAINER_NAME} 限速状态 ==="
    
    echo ""
    echo "[QDisc 配置]"
    ns_tc qdisc show dev eth0 2>/dev/null || echo "  无配置"
    
    echo ""
    echo "[Class 配置]"
    ns_tc class show dev eth0 2>/dev/null || echo "  无配置"
    
    echo ""
    echo "[统计信息]"
    ns_tc -s class show dev eth0 2>/dev/null | grep -E "class|Sent|rate" || echo "  无统计"
}

# 主逻辑
case "${ACTION}" in
    setup|s|start)
        setup_limit_htb
        show_status
        ;;
    clear|clean|c|stop)
        clear_limit
        ;;
    status|st)
        show_status
        ;;
    restart|re)
        clear_limit
        setup_limit_htb
        show_status
        ;;
    *)
        log_error "未知操作: ${ACTION}"
        echo "支持的操作: setup(设置), clear(清除), status(状态), restart(重启)"
        exit 1
        ;;
esac

exit 0
