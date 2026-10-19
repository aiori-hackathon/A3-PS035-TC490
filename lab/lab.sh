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
    log_info "Ensuring host Linux bridge filtering does not drop inter-container frames..."
    docker run --rm --privileged --net=host alpine sysctl -w net.bridge.bridge-nf-call-iptables=0 >/dev/null 2>&1 || true
    docker run --rm --privileged --net=host alpine sysctl -w net.bridge.bridge-nf-call-ip6tables=0 >/dev/null 2>&1 || true
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
    log_ok "NEXORA lab stopped. FaultLens and other projects unaffected."
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
CMD="${1:-help}"
case "${CMD}" in
    up)       lab_up ;;
    down)     lab_down ;;
    status)   lab_status ;;
    verify)   lab_verify ;;
    logs)     lab_logs "$@" ;;
    restart)  lab_restart ;;
    failover) failover_test ;;
    help|*)
        echo "Usage: $0 {up|down|status|verify|logs [router]|restart|failover}"
        echo ""
        echo "  up        Start the NEXORA five-router OSPF lab"
        echo "  down      Stop and remove NEXORA lab containers only"
        echo "  status    Show container and OSPF neighbor status"
        echo "  verify    Run all connectivity and OSPF verification checks"
        echo "  logs      Show container logs (optional: specify router e.g. r1)"
        echo "  restart   Teardown and restart the lab"
        echo "  failover  Run L12 link-failure smoke test"
        ;;
esac
