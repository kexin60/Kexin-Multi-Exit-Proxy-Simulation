"""Quick proxy reachability tester for Clash-style YAML proxy lists.

This tool checks TCP connectability to each proxy 'server:port' entry in a
Clash YAML file. It does NOT verify full protocol (vless/vmess/trojan/ss), but
it filters out nodes whose server/port are closed/unreachable which is a fast
first step when you have hundreds of proxies to triage.

Usage:
  python test_proxies.py --file proxies.yaml --timeout 3 --concurrency 40

Output: prints a table and can write JSON report with --out report.json.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

try:
    import yaml
except Exception:
    print("PyYAML is required. Install with: pip install pyyaml")
    raise


def parse_proxies(yaml_path: str) -> List[Dict[str, Any]]:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    proxies = data.get("proxies") or data.get("Proxy") or []
    if not isinstance(proxies, list):
        return []
    return proxies


def try_connect(host: str, port: int, timeout: float) -> bool:
    """Attempt to connect to host:port using getaddrinfo (supports IPv4/IPv6).

    Returns True on success, False otherwise.
    """
    try:
        for res in socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM):
            af, socktype, proto, canonname, sa = res
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                sock.settimeout(timeout)
                sock.connect(sa)
                sock.close()
                return True
            except Exception:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
                continue
    except Exception:
        return False
    return False


def extract_host_port(proxy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = proxy.get("name") or proxy.get("remarks") or "(unnamed)"
    server = proxy.get("server") or proxy.get("address") or proxy.get("host")
    port = proxy.get("port")
    # Some entries use string ports or missing ports; try to coerce
    if server is None:
        return None
    try:
        port = int(port) if port is not None else None
    except Exception:
        port = None
    return {"name": name, "server": server, "port": port}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Test TCP reachability of proxies in a Clash YAML file")
    p.add_argument("--file", "-f", required=True, help="Path to Clash YAML file containing 'proxies:' list")
    p.add_argument("--timeout", type=float, default=3.0, help="TCP connect timeout in seconds (default 3)")
    p.add_argument("--concurrency", type=int, default=30, help="Number of parallel checks (default 30)")
    p.add_argument("--out", help="Optional JSON output file path to write results")
    args = p.parse_args(argv)

    proxies = parse_proxies(args.file)
    if not proxies:
        print("No proxies found in YAML file (looked for top-level 'proxies').")
        return 2

    candidates: List[Dict[str, Any]] = []
    for pxy in proxies:
        info = extract_host_port(pxy)
        if not info:
            continue
        candidates.append(info)

    results: List[Dict[str, Any]] = []

    print(f"Testing {len(candidates)} proxies with timeout={args.timeout}s and concurrency={args.concurrency}...")

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        futures = {}
        for c in candidates:
            server = c.get("server")
            port = c.get("port")
            if port is None:
                # skip entries without port (can't test TCP connection)
                results.append({"name": c.get("name"), "server": server, "port": None, "ok": False, "reason": "no-port"})
                continue
            fut = ex.submit(try_connect, server, port, args.timeout)
            futures[fut] = c

        for fut in as_completed(futures):
            c = futures[fut]
            ok = False
            try:
                ok = fut.result()
            except Exception as e:
                ok = False
            results.append({"name": c.get("name"), "server": c.get("server"), "port": c.get("port"), "ok": bool(ok)})

    # Sort results: reachable first
    results.sort(key=lambda r: (not r.get("ok", False), r.get("name") or ""))

    # Pretty print
    reachable = sum(1 for r in results if r.get("ok"))
    print(f"Reachable: {reachable} / {len(results)}")
    for r in results:
        status = "OK" if r.get("ok") else "DOWN"
        port = r.get("port")
        port_str = str(port) if port is not None else "-"
        print(f"[{status}] {r.get('name')} -> {r.get('server')}:{port_str}")

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"Wrote JSON report to {args.out}")
        except Exception as e:
            print(f"Failed to write output: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
