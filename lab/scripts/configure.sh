#!/bin/sh
# NEXORA Router Startup Script
# Normalizes interface names so:
#   eth0 -> Management (192.168.100.0/24)
#   eth1 -> Link 1 (Phase 01 data-plane IP)
#   eth2 -> Link 2 (Phase 01 data-plane IP)
#
# Then starts FRR routing daemons via /usr/lib/frr/docker-start.

set -e

echo "[nexora-startup] Starting interface normalization and configuration..."

MGMT_MATCH="${MGMT_MATCH:-192.168.100.}"

# Find interfaces by subnet match
MGMT_DEV=$(ip -o addr | awk "/${MGMT_MATCH}/ {print \$2}" | head -1)
IF1_DEV=$(ip -o addr | awk "/${MATCH1}/ {print \$2}" | head -1)
IF2_DEV=$(ip -o addr | awk "/${MATCH2}/ {print \$2}" | head -1)

echo "[nexora-startup] Detected interfaces:"
echo "  MGMT ($MGMT_MATCH): $MGMT_DEV"
echo "  LINK1 ($MATCH1): $IF1_DEV"
echo "  LINK2 ($MATCH2): $IF2_DEV"

if [ -z "$MGMT_DEV" ] || [ -z "$IF1_DEV" ] || [ -z "$IF2_DEV" ]; then
    echo "[nexora-startup] ERROR: Could not identify all three interfaces!"
    ip -br addr
    exit 1
fi

# Step 1: Rename all three to temporary names to avoid any collisions
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

# Step 3: Add Phase 01 IP addresses
if [ -n "${IP1:-}" ]; then
    PLAN_ADDR1=$(echo "$IP1" | cut -d/ -f1)
    if ! ip addr show eth1 | grep -q "$PLAN_ADDR1"; then
        ip addr add "$IP1" dev eth1
        echo "[nexora-startup] Added $IP1 to eth1"
    fi
fi

if [ -n "${IP2:-}" ]; then
    PLAN_ADDR2=$(echo "$IP2" | cut -d/ -f1)
    if ! ip addr show eth2 | grep -q "$PLAN_ADDR2"; then
        ip addr add "$IP2" dev eth2
        echo "[nexora-startup] Added $IP2 to eth2"
    fi
fi

if [ -n "${LOOPBACK_IP:-}" ]; then
    LOOP_ADDR=$(echo "$LOOPBACK_IP" | cut -d/ -f1)
    if ! ip addr show lo | grep -q "$LOOP_ADDR"; then
        ip addr add "$LOOPBACK_IP" dev lo
        echo "[nexora-startup] Added $LOOPBACK_IP to lo"
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
