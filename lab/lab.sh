#!/usr/bin/env bash
# NEXORA — Lab management script
# Team: A3-PS035-TC490 | PS-035
#
# Usage: ./lab.sh {up|down|status|verify|logs|restart|failover}
#
# All commands operate ONLY on the nexora project containers.
# Never use system-wide Docker cleanup commands.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
PROJECT_NAME="nexora"
CONTAINERS=(nexora-r1 nexora-r2 nexora-r3 nexora-r4 nexora-r5)
OSPF_CONVERGENCE_TIMEOUT=90  # seconds

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_header()  { echo -e "\n${BLUE}=== $* ===${NC}"; }

# ---------------------------------------------------------------------------
lab_up() {
    log_header "NEXORA Lab — UP"
    log_info "Checking host Linux bridge netfilter state..."
    CURRENT_SYSCTL=$(docker run --rm --net=host alpine sysctl -n net.bridge.bridge-nf-call-iptables 2>/dev/null || echo "unknown")
    if [ "${CURRENT_SYSCTL}" = "0" ]; then
        log_ok "Host Linux bridge netfilter (net.bridge.bridge-nf-call-iptables) is already 0 (no host change required)"
    else
        log_warn "Host Linux bridge filtering (net.bridge.bridge-nf-call-iptables) is currently ${CURRENT_SYSCTL}."
        log_warn "SHARED HOST IMPACT: Nexora data-plane links use re-addressed /30 subnets over Docker bridges."
        log_warn "When bridge-nf-call-iptables=1, host iptables drops cross-bridge /30 packets."
        log_warn "Modifying this sysctl alters the entire Docker host VM and affects co-located projects (e.g. FaultLens)."
        if [ "${NEXORA_PERMIT_HOST_SYSCTL:-0}" = "1" ]; then
            log_info "NEXORA_PERMIT_HOST_SYSCTL=1 detected. Recording original sysctl state..."
            SYSCTL_STATE_FILE="${SCRIPT_DIR}/.sysctl_state.json"
            if [ ! -f "${SYSCTL_STATE_FILE}" ]; then
                cat <<EOF > "${SYSCTL_STATE_FILE}"
{
  "original_bridge_nf_call_iptables": "${CURRENT_SYSCTL}",
  "recorded_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "modified_by_project": "nexora"
}
EOF
                log_ok "Saved original host sysctl state to ${SYSCTL_STATE_FILE}"
            fi
            log_info "Configuring host bridge filtering to 0..."
            docker run --rm --privileged --net=host alpine sysctl -w net.bridge.bridge-nf-call-iptables=0 >/dev/null 2>&1 || true
            docker run --rm --privileged --net=host alpine sysctl -w net.bridge.bridge-nf-call-ip6tables=0 >/dev/null 2>&1 || true
        else
            log_warn "Host sysctl change was NOT permitted. Run with NEXORA_PERMIT_HOST_SYSCTL=1 to permit this change explicitly."
            log_warn "Proceeding with lab startup, but inter-router data plane packets may be dropped if bridge-nf-call-iptables remains 1."
        fi
    fi
    log_info "Starting five-router OSPF ring..."
    docker compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" up -d
    log_info "Waiting ${OSPF_CONVERGENCE_TIMEOUT}s for OSPF convergence..."
    sleep "${OSPF_CONVERGENCE_TIMEOUT}"
    log_ok "Lab started. Run './lab.sh verify' to validate OSPF state."
}

# ---------------------------------------------------------------------------
lab_down() {
    log_header "NEXORA Lab — DOWN"
    log_info "Stopping and removing NEXORA containers only..."
    docker compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" down --volumes=false
    log_info "Host sysctl net.bridge.bridge-nf-call-iptables preserved to prevent disruption to concurrent projects."
    log_info "Run './lab.sh restore-sysctl' if you wish to restore the recorded host sysctl setting."
    log_ok "NEXORA lab stopped. FaultLens and other projects unaffected."
}

