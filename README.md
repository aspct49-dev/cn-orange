# SDN Traffic Monitor — Computer Networks Project

Simulates an **OpenFlow 1.3 SDN controller** (Ryu-style architecture) that:
- Maintains a topology of 3 switches (core → aggregation → edge)
- Periodically sends `OFPFlowStatsRequest` to each switch
- Collects packet/byte counters from `OFPFlowStatsReply`
- Displays live terminal statistics and generates JSON reports

---

## Project Structure

```
sdn_monitor/
├── main.py                      ← entry point
├── controller/
│   ├── sdn_controller.py        ← OpenFlow controller + switch/flow data models
│   └── traffic_monitor.py       ← terminal display + report generator
└── reports/                     ← auto-generated JSON reports saved here
```

---

## Requirements

Python 3.8+ — no extra packages needed (pure stdlib).

---

## How to Run

### 1. Live interactive monitor (recommended for demo)
```bash
python main.py
```
Clears the screen every 5 seconds and shows:
- Aggregate metrics (flows, packets, bytes, throughput, drops)
- Per-switch table (DPID, flow count, RX stats)
- Flow table (match fields, packet/byte counts, utilization bars)
- Periodic report summary

Press **Ctrl+C** to stop — a JSON report is saved automatically to `reports/`.

---

### 2. Print one snapshot and exit
```bash
python main.py --once
```
Waits for one full poll cycle (6 seconds), prints everything, saves a report, and exits. Good for a quick demo or screenshot.

---

### 3. Dump raw JSON stats
```bash
python main.py --json
```
Prints the current controller snapshot as JSON. Pipe it to `jq` for pretty output:
```bash
python main.py --json | python -m json.tool
```

---

### 4. Custom refresh rate
```bash
python main.py --refresh 3
```

---

## Architecture — How It Maps to Real Ryu

| This project | Real Ryu / OpenFlow |
|---|---|
| `SDNController` class | `RyuApp` subclass |
| `_send_stats_request()` | `datapath.send_msg(OFPFlowStatsRequest(dp))` |
| `_simulate_flow_stats_reply()` | `@set_ev_cls(EventOFPFlowStatsReply)` handler |
| `OFPFlowStats` dataclass | `ryu.ofproto.ofproto_v1_3_parser.OFPFlowStats` |
| `OFPPortStats` dataclass | `ryu.ofproto.ofproto_v1_3_parser.OFPPortStats` |
| `threading` poll loop | `hub.spawn` green thread in Ryu |
| `Switch.flow_table` | Per-datapath flow entry list |

---

## Sample Output

```
╔══════════════════════════════════════════════════════════╗
║   SDN Traffic Monitor  OpenFlow 1.3 Controller          ║
╚══════════════════════════════════════════════════════════╝

  controller  127.0.0.1:6653   switches  3   uptime  12s   poll #  2

  [ aggregate metrics ]
  Active flows    8
  Total packets   1,204,388
  Total bytes     312.4 MB
  Throughput      187.3 Mbps
  Dropped pkts    42

  [ switch topology ]
  Switch         DPID                  Flows    RX Pkts     RX Bytes  Dropped
  ────────────────────────────────────────────────────────────────────────
  core-sw-1      00:00:00:00:00:01         3    412,300      98.2 MB        8
  agg-sw-2       00:00:00:00:00:02         4    510,044     134.1 MB       22
  edge-sw-3      00:00:00:00:00:03         3    282,044      80.1 MB       12

  [ flow table — OFPFlowStatsReply ]
  ...
```
