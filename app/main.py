from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .agent import Agent, TaskNotFoundError
from .db import init_db
from .tools import list_finance_records

agent = Agent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="CompanyPilot — Autonomous AI Task Worker",
    description="A narrow, auditable autonomous agent prototype for invoice processing.",
    version="0.1.0",
    lifespan=lifespan,
)


class TaskRequest(BaseModel):
    request: str = Field(min_length=8, max_length=2000, examples=["Find the latest invoice from ABC Company, enter it into finance, and confirm when done."])
    require_approval: bool = True


class ApprovalRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=100, examples=["sumit@example.com"])
    note: str | None = Field(default=None, max_length=500)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home() -> str:
    return r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CompanyPilot | Autonomous Task Worker</title>
<style>
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2c;--line:#26344d;--text:#eaf0ff;--muted:#a6b4cc;--accent:#91b8ff;--green:#9de2b2;--red:#ff9b9b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#1b2b4c 0,transparent 38%),var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}.wrap{max-width:1080px;margin:0 auto;padding:32px 18px 60px}.eyebrow{color:var(--accent);font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:12px}.hero{display:flex;gap:20px;justify-content:space-between;align-items:flex-start;margin-bottom:24px}.hero h1{font-size:clamp(30px,5vw,48px);line-height:1.08;margin:8px 0 10px;letter-spacing:-.04em}.hero p{color:var(--muted);max-width:650px;margin:0}.pill{border:1px solid var(--line);padding:7px 10px;border-radius:99px;color:var(--green);white-space:nowrap;font-size:12px}.grid{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}.panel{background:rgba(18,26,44,.92);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 12px 32px #0002}.panel h2{font-size:17px;margin:0 0 14px}.muted{color:var(--muted)}label{display:block;font-size:13px;color:var(--muted);margin-bottom:7px}textarea,input{width:100%;background:#0c1425;border:1px solid var(--line);border-radius:10px;color:var(--text);padding:12px;font:inherit}textarea{min-height:104px;resize:vertical}.check{display:flex;align-items:center;gap:9px;margin:12px 0;color:var(--muted);font-size:13px}.check input{width:auto}button{border:0;border-radius:10px;background:var(--accent);color:#071226;font-weight:750;padding:11px 15px;cursor:pointer}button.secondary{background:#23324c;color:var(--text);border:1px solid var(--line)}button.danger{background:#522e3a;color:#ffdce2}button:disabled{opacity:.5;cursor:not-allowed}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.status{display:inline-block;border-radius:99px;background:#26344d;padding:4px 9px;font-size:12px;font-weight:700}.status.completed{color:var(--green)}.status.failed,.status.rejected{color:var(--red)}.kv{display:grid;grid-template-columns:130px 1fr;gap:7px 12px;font-size:13px}.kv div:nth-child(odd){color:var(--muted)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1220;border:1px solid var(--line);padding:12px;border-radius:10px;font-size:12px;max-height:330px;overflow:auto}.event{padding:9px 0;border-bottom:1px solid #26344d;font-size:12px}.event:last-child{border:0}.event b{color:var(--accent)}.span{grid-column:1/-1}.note{font-size:12px;color:var(--muted);margin-top:14px}.error{color:var(--red);white-space:pre-wrap}.success{color:var(--green)}@media(max-width:760px){.grid{grid-template-columns:1fr}.span{grid-column:auto}.hero{display:block}.pill{display:inline-block;margin-top:14px}.kv{grid-template-columns:110px 1fr}}
</style></head><body><main class="wrap">
<header class="hero"><div><div class="eyebrow">Autonomous AI task worker · local demo</div><h1>From request to<br>verified work.</h1><p>CompanyPilot processes a sample invoice through a real tool loop: search, validate, request approval, write to a simulated finance system, recover from a transient failure, and verify the saved record.</p></div><div class="pill">● Approval-first workflow</div></header>
<div class="grid"><section class="panel"><h2>1. Give the agent a task</h2><label for="request">Natural-language request</label><textarea id="request">Find the latest invoice from ABC Company, enter it into finance, and confirm when done.</textarea><label class="check"><input id="approval" type="checkbox" checked> Require human approval before finance write</label><div class="actions"><button id="run" onclick="createTask()">Run task</button><button class="secondary" onclick="loadRecords()">Refresh finance records</button></div><p class="note">Demo vendors: ABC Company and Northstar Labs. No external accounts are accessed.</p><div id="message" class="note"></div></section>
<section class="panel"><h2>2. Current task</h2><div id="task"><p class="muted">Run a task to inspect its plan, state, and evidence here.</p></div><div id="approvalActions" class="actions" hidden><button onclick="decide(true)">Approve finance write</button><button class="danger" onclick="decide(false)">Reject</button></div></section>
<section class="panel span"><h2>3. Execution audit trail</h2><div id="audit" class="muted">Events will appear here as the task runs.</div></section>
<section class="panel span"><h2>4. Simulated finance records</h2><div id="records" class="muted">No records loaded yet.</div></section></div>
<p class="note">Prototype limitation: invoice source and finance system are local fixtures. The actor field in this demo is not real authentication. Keep the service on localhost.</p></main>
<script>let currentTask=null;const $=id=>document.getElementById(id);function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}async function api(url,opts={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...opts});const d=await r.json();if(!r.ok)throw Error(d.detail||JSON.stringify(d));return d}function showMessage(s,err=false){$('message').className=err?'error':'note';$('message').textContent=s}async function createTask(){const b=$('run');b.disabled=true;showMessage('Agent is executing its plan…');try{currentTask=await api('/tasks',{method:'POST',body:JSON.stringify({request:$('request').value,require_approval:$('approval').checked})});renderTask(currentTask);showMessage('Task created. Inspect the current state and audit events.');await loadRecords()}catch(e){showMessage(e.message,true)}finally{b.disabled=false}}function renderTask(t){currentTask=t;const inv=t.result?.invoice;const evidence=t.result?.evidence;$('task').innerHTML=`<div style="margin-bottom:12px"><span class="status ${esc(t.status)}">${esc(t.status)}</span> <span class="muted">step: ${esc(t.current_step)}</span></div><div class="kv"><div>Task ID</div><div>${esc(t.id)}</div><div>Request</div><div>${esc(t.request)}</div><div>Plan</div><div>${(t.plan||[]).map(p=>esc(p.description)).join('<br>')}</div>${inv?`<div>Invoice</div><div><b>${esc(inv.invoice_number)}</b> · ${esc(inv.company)}</div><div>Amount</div><div>${esc(inv.currency)} ${Number(inv.amount).toLocaleString('en-IN',{minimumFractionDigits:2})}</div><div>Due date</div><div>${esc(inv.due_date)}</div><div>Source</div><div>${esc(inv.file_name)}</div>`:''}${evidence?`<div>Verification</div><div class="success">Passed · finance record #${esc(evidence.finance_record_id)}</div><div>Evidence</div><div>${esc(JSON.stringify(evidence))}</div>`:''}${t.error?`<div>Error</div><div class="error">${esc(t.error)}</div>`:''}</div>`;$('approvalActions').hidden=t.status!=='pending_approval';renderAudit(t.audit_events||[])}function renderAudit(events){$('audit').innerHTML=events.length?events.map(e=>`<div class="event"><b>${esc(e.event_type)}</b> · ${esc(e.created_at)}<br><span class="muted">${esc(JSON.stringify(e.detail||{}))}</span></div>`).join(''):'<span class="muted">No audit events.</span>'}async function decide(approve){if(!currentTask)return;try{const path=`/tasks/${currentTask.id}/${approve?'approve':'reject'}`;currentTask=await api(path,{method:'POST',body:JSON.stringify({actor:'demo-reviewer',note:approve?'Approved in local demo':'Rejected in local demo'})});renderTask(currentTask);showMessage(approve?'Approved. Agent has continued through write and verification.':'Rejected. No finance record was written.');await loadRecords()}catch(e){showMessage(e.message,true)}}async function loadRecords(){try{const rows=await api('/finance/records');$('records').innerHTML=rows.length?`<pre>${esc(JSON.stringify(rows,null,2))}</pre>`:'<span class="muted">No finance records have been written yet.</span>'}catch(e){$('records').textContent=e.message}}loadRecords();</script></body></html>'''


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "companypilot", "version": "0.1.0"}


@app.post("/tasks", status_code=201)
def create_task(body: TaskRequest) -> dict[str, Any]:
    try:
        return agent.create_task(body.request, require_approval=body.require_approval)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Task execution error: {exc}") from exc


@app.get("/tasks")
def list_tasks(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    return agent.list_tasks(limit)


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    try:
        return agent.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@app.post("/tasks/{task_id}/approve")
def approve_task(task_id: str, body: ApprovalRequest) -> dict[str, Any]:
    try:
        return agent.approve_task(task_id, actor=body.actor, note=body.note)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/reject")
def reject_task(task_id: str, body: ApprovalRequest) -> dict[str, Any]:
    try:
        return agent.reject_task(task_id, actor=body.actor, note=body.note)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/finance/records")
def finance_records() -> list[dict[str, Any]]:
    return list_finance_records()


@app.get("/audit/{task_id}")
def audit_for_task(task_id: str) -> list[dict[str, Any]]:
    try:
        return agent.get_task(task_id)["audit_events"]
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