# ---------------------------------------------------------------------------
restore_sysctl() {
    log_header "NEXORA Lab — RESTORE HOST SYSCTL"
    SYSCTL_STATE_FILE="${SCRIPT_DIR}/.sysctl_state.json"
    if [ ! -f "${SYSCTL_STATE_FILE}" ]; then
        log_warn "No recorded sysctl state found at ${SYSCTL_STATE_FILE}. Nexora did not record any host modification."
        return 0
    fi
    ORIG_VAL=$(grep -o '"original_bridge_nf_call_iptables": *"[^"]*"' "${SYSCTL_STATE_FILE}" | cut -d'"' -f4 || echo "")
    if [ -z "${ORIG_VAL}" ]; then
        log_error "Could not parse original sysctl value from ${SYSCTL_STATE_FILE}"
        return 1
    fi
    log_warn "Shared-Host Impact: Other running projects (e.g. FaultLens) may currently rely on net.bridge.bridge-nf-call-iptables=0."
    log_warn "Restoring host sysctl to ${ORIG_VAL} may disrupt active Docker networks."
    if [ "${NEXORA_PERMIT_HOST_SYSCTL:-0}" != "1" ]; then
        log_error "Explicit operator approval required to restore host sysctl. Run with: NEXORA_PERMIT_HOST_SYSCTL=1 ./lab.sh restore-sysctl"
        return 1
    fi
    docker run --rm --privileged --net=host alpine sysctl -w "net.bridge.bridge-nf-call-iptables=${ORIG_VAL}" >/dev/null 2>&1 || true
    docker run --rm --privileged --net=host alpine sysctl -w "net.bridge.bridge-nf-call-ip6tables=${ORIG_VAL}" >/dev/null 2>&1 || true
    rm -f "${SYSCTL_STATE_FILE}"
    log_ok "Restored host net.bridge.bridge-nf-call-iptables=${ORIG_VAL} and removed state file."
}

# ---------------------------------------------------------------------------
lab_status() {
    log_header "NEXORA Lab — STATUS"
    log_info "Container status:"
    docker compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" ps

    log_info "OSPF neighbor tables:"
    for ctr in "${CONTAINERS[@]}"; do
        echo -e "\n${BLUE}--- ${ctr} ---${NC}"
        docker exec "${ctr}" vtysh -c "show ip ospf neighbor" 2>/dev/null \
            | grep -v "^%" || log_warn "${ctr}: vtysh not ready"
    done
}

