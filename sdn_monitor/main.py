#!/usr/bin/env python3
"""
SDN Traffic Monitoring and Statistics Collector
================================================
Simulates an OpenFlow 1.3 SDN controller (Ryu-style) with:

  - 3 connected switches (core / aggregation / edge)
  - OFPFlowStatsRequest polling every 5 seconds
  - Live packet/byte counters per flow
  - Per-switch port statistics
  - Periodic terminal report + JSON export

Usage:
    python main.py              # run interactive monitor
    python main.py --once       # print one snapshot and exit
    python main.py --json       # dump current stats as JSON
"""

import sys
import time
import argparse
import json

from controller.sdn_controller import SDNController
from controller.traffic_monitor import (
    monitor, print_header, print_metrics,
    print_switch_table, print_flow_table, print_report, save_report,
    HEADER, clr, CYAN, GREEN, BOLD
)


def parse_args():
    p = argparse.ArgumentParser(description="SDN Traffic Monitor")
    p.add_argument("--once",     action="store_true", help="Print one snapshot and exit")
    p.add_argument("--json",     action="store_true", help="Dump stats as JSON and exit")
    p.add_argument("--refresh",  type=int, default=5,  help="Monitor refresh interval (seconds)")
    p.add_argument("--no-report",action="store_true", help="Hide periodic report section")
    return p.parse_args()


def main():
    args = parse_args()

    ctrl = SDNController()
    ctrl.start()

    # Let the first poll complete
    time.sleep(0.5)

    if args.json:
        snap = ctrl.get_snapshot()
        snap["flows"] = ctrl.get_flow_stats()
        print(json.dumps(snap, indent=2))
        ctrl.stop()
        return

    if args.once:
        # Wait for one full poll cycle
        time.sleep(ctrl.POLL_INTERVAL + 1)
        print(HEADER)
        print()
        print_metrics(ctrl)
        print_switch_table(ctrl)
        print_flow_table(ctrl)
        print_report(ctrl)
        save_report(ctrl)
        ctrl.stop()
        return

    # Default: live monitor
    monitor(ctrl, refresh=args.refresh, show_report=not args.no_report)
    ctrl.stop()


if __name__ == "__main__":
    main()
