from __future__ import annotations
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_HISTORY = 720   # samples kept for the charts (2h at 10s poll interval)
MAX_EVENTS = 50


class DashboardState:
    """Thread-safe snapshot + rolling history consumed by the web dashboard.

    The controller pushes updates into this object on every tick(); the HTTP
    server (running in its own thread) only ever reads a consistent copy via
    snapshot(). No data is invented here - only what the controller actually
    measures (PV surplus, GPU stats, process status, rule state).
    """

    def __init__(self, app_name: str, version: str, dry_run: bool, cfg: dict):
        self.app_name = app_name
        self.version = version
        self.dry_run = dry_run
        self.cfg = cfg
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._history_t = deque(maxlen=MAX_HISTORY)
        self._history_surplus = deque(maxlen=MAX_HISTORY)
        self._history_gpu_power = deque(maxlen=MAX_HISTORY)
        self._history_gpu_temp = deque(maxlen=MAX_HISTORY)
        self._events = deque(maxlen=MAX_EVENTS)
        self._state = {
            "controller_state": "OFF",
            "target_power_w": None,
            "surplus_w": None,
            "gpu": None,
            "nicehash_running": None,
            "errors": 0,
            "system": {"shelly_ok": None, "nvidia_ok": None, "nicehash_ok": None},
        }

    def update(self, **fields):
        with self._lock:
            system = fields.pop("system", None)
            for key, value in fields.items():
                if value is not None:
                    self._state[key] = value
            if system is not None:
                self._state["system"].update(system)

            if "surplus_w" in fields and fields["surplus_w"] is not None:
                gpu = self._state.get("gpu")
                self._history_t.append(time.time())
                self._history_surplus.append(fields["surplus_w"])
                self._history_gpu_power.append(gpu["power_w"] if gpu else None)
                self._history_gpu_temp.append(gpu["temperature_c"] if gpu else None)

    def event(self, message: str):
        with self._lock:
            self._events.appendleft({"ts": time.time(), "msg": message})

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "app": {
                    "name": self.app_name,
                    "version": self.version,
                    "dry_run": self.dry_run,
                    "started_at": self.started_at,
                    "uptime_s": time.time() - self.started_at,
                },
                "cfg": self.cfg,
                "state": dict(self._state),
                "events": list(self._events),
                "history": {
                    "t": list(self._history_t),
                    "surplus_w": list(self._history_surplus),
                    "gpu_power_w": list(self._history_gpu_power),
                    "gpu_temp_c": list(self._history_gpu_temp),
                },
            }


