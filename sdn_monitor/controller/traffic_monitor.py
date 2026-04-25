"""
Traffic Monitor Module
Attaches to the SDN controller and renders live terminal output:
  - Per-flow packet/byte counts
  - Per-switch summaries
  - Periodic report generation
"""

import time
import os
import sys
from datetime import datetime
from typing import List

# Add parent dir so we can import controller
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from controller.sdn_controller import SDNController


# ---------------------------------------------------------------------------
# ANSI colour helpers (works on Linux/macOS terminal)
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
BLUE   = "\033[34m"
WHITE  = "\033[97m"


def clr(text, *codes):
    return "".join(codes) + str(text) + RESET


def fmt_bytes(b: int) -> str:
    if b >= 1e9:  return f"{b/1e9:.2f} GB"
    if b >= 1e6:  return f"{b/1e6:.1f} MB"
    if b >= 1e3:  return f"{b/1e3:.0f} KB"
    return f"{b} B"


def fmt_num(n: int) -> str:
    return f"{n:,}"


def bar(value, maximum, width=20) -> str:
    filled = int(value / max(maximum, 1) * width)
    return clr("█" * filled, GREEN) + clr("░" * (width - filled), DIM)


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------

HEADER = f"""
{clr('╔══════════════════════════════════════════════════════════╗', CYAN)}
{clr('║', CYAN)}   {clr('SDN Traffic Monitor', BOLD, WHITE)}  {clr('OpenFlow 1.3 Controller', DIM)}          {clr('║', CYAN)}
{clr('╚══════════════════════════════════════════════════════════╝', CYAN)}"""


def print_header(ctrl: SDNController):
    snap = ctrl.get_snapshot()
    print(HEADER)
    print(f"  {clr('controller', DIM)}  127.0.0.1:6653   "
          f"{clr('switches', DIM)}  {snap['switches']}   "
          f"{clr('uptime', DIM)}  {int(time.time() - ctrl.start_time)}s   "
          f"{clr('poll #', DIM)}  {snap['poll']}")
    print()


def print_metrics(ctrl: SDNController):
    snap = ctrl.get_snapshot()
    w = 14
    print(clr("  [ aggregate metrics ]", CYAN, BOLD))
    print(f"  {'Active flows':<{w}}  {clr(snap['flows'], GREEN, BOLD)}")
    print(f"  {'Total packets':<{w}}  {clr(fmt_num(snap['total_packets']), WHITE)}")
    print(f"  {'Total bytes':<{w}}  {clr(fmt_bytes(snap['total_bytes']), WHITE)}")
    print(f"  {'Throughput':<{w}}  {clr(str(snap['throughput_mbps']) + ' Mbps', YELLOW, BOLD)}")
    print(f"  {'Dropped pkts':<{w}}  {clr(fmt_num(snap['total_dropped']), RED)}")
    print()


def print_switch_table(ctrl: SDNController):
    snap = ctrl.get_snapshot()
    print(clr("  [ switch topology ]", CYAN, BOLD))
    header = f"  {'Switch':<12} {'DPID':<20} {'Flows':>6} {'RX Pkts':>10} {'RX Bytes':>12} {'Dropped':>8}"
    print(clr(header, DIM))
    print(clr("  " + "─" * 72, DIM))
    for sid, info in snap["per_switch"].items():
        dropped_col = clr(f"{info['dropped']:>8}", RED) if info['dropped'] > 0 else f"{info['dropped']:>8}"
        print(f"  {clr(info['name'], GREEN):<21} "
              f"{clr(info['dpid'], DIM):<20} "
              f"{info['flows']:>6} "
              f"{fmt_num(info['rx_pkts']):>10} "
              f"{fmt_bytes(info['rx_bytes']):>12} "
              f"{dropped_col}")
    print()


def print_flow_table(ctrl: SDNController, limit=12):
    flows = ctrl.get_flow_stats()[:limit]
    if not flows:
        return
    max_bytes = max(f["byte_count"] for f in flows) or 1

    print(clr("  [ flow table — OFPFlowStatsReply ]", CYAN, BOLD))
    hdr = (f"  {'Switch':<11} {'Tbl':>3} {'Match':<40} "
           f"{'Pkts':>9} {'Bytes':>10} {'Pri':>5}  {'Utilization':<22}")
    print(clr(hdr, DIM))
    print(clr("  " + "─" * 106, DIM))

    for f in flows:
        match_str = f["match_str"][:38]
        util = bar(f["byte_count"], max_bytes, 18)
        print(f"  {clr(f['switch_name'], GREEN):<21} "
              f"{f['table_id']:>3}  "
              f"{match_str:<40} "
              f"{fmt_num(f['packet_count']):>9} "
              f"{fmt_bytes(f['byte_count']):>10} "
              f"{f['priority']:>5}  "
              f"{util}")
    print()


def print_report(ctrl: SDNController):
    snap = ctrl.get_snapshot()
    flows = ctrl.get_flow_stats()
    history = ctrl.get_history()

    print(clr("  [ periodic report ]", CYAN, BOLD))
    print(f"  Generated at   {clr(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), WHITE)}")
    print(f"  Poll interval  {clr('5 seconds', WHITE)}")
    print(f"  Total polls    {clr(snap['poll'], WHITE)}")

    if flows:
        top = flows[0]
        print(f"  Top flow       {clr(top['match_str'], YELLOW)}")
        print(f"                 {clr(fmt_bytes(top['byte_count']), WHITE)} "
              f"/ {clr(fmt_num(top['packet_count']) + ' pkts', WHITE)}")

    if len(history) >= 2:
        bps_vals = [h["throughput_mbps"] for h in history]
        print(f"  Peak tput      {clr(str(max(bps_vals)) + ' Mbps', WHITE)}")
        print(f"  Avg tput       {clr(str(round(sum(bps_vals)/len(bps_vals), 2)) + ' Mbps', WHITE)}")

    print()


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def monitor(ctrl: SDNController, refresh: int = 5, show_report: bool = True):
    """
    Live terminal monitor. Refreshes every `refresh` seconds.
    Press Ctrl+C to exit and save a final JSON report.
    """
    print(f"\n{clr('[monitor]', CYAN)} starting — refresh every {refresh}s. Press Ctrl+C to stop.\n")
    time.sleep(1)

    try:
        while True:
            clear_screen()
            print_header(ctrl)
            print_metrics(ctrl)
            print_switch_table(ctrl)
            print_flow_table(ctrl)
            if show_report:
                print_report(ctrl)
            print(clr(f"  refreshing in {refresh}s …", DIM))
            time.sleep(refresh)

    except KeyboardInterrupt:
        print(f"\n\n{clr('[monitor]', CYAN)} stopped. Saving report …")
        save_report(ctrl)


def save_report(ctrl: SDNController):
    """Write a final JSON snapshot to disk."""
    import json
    from pathlib import Path

    out_dir = Path(__file__).parent.parent / "reports"
    out_dir.mkdir(exist_ok=True)
    fname = out_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    report = {
        "generated": datetime.now().isoformat(),
        "snapshot":  ctrl.get_snapshot(),
        "flows":     ctrl.get_flow_stats(),
        "history":   ctrl.get_history(),
    }
    with open(fname, "w") as f:
        json.dump(report, f, indent=2)

    print(f"  Report saved → {clr(fname, GREEN)}\n")
