"""
SDN Traffic Monitor Controller
Simulates a Ryu-style OpenFlow 1.3 controller with:
  - Flow table management per switch
  - Periodic OFPFlowStatsRequest polling
  - Packet/byte counter collection
  - Report generation
"""

import time
import random
import threading
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List
from datetime import datetime


# ---------------------------------------------------------------------------
# Data structures (mirror OpenFlow structs)
# ---------------------------------------------------------------------------

@dataclass
class OFPMatch:
    """Simplified OFP match fields."""
    in_port: int = 0
    eth_type: int = 0x0800       # IPv4
    ip_proto: int = 6            # TCP
    ipv4_src: str = "0.0.0.0"
    ipv4_dst: str = "0.0.0.0"
    tcp_dst: int = 0

    def __str__(self):
        proto_map = {6: "TCP", 17: "UDP", 1: "ICMP"}
        proto = proto_map.get(self.ip_proto, str(self.ip_proto))
        port_str = f":{self.tcp_dst}" if self.tcp_dst else ""
        return f"{self.ipv4_src} -> {self.ipv4_dst}{port_str} [{proto}]"


@dataclass
class OFPFlowStats:
    """
    Mirrors ryu.ofproto.ofproto_v1_3_parser.OFPFlowStats
    Fields returned by OFPFlowStatsReply from each switch.
    """
    table_id: int = 0
    priority: int = 100
    match: OFPMatch = field(default_factory=OFPMatch)
    packet_count: int = 0
    byte_count: int = 0
    duration_sec: int = 0
    duration_nsec: int = 0
    idle_timeout: int = 0
    hard_timeout: int = 0
    cookie: int = 0

    def to_dict(self):
        d = asdict(self)
        d["match_str"] = str(self.match)
        return d


@dataclass
class OFPPortStats:
    """Mirrors OFPPortStats — per-port counters."""
    port_no: int = 0
    rx_packets: int = 0
    tx_packets: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0
    rx_errors: int = 0


@dataclass
class Switch:
    """Represents a connected OpenFlow switch (datapath)."""
    dpid: str
    name: str
    address: str
    n_ports: int
    flow_table: List[OFPFlowStats] = field(default_factory=list)
    port_stats: List[OFPPortStats] = field(default_factory=list)
    connected: bool = True
    n_tables: int = 3


# ---------------------------------------------------------------------------
# Topology builder
# ---------------------------------------------------------------------------

