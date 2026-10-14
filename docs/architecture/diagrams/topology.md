# NEXORA — Five-Node Topology Diagram

**Team**: A3-PS035-TC490 | **PS-035**

```mermaid
graph LR
    subgraph RING["OSPF Area 0 — Five-Node Ring Topology"]
        R1["R1\nGateway\nOSPF-ID: 1.1.1.1\nlo: 192.168.255.1/32"]
        R2["R2\nAggregation-A\nOSPF-ID: 2.2.2.2\nlo: 192.168.255.2/32"]
        R3["R3\nAggregation-B\nOSPF-ID: 3.3.3.3\nlo: 192.168.255.3/32"]
        R4["R4\nEdge Router\nOSPF-ID: 4.4.4.4\nlo: 192.168.255.4/32"]
        R5["R5\nPeer/Transit\nOSPF-ID: 5.5.5.5\nlo: 192.168.255.5/32"]

        R1 -- "L12\n10.0.12.0/30\nR1:eth1↔R2:eth1" --- R2
        R2 -- "L23\n10.0.23.0/30\nR2:eth2↔R3:eth1" --- R3
        R3 -- "L34\n10.0.34.0/30\nR3:eth2↔R4:eth1" --- R4
        R4 -- "L45\n10.0.45.0/30\nR4:eth2↔R5:eth1" --- R5
        R5 -- "L51\n10.0.15.0/30\nR5:eth2↔R1:eth2" --- R1
    end

    subgraph MGMT["Management Network (isolated)"]
        MGMTNET["192.168.100.0/24\nPassive OSPF — NOT in ring"]
    end

    R1 -. "mgmt0\n192.168.100.1" .-> MGMTNET
    R2 -. "mgmt0\n192.168.100.2" .-> MGMTNET
    R3 -. "mgmt0\n192.168.100.3" .-> MGMTNET
    R4 -. "mgmt0\n192.168.100.4" .-> MGMTNET
    R5 -. "mgmt0\n192.168.100.5" .-> MGMTNET

    style MGMTNET fill:#1e1b4b,color:#c7d2fe
    style RING fill:#0f172a,color:#e2e8f0
```

---

## Addressing Summary

| Router | OSPF-ID | Loopback | eth1 | eth2 |
|--------|---------|----------|------|------|
| R1 | 1.1.1.1 | 192.168.255.1/32 | 10.0.12.1/30 (→R2) | 10.0.15.2/30 (→R5) |
| R2 | 2.2.2.2 | 192.168.255.2/32 | 10.0.12.2/30 (→R1) | 10.0.23.1/30 (→R3) |
| R3 | 3.3.3.3 | 192.168.255.3/32 | 10.0.23.2/30 (→R2) | 10.0.34.1/30 (→R4) |
| R4 | 4.4.4.4 | 192.168.255.4/32 | 10.0.34.2/30 (→R3) | 10.0.45.1/30 (→R5) |
| R5 | 5.5.5.5 | 192.168.255.5/32 | 10.0.45.2/30 (→R4) | 10.0.15.1/30 (→R1) |

## Link Subnet Summary

| Link | Subnet | Cost |
|------|--------|------|
| L12 (R1–R2) | 10.0.12.0/30 | 1 |
| L23 (R2–R3) | 10.0.23.0/30 | 1 |
| L34 (R3–R4) | 10.0.34.0/30 | 1 |
| L45 (R4–R5) | 10.0.45.0/30 | 1 |
| L51 (R5–R1) | 10.0.15.0/30 | 1 |
