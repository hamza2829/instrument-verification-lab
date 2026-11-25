"""FastAPI control API + minimal operator web UI for the simulated instrument."""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .instrument import FAULTS, Instrument, InstrumentError


class Sample(BaseModel):
    sample_id: str


class Fault(BaseModel):
    fault: str


def create_app(instrument: Instrument | None = None) -> FastAPI:
    app = FastAPI(title="Simulated Lab Instrument")
    app.state.inst = instrument or Instrument(os.environ.get("IVLAB_BUILD", "series"), int(os.environ.get("IVLAB_SEED", "0")))

    def call(fn, *args):
        try:
            return fn(*args)
        except InstrumentError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    inst = lambda: app.state.inst  # noqa: E731

    @app.get("/api/status")
    def status():
        return inst().status()

    @app.get("/api/sensors")
    def sensors():
        return inst().read_sensors()

    @app.post("/api/samples", status_code=201)
    def load(s: Sample):
        call(inst().load_sample, s.sample_id)
        return inst().status()

    @app.delete("/api/samples/{sample_id}")
    def unload(sample_id: str):
        call(inst().unload_sample, sample_id)
        return inst().status()

    @app.post("/api/runs/start", status_code=201)
    def start():
        return {"run_id": call(inst().start_run)}

    @app.post("/api/runs/stop")
    def stop():
        return {"run_id": call(inst().stop_run)}

    @app.get("/api/runs")
    def runs():
        return inst().runs()

    @app.get("/api/events")
    def events():
        return inst().events()

    @app.post("/api/faults", status_code=201)
    def inject(f: Fault):
        call(inst().inject_fault, f.fault)
        return inst().status()

    @app.delete("/api/faults")
    def clear():
        inst().clear_faults()
        return inst().status()

    @app.post("/api/reset")
    def reset():
        call(inst().reset)
        return inst().status()

    @app.get("/", response_class=HTMLResponse)
    def ui():
        options = "".join(f'<option value="{f}">{f}</option>' for f in FAULTS)
        return UI.replace("{{FAULTS}}", options)

    return app


UI = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Instrument Console</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto}button{margin:.2rem}
#state{font-weight:bold}.ERROR{color:#b00}.RUNNING{color:#070}#msg{color:#b00;min-height:1.2em}</style></head>
<body><h1>Instrument Console</h1>
<p>Build: <span id="build"></span> | State: <span id="state" data-testid="state"></span>
 <span id="error" data-testid="error"></span></p>
<p>Samples: <span id="samples" data-testid="samples"></span></p>
<p><input id="sid" aria-label="Sample ID" placeholder="Sample ID"><button id="load">Load sample</button></p>
<p><button id="start">Start run</button><button id="stop">Stop run</button><button id="read">Read sensors</button>
<button id="reset">Reset</button></p>
<p><select id="fault" aria-label="Fault">{{FAULTS}}</select><button id="inject">Inject fault</button>
<button id="clear">Clear faults</button></p>
<p>Temperature: <span data-testid="temp">-</span> &deg;C</p>
<p id="msg" role="alert" data-testid="msg"></p>
<script>
const $=id=>document.getElementById(id);
async function api(path,method='GET',body){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json'},body:body&&JSON.stringify(body)});
 const d=await r.json();$('msg').textContent=r.ok?'':(d.detail||'error');await refresh();return d;}
async function refresh(){const s=await (await fetch('/api/status')).json();$('build').textContent=s.build;
 $('state').textContent=s.state;$('state').className=s.state;$('error').textContent=s.error?s.error+' '+s.error_text:'';
 $('samples').textContent=s.samples.join(', ')||'none';}
$('load').onclick=()=>api('/samples','POST',{sample_id:$('sid').value});
$('start').onclick=()=>api('/runs/start','POST');$('stop').onclick=()=>api('/runs/stop','POST');
$('reset').onclick=()=>api('/reset','POST');$('clear').onclick=()=>api('/faults','DELETE');
$('inject').onclick=()=>api('/faults','POST',{fault:$('fault').value});
$('read').onclick=async()=>{const d=await api('/sensors');document.querySelector('[data-testid=temp]').textContent=d.temperature_c??'n/a';};
refresh();
</script></body></html>"""

app = create_app()