def _make_handler(state: DashboardState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # the controller has its own logger; keep stdout clean

        def _send(self, status: int, content_type: str, body: bytes):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", _HTML.encode("utf-8"))
            elif self.path == "/api/status":
                body = json.dumps(state.snapshot()).encode("utf-8")
                self._send(200, "application/json", body)
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

    return Handler


def start_dashboard_server(state: DashboardState, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="dashboard-http")
    thread.start()
    return server


_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pv-3070-nicehash</title>
<style>
  :root {
    --bg: #03121c; --bg2: #020b12; --panel: #061824; --line: #17425a;
    --text: #d7e7f5; --muted: #8da7bb;
    --green: #43e27b; --blue: #35a9ff; --orange: #ffad42; --red: #ff4d33;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: linear-gradient(var(--bg), var(--bg2));
    color: var(--text); font-family: Arial, Helvetica, sans-serif;
  }
  header {
    display: flex; align-items: center; gap: 24px; padding: 14px 24px;
    background: #041723; border-bottom: 2px solid #0c3850; flex-wrap: wrap;
  }
  header h1 { font-size: 20px; margin: 0; flex: 1; }
  header .muted { color: var(--muted); font-size: 14px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .green { color: var(--green); } .blue { color: var(--blue); }
  .orange { color: var(--orange); } .red { color: var(--red); } .muted { color: var(--muted); }
  .dot.green { background: var(--green); } .dot.red { background: var(--red); } .dot.grey { background: #556; }
  main { padding: 18px; display: grid; gap: 16px; grid-template-columns: repeat(4, minmax(220px, 1fr)); }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
  .panel h2 { margin: 0 0 12px; font-size: 16px; }
  .row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #0e2c3d; font-size: 14px; }
  .row:last-child { border-bottom: none; }
  .row .v { font-weight: 700; }
  .span2 { grid-column: span 2; }
  .span4 { grid-column: span 4; }
  svg.chart { width: 100%; height: 180px; }
  .legend { font-size: 12px; margin-top: 6px; }
  .legend span { margin-right: 16px; }
  ul.events { list-style: none; margin: 0; padding: 0; font-size: 13px; max-height: 220px; overflow-y: auto; }
  ul.events li { padding: 4px 0; border-bottom: 1px solid #0e2c3d; }
  footer { padding: 10px 24px; background: #041723; font-size: 14px; }
  @media (max-width: 900px) {
    main { grid-template-columns: repeat(2, 1fr); }
    .span2, .span4 { grid-column: span 2; }
  }
  @media (max-width: 560px) {
    main { grid-template-columns: 1fr; }
    .span2, .span4 { grid-column: span 1; }
  }
</style>
</head>
<body>
<header>
  <h1>&#127807; pv-3070-nicehash</h1>
  <span class="muted" id="clock">-</span>
  <span class="muted" id="uptime">-</span>
  <span id="online"><span class="dot grey"></span>Verbinde ...</span>
</header>
<main>
  <section class="panel">
    <h2>&#9728; PV-&Uuml;berschuss</h2>
    <div class="row"><span>&Uuml;berschuss</span><span class="v green" id="surplus">-</span></div>
    <div class="row"><span>Reserve</span><span class="v" id="reserve">-</span></div>
    <div class="row"><span>GPU-Ziel (Power Limit)</span><span class="v blue" id="target">-</span></div>
    <div class="row"><span>Steckdose PC (gemessen)</span><span class="v" id="pc-power">-</span></div>
  </section>

  <section class="panel">
    <h2>&#9646; GPU (RTX 3070)</h2>
    <div class="row"><span>Regler-Status</span><span class="v" id="ctrl-state">-</span></div>
    <div class="row"><span>Power Limit / Ist</span><span class="v" id="gpu-power">-</span></div>
    <div class="row"><span>Temperatur</span><span class="v" id="gpu-temp">-</span></div>
    <div class="row"><span>Auslastung</span><span class="v" id="gpu-util">-</span></div>
  </section>

  <section class="panel">
    <h2>&#9679; NiceHash Miner</h2>
    <div class="row"><span>Prozess</span><span class="v" id="nh-status">-</span></div>
    <div class="row"><span>Modus</span><span class="v" id="dry-run">-</span></div>
    <div class="row"><span>Fehlerz&auml;hler</span><span class="v" id="errors">-</span></div>
    <div class="row"><span>Cloud-Status</span><span class="v" id="nh-cloud-status">-</span></div>
    <div class="row"><span>Hashrate</span><span class="v" id="nh-hashrate">-</span></div>
    <div class="row"><span>Profitabilit&auml;t</span><span class="v" id="nh-profit">-</span></div>
    <div class="row"><span>Unbezahlt</span><span class="v" id="nh-unpaid">-</span></div>
  </section>

  <section class="panel">
    <h2>&#9881; Konfiguration</h2>
    <div class="row"><span>Start-Schwelle</span><span class="v" id="cfg-start">-</span></div>
    <div class="row"><span>Stop-Schwelle</span><span class="v" id="cfg-stop">-</span></div>
    <div class="row"><span>GPU-Bereich</span><span class="v" id="cfg-range">-</span></div>
  </section>

  <section class="panel span2">
    <h2>&#9728; PV-&Uuml;berschuss (W)</h2>
    <svg class="chart" id="chart-surplus" viewBox="0 0 400 180" preserveAspectRatio="none"></svg>
    <div class="legend"><span class="green">&#9679; &Uuml;berschuss</span><span class="orange">- - Start</span><span class="red">- - Stop</span></div>
  </section>

  <section class="panel span2">
    <h2>&#9646; GPU-Leistung / Temperatur</h2>
    <svg class="chart" id="chart-gpu" viewBox="0 0 400 180" preserveAspectRatio="none"></svg>
    <div class="legend"><span class="blue">&#9679; Leistung (W)</span><span class="orange">&#9679; Temperatur (&deg;C)</span><span class="red">- - Temp-Grenze</span></div>
  </section>

  <section class="panel span2">
    <h2>&#9881; System-Status</h2>
    <div class="row"><span>Shelly Pro 3EM</span><span class="v" id="sys-shelly">-</span></div>
    <div class="row"><span>NVIDIA (nvidia-smi)</span><span class="v" id="sys-nvidia">-</span></div>
    <div class="row"><span>NiceHash Miner</span><span class="v" id="sys-nicehash">-</span></div>
    <div class="row"><span>Shelly Plug (PC-Steckdose)</span><span class="v" id="sys-pc-power">-</span></div>
  </section>

  <section class="panel span2">
    <h2>&#9201; Letzte Ereignisse</h2>
    <ul class="events" id="events"></ul>
  </section>
</main>
<footer id="footer">Verbinde mit Controller ...</footer>

<script>
function fmtW(v) { return (v === null || v === undefined) ? "-" : Math.round(v) + " W"; }
function fmtC(v) { return (v === null || v === undefined) ? "-" : v.toFixed(1) + " °C"; }
function fmtPct(v) { return (v === null || v === undefined) ? "-" : Math.round(v) + " %"; }
function fmtDur(s) {
  s = Math.floor(s);
  const d = Math.floor(s / 86400); s %= 86400;
  const h = Math.floor(s / 3600); s %= 3600;
  const m = Math.floor(s / 60);
  return (d ? d + "d " : "") + h + "h " + m + "m";
}
function statusBadge(ok) {
  if (ok === null || ok === undefined) return '<span class="dot grey"></span>unbekannt';
  return ok ? '<span class="dot green"></span>OK' : '<span class="dot red"></span>Fehler';
}

function poly(values, w, h, min, max) {
  const clean = values.map(v => (v === null || v === undefined) ? null : v);
  const n = clean.length;
  if (n < 2) return "";
  const span = (max - min) || 1;
  return clean.map((v, i) => {
    if (v === null) return null;
    const x = (i / (n - 1)) * w;
    const y = h - ((v - min) / span) * h;
    return x.toFixed(1) + "," + y.toFixed(1);
  }).filter(p => p !== null).join(" ");
}

function dashedLineAt(value, w, h, min, max, color) {
  const span = (max - min) || 1;
  const y = h - ((value - min) / span) * h;
  return `<line x1="0" y1="${y}" x2="${w}" y2="${y}" stroke="${color}" stroke-width="1.5" stroke-dasharray="6,4"/>`;
}

async function refresh() {
  let data;
  try {
    const res = await fetch("/api/status", { cache: "no-store" });
    data = await res.json();
    document.getElementById("online").innerHTML = '<span class="dot green"></span>Online';
  } catch (e) {
    document.getElementById("online").innerHTML = '<span class="dot red"></span>Keine Verbindung';
    return;
  }

  const app = data.app, st = data.state, cfg = data.cfg, hist = data.history;

  document.getElementById("clock").textContent = new Date().toLocaleString("de-DE");
  document.getElementById("uptime").textContent = "Laufzeit: " + fmtDur(app.uptime_s);
  document.getElementById("footer").textContent =
    (st.controller_state === "MINING")
      ? "Mining läuft – PV-Überschuss wird genutzt"
      : "Regler-Status: " + st.controller_state + (app.dry_run ? " (Testlauf / dry_run)" : "");

  document.getElementById("surplus").textContent = fmtW(st.surplus_w);
  document.getElementById("reserve").textContent = fmtW(cfg.reserve_watts);
  document.getElementById("target").textContent = fmtW(st.target_power_w);
  document.getElementById("pc-power").textContent =
    st.pc_power ? (fmtW(st.pc_power.power_w) + (st.pc_power.on === false ? " (aus)" : "")) : "-";

  document.getElementById("ctrl-state").textContent = st.controller_state;
  document.getElementById("gpu-power").textContent =
    st.gpu ? (Math.round(st.gpu.power_w) + " / " + fmtW(st.target_power_w)) : "-";
  document.getElementById("gpu-temp").textContent = st.gpu ? fmtC(st.gpu.temperature_c) : "-";
  document.getElementById("gpu-util").textContent = st.gpu ? fmtPct(st.gpu.utilization_pct) : "-";

  document.getElementById("nh-status").innerHTML =
    st.nicehash_running === null ? "-" : (st.nicehash_running
      ? '<span class="dot green"></span>läuft'
      : '<span class="dot grey"></span>gestoppt');
  document.getElementById("dry-run").textContent = app.dry_run ? "Testlauf (dry_run)" : "Live";
  document.getElementById("errors").textContent = st.errors;

  const nc = st.nicehash_cloud;
  document.getElementById("nh-cloud-status").textContent = nc
    ? nc.miner_status + (nc.gpu_name ? " (" + nc.gpu_name + ")" : "")
    : "-";
  document.getElementById("nh-hashrate").textContent =
    (nc && nc.speed && nc.speed.value !== null && nc.speed.value !== undefined)
      ? nc.speed.value.toFixed(1) + " " + (nc.speed.algorithm || "")
      : "-";
  document.getElementById("nh-profit").textContent =
    (nc && nc.profitability_btc_day !== null && nc.profitability_btc_day !== undefined)
      ? nc.profitability_btc_day.toFixed(8) + " BTC/Tag" : "-";
  document.getElementById("nh-unpaid").textContent =
    (nc && nc.unpaid_amount_btc !== null && nc.unpaid_amount_btc !== undefined)
      ? nc.unpaid_amount_btc.toFixed(8) + " BTC" : "-";

  document.getElementById("cfg-start").textContent =
    Math.round(cfg.start_threshold_watts) + " W (" + cfg.min_start_seconds + " s)";
  document.getElementById("cfg-stop").textContent =
    Math.round(cfg.stop_threshold_watts) + " W (" + cfg.min_stop_seconds + " s)";
  document.getElementById("cfg-range").textContent =
    cfg.min_power_watts + "–" + cfg.max_power_watts + " W";

  document.getElementById("sys-shelly").innerHTML = statusBadge(st.system.shelly_ok);
  document.getElementById("sys-nvidia").innerHTML = statusBadge(st.system.nvidia_ok);
  document.getElementById("sys-nicehash").innerHTML = statusBadge(st.system.nicehash_ok);
  document.getElementById("sys-pc-power").innerHTML = statusBadge(st.system.pc_power_ok);

  document.getElementById("events").innerHTML = data.events.map(e =>
    "<li><span class=\"muted\">" + new Date(e.ts * 1000).toLocaleTimeString("de-DE") + "</span> " + e.msg + "</li>"
  ).join("") || "<li class=\"muted\">Noch keine Ereignisse</li>";

  // --- surplus chart ---
  const sVals = hist.surplus_w;
  if (sVals.length > 1) {
    const min = Math.min(0, ...sVals, cfg.stop_threshold_watts);
    const max = Math.max(...sVals, cfg.start_threshold_watts) * 1.1 + 1;
    const w = 400, h = 180;
    const svg = document.getElementById("chart-surplus");
    svg.innerHTML =
      dashedLineAt(cfg.start_threshold_watts, w, h, min, max, "#ffad42") +
      dashedLineAt(cfg.stop_threshold_watts, w, h, min, max, "#ff4d33") +
      `<polyline fill="none" stroke="#43e27b" stroke-width="2.5" points="${poly(sVals, w, h, min, max)}"/>`;
  }

  // --- gpu power + temp chart (dual scale, power left 0-250W, temp right 0-100C, both mapped to same box) ---
  const pVals = hist.gpu_power_w, tVals = hist.gpu_temp_c;
  if (pVals.length > 1) {
    const w = 400, h = 180;
    const pMax = Math.max(cfg.max_power_watts, ...pVals.filter(v => v !== null)) * 1.1 + 1;
    const tMax = Math.max(cfg.temperature_critical_c || 90, ...tVals.filter(v => v !== null)) * 1.1;
    const svg = document.getElementById("chart-gpu");
    svg.innerHTML =
      dashedLineAt(cfg.temperature_critical_c, w, h, 0, tMax, "#ff4d33") +
      `<polyline fill="none" stroke="#35a9ff" stroke-width="2.5" points="${poly(pVals, w, h, 0, pMax)}"/>` +
      `<polyline fill="none" stroke="#ffad42" stroke-width="2.5" points="${poly(tVals, w, h, 0, tMax)}"/>`;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
