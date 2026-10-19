#!/bin/sh
# NEXORA Router Startup Script
# Hardened interface discovery and normalization:
#   eth0 -> Management (192.168.100.0/24)
#   eth1 -> Link 1 (Phase 01 data-plane IP)
#   eth2 -> Link 2 (Phase 01 data-plane IP)
#
# Then starts FRR routing daemons via /usr/lib/frr/docker-start.

set -e

echo "[nexora-startup] Starting interface normalization and configuration..."

MGMT_MATCH="${MGMT_MATCH:-192.168.100.}"

if [ -z "${MATCH1:-}" ] || [ -z "${MATCH2:-}" ]; then
    echo "[nexora-startup] ERROR: Required environment variables MATCH1 and MATCH2 must be set!"
    exit 1
fi

# Step 0: Enumerate non-loopback interfaces and detect unexpected extra interfaces
ALL_IFS=$(ip -o link show | awk -F': ' '{print $2}' | grep -v '^lo' | cut -d'@' -f1 | sort)
IF_COUNT=$(echo "$ALL_IFS" | wc -w | tr -d ' ')

if [ "$IF_COUNT" -ne 3 ]; then
    echo "[nexora-startup] ERROR: Expected exactly 3 non-loopback network interfaces (mgmt, link1, link2), but detected ${IF_COUNT}: ${ALL_IFS}"
    echo "[nexora-startup] Full interface details:"
    ip -br addr
    exit 1
fi

echo "[nexora-startup] Detected ${IF_COUNT} candidate interfaces: ${ALL_IFS}"

# Check if interfaces are already normalized and assigned (e.g. container restart)
ETH0_HAS_MGMT=$(ip -o addr show dev eth0 2>/dev/null | grep -F "$MGMT_MATCH" || true)
ETH1_HAS_L1=$(ip -o addr show dev eth1 2>/dev/null | grep -F "$MATCH1" || true)
ETH2_HAS_L2=$(ip -o addr show dev eth2 2>/dev/null | grep -F "$MATCH2" || true)

if [ -n "$ETH0_HAS_MGMT" ] && [ -n "$ETH1_HAS_L1" ] && [ -n "$ETH2_HAS_L2" ]; then
    echo "[nexora-startup] Interfaces are already normalized (eth0=mgmt, eth1=link1, eth2=link2). Preserving current interface state."