def build_topology() -> Dict[str, Switch]:
    """
    Create a simple 3-switch topology:
      core-sw-1  (dpid 1)  — backbone switch
      agg-sw-2   (dpid 2)  — aggregation
      edge-sw-3  (dpid 3)  — edge / access
    """
    protos = [
        (6,  80,  "10.0.0.1", "10.0.0.5"),
        (6,  443, "10.0.0.2", "10.0.1.1"),
        (17, 53,  "10.0.0.3", "8.8.8.8"),
        (17, 5001,"10.0.1.2", "10.0.2.1"),
        (1,  0,   "10.0.0.4", "10.0.0.1"),
        (6,  22,  "10.0.2.5", "10.0.0.9"),
        (6,  8080,"192.168.1.10","10.0.0.1"),
        (6,  3306,"10.0.3.1", "10.0.4.2"),
    ]

    def make_flows(subset, base_pkts=5000, base_bytes=500_000):
        flows = []
        for i, (proto, port, src, dst) in enumerate(subset):
            flows.append(OFPFlowStats(
                table_id=i % 2,
                priority=random.choice([50, 100, 200, 300]),
                match=OFPMatch(
                    in_port=i + 1,
                    ip_proto=proto,
                    ipv4_src=src,
                    ipv4_dst=dst,
                    tcp_dst=port,
                ),
                packet_count=random.randint(base_pkts, base_pkts * 5),
                byte_count=random.randint(base_bytes, base_bytes * 10),
                duration_sec=random.randint(10, 600),
                cookie=0xAB00 + i,
            ))
        return flows

    def make_ports(n):
        return [OFPPortStats(
            port_no=i + 1,
            rx_packets=random.randint(1000, 50000),
            tx_packets=random.randint(1000, 50000),
            rx_bytes=random.randint(100_000, 5_000_000),
            tx_bytes=random.randint(100_000, 5_000_000),
            rx_dropped=random.randint(0, 50),
        ) for i in range(n)]

    switches = {
        "s1": Switch("00:00:00:00:00:01", "core-sw-1",  "10.0.0.254:6653", 4,
                     flow_table=make_flows(protos[:3]),  port_stats=make_ports(4)),
        "s2": Switch("00:00:00:00:00:02", "agg-sw-2",   "10.0.1.254:6653", 6,
                     flow_table=make_flows(protos[2:6]), port_stats=make_ports(6)),
        "s3": Switch("00:00:00:00:00:03", "edge-sw-3",  "10.0.2.254:6653", 8,
                     flow_table=make_flows(protos[5:]),  port_stats=make_ports(8)),
    }
    return switches


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class SDNController:
    """
    Simulates a Ryu OpenFlow controller.

    In a real Ryu app this class would extend RyuApp and handle:
      EventOFPFlowStatsReply  -> _flow_stats_reply_handler
      EventOFPPortStatsReply  -> _port_stats_reply_handler

    Here we simulate those replies with periodic thread-based polling.
    """

    POLL_INTERVAL = 5       # seconds between OFPFlowStatsRequest cycles
    OF_VERSION    = "1.3"
    CONTROLLER_IP = "127.0.0.1"
    CONTROLLER_PORT = 6653

    def __init__(self):
        self.switches: Dict[str, Switch] = build_topology()
        self.poll_count = 0
        self.start_time = time.time()
        self._lock = threading.Lock()
        self._running = False
        self._history: List[dict] = []   # one snapshot per poll cycle

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self._running = True
        t = threading.Thread(target=self._poll_loop, daemon=True)
        t.start()
        print(f"\n[controller] OpenFlow {self.OF_VERSION} controller started")
        print(f"[controller] Listening on {self.CONTROLLER_IP}:{self.CONTROLLER_PORT}")
        print(f"[controller] {len(self.switches)} switches connected\n")

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    # Polling — mimics hub.spawn in Ryu
    # ------------------------------------------------------------------

    def _poll_loop(self):
        while self._running:
            self._send_stats_request()
            time.sleep(self.POLL_INTERVAL)

    def _send_stats_request(self):
        """
        Equivalent to:
            datapath.send_msg(OFPFlowStatsRequest(datapath))
        for each connected switch.
        """
        with self._lock:
            self.poll_count += 1
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] poll #{self.poll_count} — sending OFPFlowStatsRequest to {len(self.switches)} switches")
            for sid, sw in self.switches.items():
                if sw.connected:
                    self._simulate_flow_stats_reply(sw)
                    self._simulate_port_stats_reply(sw)
            snapshot = self._collect_snapshot()
            self._history.append(snapshot)
            self._print_summary(snapshot)

    def _simulate_flow_stats_reply(self, sw: Switch):
        """
        Simulates OFPFlowStatsReply — update counters as if traffic is flowing.
        In a real controller this fires as an event from the switch.
        """
        for fs in sw.flow_table:
            delta_pkts  = random.randint(200, 4000)
            delta_bytes = delta_pkts * random.randint(64, 1500)
            fs.packet_count  += delta_pkts
            fs.byte_count    += delta_bytes
            fs.duration_sec  += self.POLL_INTERVAL

    def _simulate_port_stats_reply(self, sw: Switch):
        for ps in sw.port_stats:
            ps.rx_packets += random.randint(100, 2000)
            ps.tx_packets += random.randint(100, 2000)
            ps.rx_bytes   += random.randint(10_000, 1_500_000)
            ps.tx_bytes   += random.randint(10_000, 1_500_000)
            ps.rx_dropped += random.randint(0, 5)

    # ------------------------------------------------------------------
    # Stats collection
    # ------------------------------------------------------------------

    def _collect_snapshot(self) -> dict:
        all_flows   = [fs for sw in self.switches.values() for fs in sw.flow_table]
        total_pkts  = sum(fs.packet_count for fs in all_flows)
        total_bytes = sum(fs.byte_count   for fs in all_flows)
        total_drop  = sum(ps.rx_dropped
                          for sw in self.switches.values()
                          for ps in sw.port_stats)

        # Approximate throughput (Mbps) from byte delta
        elapsed = max(time.time() - self.start_time, 1)
        mbps = round((total_bytes * 8) / elapsed / 1e6, 2)

        return {
            "timestamp": datetime.now().isoformat(),
            "poll":      self.poll_count,
            "switches":  len(self.switches),
            "flows":     len(all_flows),
            "total_packets": total_pkts,
            "total_bytes":   total_bytes,
            "throughput_mbps": mbps,
            "total_dropped":   total_drop,
            "per_switch": {
                sid: {
                    "name":    sw.name,
                    "dpid":    sw.dpid,
                    "flows":   len(sw.flow_table),
                    "rx_pkts": sum(p.rx_packets for p in sw.port_stats),
                    "rx_bytes":sum(p.rx_bytes   for p in sw.port_stats),
                    "dropped": sum(p.rx_dropped for p in sw.port_stats),
                }
                for sid, sw in self.switches.items()
            },
        }

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _print_summary(self, snap: dict):
        print(f"  flows={snap['flows']}  "
              f"packets={snap['total_packets']:,}  "
              f"bytes={self._fmt_bytes(snap['total_bytes'])}  "
              f"throughput={snap['throughput_mbps']} Mbps  "
              f"dropped={snap['total_dropped']}")

    @staticmethod
    def _fmt_bytes(b: int) -> str:
        if b >= 1e9:  return f"{b/1e9:.2f} GB"
        if b >= 1e6:  return f"{b/1e6:.1f} MB"
        if b >= 1e3:  return f"{b/1e3:.0f} KB"
        return f"{b} B"

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def get_flow_stats(self, switch_id: str = None) -> List[dict]:
        """Return flow stats for one or all switches."""
        with self._lock:
            result = []
            for sid, sw in self.switches.items():
                if switch_id and sid != switch_id:
                    continue
                for fs in sw.flow_table:
                    d = fs.to_dict()
                    d["switch"] = sid
                    d["switch_name"] = sw.name
                    result.append(d)
            return sorted(result, key=lambda x: x["byte_count"], reverse=True)

    def get_port_stats(self, switch_id: str = None) -> List[dict]:
        with self._lock:
            result = []
            for sid, sw in self.switches.items():
                if switch_id and sid != switch_id:
                    continue
                for ps in sw.port_stats:
                    d = asdict(ps)
                    d["switch"] = sid
                    d["switch_name"] = sw.name
                    result.append(d)
            return result

    def get_snapshot(self) -> dict:
        with self._lock:
            return self._collect_snapshot()

    def get_history(self) -> List[dict]:
        with self._lock:
            return list(self._history)
