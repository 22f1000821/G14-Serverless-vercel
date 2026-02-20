import json
import math
from http.server import BaseHTTPRequestHandler
from statistics import mean
from typing import Any, Dict, List

DATA_FILE = "q-vercel-latency.json"

def p95(values: List[float]) -> float:
    """
    Simple 95th percentile:
    - sort
    - take the element at ceil(0.95*n) - 1
    """
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    idx = max(0, min(n - 1, math.ceil(0.95 * n) - 1))
    return float(s[idx])

def to_number(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

class handler(BaseHTTPRequestHandler):
    def _set_cors(self) -> None:
        # CORS: allow ANY origin to call this endpoint
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        # Browser preflight request
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        # Only accept this endpoint as POST
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length).decode("utf-8") if content_length else ""

        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = {}

        regions = body.get("regions", [])
        threshold_ms = to_number(body.get("threshold_ms", 180))

        # Load telemetry data (file is in project root)
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

        # Accept either a list of records, or an object with a "records" list
        records = data.get("records", data) if isinstance(data, dict) else data
        if not isinstance(records, list):
            records = []

        # Compute metrics per region
        result: Dict[str, Dict[str, Any]] = {}

        for region in regions:
            region_records = [r for r in records if str(r.get("region", "")).lower() == str(region).lower()]

            # Try common key names safely
            latencies = [
                to_number(r.get("latency_ms", r.get("latency", r.get("ms", 0))))
                for r in region_records
            ]
            uptimes = [
                to_number(r.get("uptime", r.get("uptime_ratio", r.get("up", 0))))
                for r in region_records
            ]

            avg_latency = float(mean(latencies)) if latencies else 0.0
            p95_latency = p95(latencies)
            avg_uptime = float(mean(uptimes)) if uptimes else 0.0
            breaches = sum(1 for v in latencies if v > threshold_ms)

            result[str(region)] = {
                "avg_latency": avg_latency,
                "p95_latency": p95_latency,
                "avg_uptime": avg_uptime,
                "breaches": breaches,
            }

        # Respond JSON
        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode("utf-8"))