else
    # Find interfaces by subnet match unambiguously
    MGMT_DEVS=$(ip -o addr | awk "/${MGMT_MATCH}/ {print \$2}" | sort -u)
    IF1_DEVS=$(ip -o addr | awk "/${MATCH1}/ {print \$2}" | sort -u)
    IF2_DEVS=$(ip -o addr | awk "/${MATCH2}/ {print \$2}" | sort -u)

    MGMT_MATCH_COUNT=$(echo "$MGMT_DEVS" | wc -w | tr -d ' ')
    IF1_MATCH_COUNT=$(echo "$IF1_DEVS" | wc -w | tr -d ' ')
    IF2_MATCH_COUNT=$(echo "$IF2_DEVS" | wc -w | tr -d ' ')

    if [ "$MGMT_MATCH_COUNT" -ne 1 ]; then
        echo "[nexora-startup] ERROR: Expected exactly 1 interface matching MGMT ($MGMT_MATCH), found ${MGMT_MATCH_COUNT}: '$MGMT_DEVS'"
        ip -br addr
        exit 1
    fi

    if [ "$IF1_MATCH_COUNT" -ne 1 ]; then
        echo "[nexora-startup] ERROR: Expected exactly 1 interface matching LINK1 ($MATCH1), found ${IF1_MATCH_COUNT}: '$IF1_DEVS'"
        ip -br addr
        exit 1
    fi

    if [ "$IF2_MATCH_COUNT" -ne 1 ]; then
        echo "[nexora-startup] ERROR: Expected exactly 1 interface matching LINK2 ($MATCH2), found ${IF2_MATCH_COUNT}: '$IF2_DEVS'"
        ip -br addr
        exit 1
    fi

    MGMT_DEV="$MGMT_DEVS"
    IF1_DEV="$IF1_DEVS"
    IF2_DEV="$IF2_DEVS"

    echo "[nexora-startup] Unambiguously detected interfaces:"
    echo "  MGMT  ($MGMT_MATCH): $MGMT_DEV"
    echo "  LINK1 ($MATCH1):     $IF1_DEV"
    echo "  LINK2 ($MATCH2):     $IF2_DEV"

    # Verify all matched interfaces are pairwise distinct
    if [ "$MGMT_DEV" = "$IF1_DEV" ] || [ "$MGMT_DEV" = "$IF2_DEV" ] || [ "$IF1_DEV" = "$IF2_DEV" ]; then
        echo "[nexora-startup] ERROR: Interface collision detected! (MGMT=$MGMT_DEV, LINK1=$IF1_DEV, LINK2=$IF2_DEV)"
        ip -br addr
        exit 1
    fi

    # Verify no unclassified interfaces exist
    for dev in $ALL_IFS; do
        if [ "$dev" != "$MGMT_DEV" ] && [ "$dev" != "$IF1_DEV" ] && [ "$dev" != "$IF2_DEV" ]; then
            echo "[nexora-startup] ERROR: Unclassified extra interface '$dev' found!"
            ip -br addr
            exit 1
        fi
    done

    # Step 1: Rename all three to temporary names to avoid any naming collisions
    ip link set dev "$MGMT_DEV" down
    ip link set dev "$MGMT_DEV" name _t_mgmt

    ip link set dev "$IF1_DEV" down
    ip link set dev "$IF1_DEV" name _t_if1

    ip link set dev "$IF2_DEV" down
    ip link set dev "$IF2_DEV" name _t_if2

    # Step 2: Rename to standard Phase 01 names and bring UP
    ip link set dev _t_mgmt name eth0
    ip link set dev eth0 up

    ip link set dev _t_if1 name eth1
    ip link set dev eth1 up

    ip link set dev _t_if2 name eth2
    ip link set dev eth2 up
fi

# Step 3: Add Phase 01 IP addresses idempotently
if [ -n "${IP1:-}" ]; then
    PLAN_ADDR1=$(echo "$IP1" | cut -d/ -f1)
    if ! ip addr show eth1 | grep -q "$PLAN_ADDR1"; then
        ip addr add "$IP1" dev eth1
        echo "[nexora-startup] Added $IP1 to eth1"
    else
        echo "[nexora-startup] Address $IP1 already present on eth1"
    fi
fi

if [ -n "${IP2:-}" ]; then
    PLAN_ADDR2=$(echo "$IP2" | cut -d/ -f1)
    if ! ip addr show eth2 | grep -q "$PLAN_ADDR2"; then
        ip addr add "$IP2" dev eth2
        echo "[nexora-startup] Added $IP2 to eth2"
    else
        echo "[nexora-startup] Address $IP2 already present on eth2"
    fi
fi

if [ -n "${LOOPBACK_IP:-}" ]; then
    LOOP_ADDR=$(echo "$LOOPBACK_IP" | cut -d/ -f1)
    if ! ip addr show lo | grep -q "$LOOP_ADDR"; then
        ip addr add "$LOOPBACK_IP" dev lo
        echo "[nexora-startup] Added $LOOPBACK_IP to lo"
    else
        echo "[nexora-startup] Loopback $LOOPBACK_IP already present on lo"
    fi
fi

# Step 4: Ensure forwarding and rp_filter sysctls
sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true
sysctl -w net.ipv4.conf.all.rp_filter=0 2>/dev/null || true
sysctl -w net.ipv4.conf.default.rp_filter=0 2>/dev/null || true
sysctl -w net.ipv4.conf.eth0.rp_filter=0 2>/dev/null || true
sysctl -w net.ipv4.conf.eth1.rp_filter=0 2>/dev/null || true
sysctl -w net.ipv4.conf.eth2.rp_filter=0 2>/dev/null || true

echo "[nexora-startup] Normalized interface configuration:"
ip -br addr

echo "[nexora-startup] Starting FRRouting daemons..."
exec /usr/lib/frr/docker-start

