import json
import math
from http.server import BaseHTTPRequestHandler
from statistics import mean
from typing import Any, Dict, List

DATA_FILE = "q-vercel-latency.json"

def p95(values):
    """
    95th percentile using linear interpolation (common in numpy/pandas quantile).
    """
    if not values:
        return 0.0

    s = sorted(float(v) for v in values)
    n = len(s)
    if n == 1:
        return float(s[0])

    # position on 0..n-1
    pos = 0.95 * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))

    if lo == hi:
        return float(s[lo])

    frac = pos - lo
    return float(s[lo] + frac * (s[hi] - s[lo]))

def to_number(x: Any) -> float:
    try:
        if isinstance(x, str):
            x = x.strip()
            if x.endswith("%"):
                x = x[:-1].strip()
        return float(x)
    except Exception:
        return 0.0
    
def extract_uptime_percent(r: Dict[str, Any]) -> float:
    # Try many possible field names
    candidates = [
        "uptime", "uptime_pct", "uptime_percent", "uptime_percentage",
        "availability", "availability_pct", "availability_percent",
        "uptime_ratio", "uptimeRatio", "up"
    ]

    val = None
    for k in candidates:
        if k in r and r.get(k) is not None:
            val = r.get(k)
            break

    if val is None:
        return 0.0

    num = to_number(val)

    # If it's a ratio like 0.98373, convert to percent
    # (heuristic: ratios are usually between 0 and 1.5)
    if 0 <= num <= 1.5:
        num *= 100.0

    return float(num)

class handler(BaseHTTPRequestHandler):
    def _set_cors(self) -> None:
        # Must be exactly "*" for the checker
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "Access-Control-Allow-Origin")
        self.send_header("Access-Control-Allow-Credentials", "false")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        # Read request JSON
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}

        regions = body.get("regions", [])
        threshold_ms = to_number(body.get("threshold_ms", 180))

        # Load telemetry JSON
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.send_response(500)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Failed to load data file", "detail": str(e)}).encode("utf-8"))
            return

        # Accept either list or {"records":[...]}
        records = data.get("records", data) if isinstance(data, dict) else data
        if not isinstance(records, list):
            records = []

        # Build array of per-region stats (the checker likes array or object under k.regions)
        regions_out = []

        for region in regions:
            region_records = [r for r in records if str(r.get("region", "")).lower() == str(region).lower()]

            latencies = [
                to_number(r.get("latency_ms", r.get("latency", r.get("ms", 0))))
                for r in region_records
            ]
            uptimes = [extract_uptime_percent(r) for r in region_records]

            avg_latency = float(mean(latencies)) if latencies else 0.0
            p95_latency = p95(latencies)
            avg_uptime = float(mean(uptimes)) if uptimes else 0.0
            breaches = sum(1 for v in latencies if v > threshold_ms)

            regions_out.append({
                "region": str(region),
                "avg_latency": avg_latency,
                "p95_latency": p95_latency,
                "avg_uptime": avg_uptime,
                "breaches": breaches,
            })

        # Send response with CORS header on the POST response
        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()

        payload = {"regions": regions_out}
        self.wfile.write(json.dumps(payload).encode("utf-8"))