# ---------------------------------------------------------------------------
lab_verify() {
    log_header "NEXORA Lab — VERIFY"
    FAILURES=0

    # 1. Five containers running
    log_info "Check 1: Five router containers running"
    RUNNING=$(docker compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" ps --status running --quiet | wc -l | tr -d ' ')
    if [ "${RUNNING}" -eq 5 ]; then
        log_ok "All 5 containers running (${RUNNING}/5)"
    else
        log_error "Expected 5 running containers, found ${RUNNING}"
        FAILURES=$((FAILURES + 1))
    fi

    # 2. Five data-plane networks
    log_info "Check 2: Five data-plane networks exist"
    NETS=$(docker network ls --format '{{.Name}}' | grep -c "^nexora_net_l" || true)
    if [ "${NETS}" -eq 5 ]; then
        log_ok "All 5 data networks present (${NETS}/5)"
    else
        log_error "Expected 5 nexora_net_l* networks, found ${NETS}"
        FAILURES=$((FAILURES + 1))
    fi

    # 3. Interface IP assignments
    log_info "Check 3: Interface IP assignments"
    get_expected_ips() {
        case "$1" in
            nexora-r1) echo "192.168.255.1 10.0.12.1 10.0.15.2" ;;
            nexora-r2) echo "192.168.255.2 10.0.12.2 10.0.23.1" ;;
            nexora-r3) echo "192.168.255.3 10.0.23.2 10.0.34.1" ;;
            nexora-r4) echo "192.168.255.4 10.0.34.2 10.0.45.1" ;;
            nexora-r5) echo "192.168.255.5 10.0.45.2 10.0.15.1" ;;
        esac
    }
    for ctr in "${CONTAINERS[@]}"; do
        ADDRS=$(docker exec "${ctr}" ip addr 2>/dev/null)
        for ip in $(get_expected_ips "${ctr}"); do
            if echo "${ADDRS}" | grep -q "${ip}"; then
                log_ok "${ctr}: ${ip} present"
            else
                log_error "${ctr}: ${ip} MISSING"
                FAILURES=$((FAILURES + 1))
            fi
        done
    done

    # 4. OSPF FULL adjacencies
    log_info "Check 4: OSPF FULL adjacencies (expect 10 total, 2 per router)"
    TOTAL_FULL=0
    for ctr in "${CONTAINERS[@]}"; do
        FULL=$(docker exec "${ctr}" vtysh -c "show ip ospf neighbor" 2>/dev/null \
            | grep -c "Full" || true)
        log_info "${ctr}: ${FULL} FULL adjacencies"
        TOTAL_FULL=$((TOTAL_FULL + FULL))
    done
    if [ "${TOTAL_FULL}" -eq 10 ]; then
        log_ok "All 10 directional OSPF adjacencies are FULL (${TOTAL_FULL}/10)"
    else
        log_error "Expected 10 FULL adjacencies, found ${TOTAL_FULL}"
        FAILURES=$((FAILURES + 1))
    fi

    # 5. Loopback reachability
    log_info "Check 5: Loopback reachability (cross-router pings)"
    get_loopback() {
        case "$1" in
            nexora-r1) echo "192.168.255.1" ;;
            nexora-r2) echo "192.168.255.2" ;;
            nexora-r3) echo "192.168.255.3" ;;
            nexora-r4) echo "192.168.255.4" ;;
            nexora-r5) echo "192.168.255.5" ;;
        esac
    }
    PING_FAIL=0
    for src_ctr in "${CONTAINERS[@]}"; do
        for dst_ctr in "${CONTAINERS[@]}"; do
            if [ "${src_ctr}" = "${dst_ctr}" ]; then continue; fi
            DST_IP=$(get_loopback "${dst_ctr}")
            if docker exec "${src_ctr}" ping -c 2 -W 2 "${DST_IP}" >/dev/null 2>&1; then
                log_ok "${src_ctr} -> ${DST_IP} (${dst_ctr}): reachable"
            else
                log_error "${src_ctr} -> ${DST_IP} (${dst_ctr}): UNREACHABLE"
                PING_FAIL=$((PING_FAIL + 1))
                FAILURES=$((FAILURES + 1))
            fi
        done
    done

    # 6. Routing tables contain OSPF routes
    log_info "Check 6: OSPF routes in routing tables"
    for ctr in "${CONTAINERS[@]}"; do
        OSPF_ROUTES=$(docker exec "${ctr}" vtysh -c "show ip route ospf" 2>/dev/null \
            | grep -c "^O" || true)
        if [ "${OSPF_ROUTES}" -ge 4 ]; then
            log_ok "${ctr}: ${OSPF_ROUTES} OSPF routes (≥4 expected)"
        else
            log_error "${ctr}: only ${OSPF_ROUTES} OSPF routes (expect ≥4)"
            FAILURES=$((FAILURES + 1))
        fi
    done

    # 7. Management network not used as transit
    log_info "Check 7: Management (192.168.100.0/24) not in OSPF LSDB"
    for ctr in "${CONTAINERS[@]}"; do
        MGMT_IN_OSPF=$(docker exec "${ctr}" vtysh -c "show ip ospf database" 2>/dev/null \
            | grep -c "192.168.100" || true)
        if [ "${MGMT_IN_OSPF}" -eq 0 ]; then
            log_ok "${ctr}: management subnet not in OSPF LSDB"
        else
            log_error "${ctr}: management subnet FOUND in OSPF LSDB — isolation BROKEN"
            FAILURES=$((FAILURES + 1))
        fi
    done

    # Summary
    echo ""
    if [ "${FAILURES}" -eq 0 ]; then
        log_ok "ALL CHECKS PASSED — NEXORA lab is fully operational"
        return 0
    else
        log_error "${FAILURES} check(s) FAILED"
        return 1
    fi
}

# ---------------------------------------------------------------------------
lab_logs() {
    log_header "NEXORA Lab — LOGS"
    ROUTER="${2:-}"
    if [ -n "${ROUTER}" ]; then
        docker logs "nexora-${ROUTER}" --tail=50
    else
        docker compose -f "${COMPOSE_FILE}" -p "${PROJECT_NAME}" logs --tail=20
    fi
}

# ---------------------------------------------------------------------------
lab_restart() {
    log_header "NEXORA Lab — RESTART"
    lab_down
    sleep 5
    lab_up
}

# ---------------------------------------------------------------------------
# Failover smoke test: temporarily disable R1-R2 link (L12)
# Records route changes and verifies alternate path exists.
# Always restores the baseline.
failover_test() {
    log_header "NEXORA Lab — FAILOVER SMOKE TEST (L12: R1-R2)"
    TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
    REPORT_DIR="${SCRIPT_DIR}/../docs/phase-reports"
    REPORT="${REPORT_DIR}/failover-${TIMESTAMP}.txt"
    mkdir -p "${REPORT_DIR}"
    FAILED=0

    {
        echo "NEXORA Failover Smoke Test — ${TIMESTAMP}"
        echo "Link under test: L12 (R1 eth1 <-> R2 eth1)"
        echo ""

        echo "--- PRE-FAILOVER: R1 routing table ---"
        docker exec nexora-r1 vtysh -c "show ip route ospf" 2>/dev/null
        echo ""
        echo "--- PRE-FAILOVER: R1 OSPF neighbors ---"
        docker exec nexora-r1 vtysh -c "show ip ospf neighbor" 2>/dev/null
        echo ""

        echo "--- INJECTING FAULT: disabling eth1 on nexora-r1 ---"
        docker exec nexora-r1 ip link set eth1 down 2>/dev/null && echo "eth1 DOWN on nexora-r1"
        echo "Waiting 60s for OSPF reconvergence..."
    } | tee "${REPORT}"

    sleep 60

    {
        echo ""
        echo "--- POST-FAILOVER: R1 OSPF neighbors ---"
        docker exec nexora-r1 vtysh -c "show ip ospf neighbor" 2>/dev/null
        echo ""
        echo "--- POST-FAILOVER: R1 routing table ---"
        docker exec nexora-r1 vtysh -c "show ip route ospf" 2>/dev/null
        echo ""

        # Check R1 can still reach R2's loopback via alternate path
        echo "--- Alternate path test: R1 -> 192.168.255.2 (R2 loopback) ---"
        if docker exec nexora-r1 ping -c 4 -W 3 192.168.255.2 2>/dev/null; then
            echo "ALTERNATE PATH: REACHABLE"
        else
            echo "ALTERNATE PATH: UNREACHABLE — FAIL"
            FAILED=1
        fi

        echo ""
        echo "--- RESTORING FAULT: re-enabling eth1 on nexora-r1 ---"
        docker exec nexora-r1 ip link set eth1 up 2>/dev/null && echo "eth1 UP on nexora-r1"
        echo "Waiting 60s for OSPF re-convergence..."
    } | tee -a "${REPORT}"

    sleep 60

    {
        echo ""
        echo "--- POST-RESTORE: R1 OSPF neighbors ---"
        docker exec nexora-r1 vtysh -c "show ip ospf neighbor" 2>/dev/null
        echo ""
        echo "--- POST-RESTORE: R1 routing table ---"
        docker exec nexora-r1 vtysh -c "show ip route ospf" 2>/dev/null
        echo ""
        echo "Failover test complete. Report saved to: ${REPORT}"
    } | tee -a "${REPORT}"

    return ${FAILED}
}

# ---------------------------------------------------------------------------
fault_cmd() {
    cd "${SCRIPT_DIR}/../backend" && PYTHONPATH=".:.." uv run python -m lab.fault_injection.cli "$@"
}

# ---------------------------------------------------------------------------
CMD="${1:-help}"
case "${CMD}" in
    up)                    lab_up ;;
    down)                  lab_down ;;
    status)                lab_status ;;
    verify)                lab_verify ;;
    logs)                  lab_logs "$@" ;;
    restart)               lab_restart ;;
    failover)              failover_test ;;
    restore-sysctl)        restore_sysctl ;;
    fault-list)            shift; fault_cmd list "$@" ;;
    fault-status)          shift; fault_cmd status "$@" ;;
    fault-observe)         shift; fault_cmd observe "$@" ;;
    fault-inject)          shift; fault_cmd inject "$@" ;;
    fault-reset)           shift; fault_cmd reset "$@" ;;
    fault-emergency-reset) shift; fault_cmd emergency-reset "$@" ;;
    fault-run)             shift; fault_cmd run "$@" ;;
    help|*)
        echo "Usage: $0 {up|down|status|verify|logs [router]|restart|failover|restore-sysctl|fault-*}"
        echo ""
        echo "  up                    Start the NEXORA five-router OSPF lab"
        echo "  down                  Stop and remove NEXORA lab containers only"
        echo "  status                Show container and OSPF neighbor status"
        echo "  verify                Run all connectivity and OSPF verification checks"
        echo "  logs                  Show container logs (optional: specify router e.g. r1)"
        echo "  restart               Teardown and restart the lab"
        echo "  failover              Run L12 link-failure smoke test"
        echo "  restore-sysctl        Restore original host sysctl setting recorded before lab startup"
        echo "  fault-list            List all available fault injection scenarios"
        echo "  fault-status          Check active fault experiment status"
        echo "  fault-observe         Print current network observation snapshot"
        echo "  fault-inject <scen>   Inject a fault (e.g. F1, F2, F3, F4, F5)"
        echo "  fault-reset           Safely restore active fault"
        echo "  fault-emergency-reset Idempotently reset all interfaces, qdiscs, and OSPF timers"
        echo "  fault-run <scen>      Run complete experiment lifecycle with structured report"
        ;;
esac
