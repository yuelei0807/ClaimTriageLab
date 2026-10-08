"""Server-rendered reviewer experience for durable claim workflows."""

# ruff: noqa: E501

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from claimtriagelab.showcase import prepare_showcase_database
from claimtriagelab.tools.registry import ToolError
from claimtriagelab.workflow.service import WorkflowService


@dataclass(frozen=True)
class ReviewerSecurity:
    username: str
    password: str
    csrf_secret: str
    max_request_bytes: int = 16 * 1024
    session_seconds: int = 8 * 60 * 60
    allow_showcase_reset: bool = True


class ReviewWebhookRequest(BaseModel):
    """Validated public API contract for a human review continuation."""

    decision: Literal["approve_referral", "reject_referral", "request_information"]
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=200)
    actor_id: str = Field(default="webhook_reviewer", min_length=3, max_length=100)


def csrf_token(config: ReviewerSecurity, case_id: str) -> str:
    return hmac.new(
        config.csrf_secret.encode(), f"{config.username}:{case_id}".encode(), hashlib.sha256
    ).hexdigest()


def _session_token(config: ReviewerSecurity, expires: int) -> str:
    payload = f"{config.username}:{expires}"
    signature = hmac.new(config.csrf_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def _valid_session(config: ReviewerSecurity, token: str | None) -> bool:
    if not token:
        return False
    try:
        username, expires, signature = base64.urlsafe_b64decode(token.encode()).decode().split(":")
        payload = f"{username}:{expires}"
        expected = hmac.new(
            config.csrf_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return (
            secrets.compare_digest(username, config.username)
            and int(expires) >= int(time.time())
            and secrets.compare_digest(signature, expected)
        )
    except (ValueError, UnicodeDecodeError):
        return False


STYLES = """
:root{--ink:#172033;--muted:#667085;--line:#e4e7ec;--paper:#fff;--bg:#f4f7fb;
--brand:#3157d5;--brand2:#17328f;--warn:#b54708;--warnbg:#fffaeb;--good:#067647;
--goodbg:#ecfdf3;--shadow:0 12px 30px rgba(16,24,40,.08)}*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,
-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--brand);text-decoration:none}
a:hover{text-decoration:underline}.shell{max-width:1180px;margin:auto;padding:0 24px 64px}.topbar{background:#101828;color:white}
.topbar-inner{max-width:1180px;margin:auto;padding:16px 24px;display:flex;align-items:center;gap:20px;position:relative}
.brand{display:flex;gap:11px;align-items:center;color:white;font-weight:760;font-size:18px}.mark{width:32px;height:32px;
border-radius:9px;display:grid;place-items:center;background:linear-gradient(135deg,#88a0ff,#4263eb);font-size:13px}
.topbar-actions{margin-left:auto;display:flex;align-items:center;gap:18px}.site-nav{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.site-nav a,.signout{color:#d0d5dd;padding:7px 9px;border-radius:7px;font-size:13px;font-weight:650;white-space:nowrap}.site-nav a:hover,.signout:hover{color:white;background:#344054;text-decoration:none}.site-nav a.active{color:white;background:#344054}.signout{margin-left:8px;color:white;border:1px solid #475467}.hero{padding:42px 0 25px;display:flex;justify-content:space-between;gap:20px;align-items:end}
.eyebrow{text-transform:uppercase;letter-spacing:.09em;font-size:12px;font-weight:750;color:var(--brand)}h1{font-size:32px;
line-height:1.15;margin:7px 0 8px;letter-spacing:-.025em}h2{font-size:19px;margin:0 0 16px}h3{font-size:15px;margin:0 0 5px}
.subtle,.meta{color:var(--muted)}.meta{font-size:13px}.badge{display:inline-flex;padding:6px 10px;border-radius:999px;
font-size:12px;font-weight:750;text-transform:capitalize}.badge.priority_review{background:var(--warnbg);color:var(--warn)}
.badge.pending_review{background:#eef4ff;color:#3538cd}.badge.complete{background:var(--goodbg);color:var(--good)}
.badge.findings{background:var(--warnbg);color:var(--warn)}
.badge.routine_review{background:#ecfdf3;color:#067647}.badge.insufficient_information{background:#fef3f2;color:#b42318}
.grid{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(300px,.85fr);gap:20px}.card{background:var(--paper);
border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:var(--shadow)}.stack{display:grid;gap:20px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}.stat{background:#f8f9fc;
border:1px solid #eaecf0;border-radius:12px;padding:14px}.stat span{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}
.stat strong{font-size:16px}.signal{padding:14px 0;border-top:1px solid var(--line)}.signal:first-of-type{border-top:0;padding-top:0}
.signal-head{display:flex;justify-content:space-between;gap:12px}.evidence-id{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;
color:#475467;background:#f2f4f7;padding:3px 6px;border-radius:5px}.timeline{display:grid;grid-template-columns:repeat(5,1fr);gap:7px}
.step{font-size:11px;text-align:center;color:var(--muted);position:relative;padding-top:18px}.step:before{content:"";position:absolute;
top:3px;left:calc(50% - 6px);width:12px;height:12px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 4px #eef4ff}
.step.active:before{background:#f79009;box-shadow:0 0 0 4px #fef0c7}
.decision-grid{display:grid;gap:9px}.decision{display:block;border:1px solid var(--line);border-radius:11px;padding:12px;cursor:pointer}
.decision:has(input:checked){border-color:var(--brand);background:#f5f7ff;box-shadow:0 0 0 2px #dbe4ff}.decision input{margin-right:8px;accent-color:var(--brand)}
textarea{width:100%;min-height:105px;resize:vertical;border:1px solid #d0d5dd;border-radius:10px;padding:11px;font:inherit;margin-top:7px}
textarea:focus,input:focus{outline:3px solid #dbe4ff;border-color:var(--brand)}.button{display:inline-flex;justify-content:center;
align-items:center;border:0;border-radius:10px;padding:11px 16px;font-weight:720;cursor:pointer}.button.primary{background:var(--brand);
color:white;width:100%;margin-top:12px}.button.primary:hover{background:var(--brand2)}
.button.secondary{background:white;color:var(--brand);border:1px solid #a4b4ff}.button.secondary:hover{background:#f5f7ff}
.notice{border-left:4px solid #f79009;background:var(--warnbg);padding:12px 14px;border-radius:8px;color:#7a2e0e;font-size:13px}.case-list{display:grid;gap:12px}
.case-row{display:grid;grid-template-columns:1fr auto auto;gap:20px;align-items:center;padding:16px;border:1px solid var(--line);
border-radius:12px}.case-row:hover{border-color:#a4b4ff;background:#fafbff}.login-wrap{min-height:100vh;display:grid;place-items:center;
padding:24px;background:radial-gradient(circle at top,#e9efff,#f7f8fb 55%)}.login{width:min(420px,100%)}.login input{width:100%;
padding:11px;border:1px solid #d0d5dd;border-radius:9px;margin:6px 0 15px}.footer-note{margin-top:22px;text-align:center;color:var(--muted);font-size:12px}
.table{width:100%;border-collapse:collapse}.table td{padding:10px 0;border-top:1px solid var(--line);vertical-align:top}.table td:first-child{color:var(--muted);width:42%}
.tabs{display:flex;gap:6px;border-bottom:1px solid var(--line);margin-bottom:20px}.tab{padding:10px 14px;color:var(--muted);font-weight:700;border-bottom:3px solid transparent}.tab.active{color:var(--brand);border-color:var(--brand)}
.run-card{border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:12px}.run-head{display:flex;justify-content:space-between;gap:12px}.code{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8f9fc;border:1px solid #eaecf0;border-radius:8px;padding:10px;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}.eval-pass{color:var(--good)}.eval-warning{color:var(--warn)}.eval-fail{color:#b42318}.id{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted)}
.graph-toolbar{display:flex;justify-content:space-between;align-items:end;gap:16px;flex-wrap:wrap}.graph-toolbar select{min-width:320px;padding:10px;border:1px solid #d0d5dd;border-radius:9px;background:white}.graph-flow{display:flex;align-items:flex-start;gap:34px;overflow-x:auto;padding:22px 4px 18px}.graph-node{position:relative;flex:0 0 235px}.graph-node:not(:first-child):before{content:"→";position:absolute;left:-27px;top:23px;color:#98a2b3;font-size:22px;font-weight:800}.graph-node summary{list-style:none;cursor:pointer;border:2px solid #a4b4ff;border-radius:13px;background:#f5f7ff;padding:14px;min-height:74px}.graph-node summary::-webkit-details-marker{display:none}.graph-node summary:hover{border-color:var(--brand);box-shadow:0 6px 16px rgba(49,87,213,.12)}.graph-node[open] summary{background:#eef4ff;border-color:var(--brand)}.graph-node.human summary{border-color:#f79009;background:#fffaeb}.graph-node.failed summary{border-color:#f04438;background:#fef3f2}.node-kind{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:4px}.node-panel{margin-top:10px;border:1px solid var(--line);border-radius:10px;background:white;padding:12px;box-shadow:var(--shadow)}.thread-lane{border-left:4px solid #dbe4ff;padding:4px 0 18px 18px;margin-top:18px}.thread-lane+.thread-lane:before{content:"↓ next trace";display:block;color:var(--muted);font-size:11px;font-weight:700;margin:-15px 0 12px}.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;background:#a4b4ff}.legend .human-key{background:#f79009}.legend .failed-key{background:#f04438}
@media(max-width:800px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}.hero{align-items:start;flex-direction:column}.case-row{grid-template-columns:1fr}.topbar-inner{align-items:flex-start;gap:12px;flex-direction:column;padding-right:100px}.topbar-actions{margin-left:0;width:calc(100vw - 48px);display:block}.site-nav{width:100%;overflow-x:auto;flex-wrap:nowrap}.signout{position:absolute;right:24px;top:15px;margin:0}}
@media(max-width:480px){.shell{padding:0 14px 40px}.stats{grid-template-columns:1fr}.timeline{grid-template-columns:1fr}.step{text-align:left;padding:4px 0 4px 25px}.step:before{left:2px;top:8px}}
"""


def _layout(
    title: str,
    body: str,
    *,
    signed_in: bool = True,
    case_id: str | None = None,
    active_page: str = "dashboard",
) -> str:
    topbar = ""
    if signed_in:
        destinations = [("dashboard", "Dashboard", "/")]
        if case_id:
            safe_case = escape(case_id)
            destinations.extend(
                [
                    ("case", "Case", f"/cases/{safe_case}"),
                    ("activity", "Activity", f"/cases/{safe_case}/activity?tab=run"),
                    ("graph", "Node graph", f"/cases/{safe_case}/graph"),
                ]
            )
        navigation = "".join(
            f'<a class="{"active" if key == active_page else ""}" href="{url}">{label}</a>'
            for key, label, url in destinations
        )
        topbar = """<header class="topbar"><div class="topbar-inner">
        <a class="brand" href="/"><span class="mark">CT</span>ClaimTriageLab</a>""" + (
            f'<div class="topbar-actions"><nav class="site-nav" aria-label="Primary navigation">{navigation}</nav>'
            '<a class="signout" href="/logout">Sign out</a></div></div></header>'
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
    <style>{STYLES}</style></head><body>{topbar}{body}</body></html>"""


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _pretty(value: object) -> str:
    return escape(json.dumps(value, indent=2, sort_keys=True, default=str))


def _graph_node(run: dict[str, object], evaluations: list[dict[str, object]]) -> str:
    """Render one accessible, expandable execution node."""
    run_type = str(run["run_type"])
    status = str(run["status"])
    classes = "graph-node"
    if run_type == "human_input":
        classes += " human"
    if status != "success":
        classes += " failed"
    findings = "".join(
        f'<li class="eval-{escape(str(item["severity"]))}">{escape(str(item["message"]))}</li>'
        for item in evaluations
    )
    return f"""<details class="{classes}"><summary><span class="node-kind">{escape(run_type)}</span>
    <strong>{_humanize(str(run["step_name"]))}</strong><div class="id">{escape(str(run["run_id"]))}</div></summary>
    <div class="node-panel"><div class="meta">Status: {_humanize(status)} · {float(run["duration_ms"]):.3f} ms</div>
    <h3 style="margin-top:12px">Prior context</h3><div class="code">{_pretty(run["prior_context"])}</div>
    <h3 style="margin-top:12px">Decision</h3><div class="code">{_pretty(run["decision"])}</div>
    <h3 style="margin-top:12px">Tool execution</h3><div class="code">{_pretty({"tool": run["tool_name"], "arguments": run["tool_arguments"], "result": run["tool_result"]})}</div>
    <h3 style="margin-top:12px">Evaluation</h3><ul>{findings or "<li>No evaluation attached.</li>"}</ul></div></details>"""


def _human_checkpoint(trace: dict[str, object]) -> str:
    if trace["task_type"] != "initial_triage":
        return ""
    return f"""<details class="graph-node human"><summary><span class="node-kind">human interrupt</span>
    <strong>Human Review Checkpoint</strong><div class="id">{escape(str(trace["trace_id"]))}</div></summary>
    <div class="node-panel"><p>The workflow pauses here until an authorized reviewer submits a decision.</p>
    <div class="code">{_pretty({"status": trace["status"], "allowed_decisions": ["approve_referral", "reject_referral", "request_information"]})}</div></div></details>"""


def _audit_status(service: WorkflowService) -> tuple[str, str]:
    try:
        service.store.verify_audit_integrity()
        return "Verified", "var(--good)"
    except ValueError:
        return "Integrity failure", "var(--danger)"


def _decision_form(config: ReviewerSecurity, case_id: str, *, follow_up: bool = False) -> str:
    heading = "Record another review" if follow_up else "Record reviewer decision"
    return f"""<form method="post" action="/cases/{escape(case_id)}/review" style="margin-top:18px">
    <input type="hidden" name="csrf" value="{csrf_token(config, case_id)}">
    <input type="hidden" name="idempotency_key" value="review-{uuid4().hex}">
    <div class="decision-grid">
    <label class="decision"><input type="radio" name="decision" value="approve_referral" required><strong>Approve referral</strong><div class="meta">Send for additional investigation.</div></label>
    <label class="decision"><input type="radio" name="decision" value="request_information"><strong>Request information</strong><div class="meta">Obtain documents or clarification first.</div></label>
    <label class="decision"><input type="radio" name="decision" value="reject_referral"><strong>Reject referral</strong><div class="meta">Keep out of the investigation queue.</div></label></div>
    <label style="display:block;margin-top:16px"><strong>Decision rationale</strong><div class="meta">Describe the evidence and next step. For Request information, name the exact document, fact, or clarification needed. This becomes part of the audit record.</div>
    <textarea name="reason" required maxlength="2000" placeholder="Example: Obtain the missing police report and verify the repair estimate."></textarea></label>
    <button class="button primary" type="submit">{heading}</button></form>"""


SIGNAL_COPY = {
    "high_claim_amount": "Claim amount meets the configured high-value review threshold.",
    "multiple_previous_claims": "Claim history contains three or more previous claims.",
    "reporting_delay": "The claim was reported more than five days after the incident.",
    "severe_without_report": "A major or total-loss incident has no police report listed.",
    "high_coverage_ratio": "The requested amount is at least 80% of policy coverage.",
    "inactive_policy": "The policy was not recorded as active at incident time.",
}


def create_app(database_path: Path, security_config: ReviewerSecurity) -> FastAPI:
    runtime = {"service": WorkflowService(database_path)}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        runtime["service"].close()

    app = FastAPI(title="ClaimTriageLab reviewer", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.workflow_service = runtime["service"]

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            length = request.headers.get("content-length")
            if length and int(length) > security_config.max_request_bytes:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
            if len(await request.body()) > security_config.max_request_bytes:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
        return await call_next(request)

    def authorized(request: Request) -> str:
        if not _valid_session(security_config, request.cookies.get("ctl_session")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sign in required")
        return security_config.username

    @app.exception_handler(HTTPException)
    async def browser_auth_error(request: Request, error: HTTPException):
        accepts_html = "text/html" in request.headers.get("accept", "")
        if error.status_code == 401 and accepts_html and request.url.path != "/login":
            path_with_query = request.url.path
            if request.url.query:
                path_with_query = f"{path_with_query}?{request.url.query}"
            destination = quote(path_with_query, safe="")
            return RedirectResponse(f"/login?return_to={destination}", status_code=303)
        if error.status_code in {409, 503} and accepts_html:
            case_path = request.url.path.removesuffix("/review")
            body = f"""<main class="shell"><section class="hero"><div>
            <div class="eyebrow">Execution interrupted</div><h1>The agent could not finish this run</h1>
            <p class="subtle">The failed attempt was recorded. Return to the case and submit the
            review again; provider formatting and rate-limit failures are retried automatically.</p>
            <a class="button secondary" href="{escape(case_path)}">Return to case</a>
            </div></section></main>"""
            return HTMLResponse(_layout("Agent execution interrupted", body), error.status_code)
        return JSONResponse({"detail": error.detail}, status_code=error.status_code)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(return_to: str = "/") -> str:
        safe_return = (
            return_to if return_to.startswith("/") and not return_to.startswith("//") else "/"
        )
        body = f"""<div class="login-wrap"><main class="card login">
        <div class="brand" style="color:var(--ink)"><span class="mark">CT</span>ClaimTriageLab</div>
        <div style="margin:30px 0 22px"><div class="eyebrow">Reviewer workspace</div>
        <h1>Welcome back</h1><p class="subtle">Sign in to review synthetic claim referrals.</p></div>
        <form method="post" action="/login"><input type="hidden" name="csrf" value="{csrf_token(security_config, "login")}">
        <input type="hidden" name="return_to" value="{escape(safe_return)}">
        <label>Reviewer ID<input name="username" autocomplete="username" required></label>
        <label>Password<input type="password" name="password" autocomplete="current-password" required></label>
        <button class="button primary" type="submit">Sign in securely</button></form>
        <p class="footer-note">Local research demo · Synthetic data only</p></main></div>"""
        return _layout("Reviewer sign in", body, signed_in=False)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/login")
    def login(
        username: str = Form(),  # noqa: B008
        password: str = Form(),  # noqa: B008
        csrf: str = Form(),  # noqa: B008
        return_to: str = Form("/"),  # noqa: B008
    ):
        valid = secrets.compare_digest(
            username, security_config.username
        ) and secrets.compare_digest(password, security_config.password)
        if not valid or not secrets.compare_digest(csrf, csrf_token(security_config, "login")):
            raise HTTPException(status_code=401, detail="invalid credentials")
        destination = (
            return_to if return_to.startswith("/") and not return_to.startswith("//") else "/"
        )
        response = RedirectResponse(destination, status_code=303)
        response.set_cookie(
            "ctl_session",
            _session_token(security_config, int(time.time()) + security_config.session_seconds),
            httponly=True,
            samesite="strict",
            max_age=security_config.session_seconds,
        )
        return response

    @app.get("/logout")
    def logout() -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie("ctl_session")
        return response

    @app.get("/", response_class=HTMLResponse)
    def dashboard(_: str = Depends(authorized)) -> str:  # noqa: B008
        service = runtime["service"]
        cases = []
        for claim in service.store.list_claims():
            try:
                cases.append((claim, service.status(claim["claim_id"])))
            except ToolError:
                continue
        category_order = {
            "priority_review": 0,
            "insufficient_information": 1,
            "routine_review": 2,
        }
        cases.sort(
            key=lambda item: (
                item[1]["stage"] == "complete",
                category_order.get(item[1]["triage"]["category"], 9),
                item[0]["claim_id"],
            )
        )
        pending = sum(workflow["stage"] == "pending_review" for _, workflow in cases)
        complete = sum(workflow["stage"] == "complete" for _, workflow in cases)
        audit_label, audit_color = _audit_status(service)
        agent_banner = ""
        if service.agent is None:
            agent_banner = f"""<div class="notice" style="margin-bottom:20px"><strong>Model agent offline.</strong>
            New reviewer decisions are disabled until Groq or Gemini is configured. Existing
            completed continuations may be legacy deterministic demo records.<br>
            <span class="id">{escape(service.agent_configuration_error or "provider unavailable")}</span></div>"""
        rows = (
            "".join(
                f"""<a class="case-row" href="/cases/{escape(claim["claim_id"])}">
            <div><strong>{escape(claim.get("display_name", claim["claim_id"]))}</strong><div class="meta">{escape(claim["claim_id"])} · Policy {escape(claim.get("policy_id", "—"))}</div></div>
            <span class="badge {workflow["triage"]["category"]}">{_humanize(workflow["triage"]["category"])}</span>
            <span class="badge {workflow["stage"]}">{_humanize(workflow["stage"])}</span></a>"""
                for claim, workflow in cases
            )
            or '<div class="footer-note">No workflow cases are available.</div>'
        )
        reset_form = ""
        if security_config.allow_showcase_reset:
            reset_form = f"""<form method="post" action="/showcase/reset" onsubmit="return confirm('Reset all four demo cases and discard demo decisions?')">
            <input type="hidden" name="csrf" value="{csrf_token(security_config, "showcase-reset")}">
            <button class="button secondary" type="submit">Reset demo cases</button></form>"""
        body = f"""<main class="shell"><section class="hero"><div><div class="eyebrow">Reviewer dashboard</div>
        <h1>Claim review queue</h1><p class="subtle">Prioritized synthetic cases awaiting a human decision.</p></div>
        <div style="display:flex;gap:10px;align-items:center">{reset_form}</div></section><section class="stats">
        <div class="stat"><span>Total cases</span><strong>{len(cases)}</strong></div>
        <div class="stat"><span>Pending review</span><strong>{pending}</strong></div>
        <div class="stat"><span>Completed</span><strong>{complete}</strong></div>
        <div class="stat"><span>Audit integrity</span><strong style="color:{audit_color}">{audit_label}</strong></div></section>
        {agent_banner}<section class="card"><h2>Review queue</h2><div class="case-list">{rows}</div></section>
        <p class="footer-note">Recommendations support prioritization only. Human reviewers retain decision authority.</p></main>"""
        return _layout("Review queue", body)

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    def case_page(case_id: str, _: str = Depends(authorized)) -> str:  # noqa: B008
        service = runtime["service"]
        try:
            state = service.status(case_id)
        except ToolError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        claim = service.store.get_record("claims", "claim_id", case_id) or {}
        evidence = service.store.evidence_records(case_id)
        triage = state.get("triage", {})
        audit_label, audit_color = _audit_status(service)
        reviews = service.store.reviews_for_case(case_id)
        signal_html = (
            "".join(
                f"""<div class="signal"><div class="signal-head"><div><h3>{
                    _humanize(item["indicator_id"])
                }</h3>
            <div class="meta">{
                    escape(SIGNAL_COPY.get(item["indicator_id"], item["derivation"]))
                }</div></div>
            <span class="badge priority_review">Review signal</span></div><div style="margin-top:9px">{
                    " ".join(
                        f'<a class="evidence-id" href="#{escape(ev)}">{escape(ev)}</a>'
                        for ev in item["evidence_ids"]
                    )
                }</div></div>"""
                for item in triage.get("indicators", [])
            )
            or '<p class="subtle">No elevated rule signals were identified.</p>'
        )
        stats = (
            ("Claim amount", f"${float(claim.get('claim_amount', 0)):,.0f}"),
            ("Coverage", f"${float(claim.get('coverage_amount', 0)):,.0f}"),
            ("Severity", _humanize(str(claim.get("accident_severity", "Unknown")))),
            ("Reported", str(claim.get("claim_date", "—"))),
        )
        stats_html = "".join(
            f'<div class="stat"><span>{label}</span><strong>{escape(value)}</strong></div>'
            for label, value in stats
        )
        evidence_html = "".join(
            f'<tr id="{escape(str(item.get("evidence_id", "")))}"><td>{_humanize(str(item.get("field_name", "Evidence")))}</td><td>{escape(str(item.get("value", "—")))}</td></tr>'
            for item in evidence
        )
        steps = "".join(
            f'<div class="step {"active" if label == "Human review" and state["stage"] == "pending_review" else ""}">{label}</div>'
            for label in ("Intake", "Evidence", "Triage", "Brief", "Human review")
        )
        if state["stage"] == "pending_review":
            if service.agent is None and os.getenv("CLAIMTRIAGE_TEST_MODE") != "1":
                review_panel = f"""<div class="notice"><strong>Real LLM configuration required.</strong><br>
                Review submission is disabled because the agent cannot continue without genuine
                model inference. Configure Groq or Gemini credentials in the environment.<br>
                <span class="id">{escape(service.agent_configuration_error or "provider unavailable")}</span></div>"""
            else:
                review_panel = f"""<div class="notice"><strong>Human decision required.</strong><br>
                Signals prioritize review and do not establish fraud or justify an automatic claim action.</div>{_decision_form(security_config, case_id)}"""
        elif state["stage"] == "post_review":
            interrupted_review = state.get("review", {})
            review_panel = f"""<div class="notice"><strong>Review saved; agent continuation interrupted.</strong><br>
            The human decision is preserved. Retry resumes the existing decision and records a new
            trace without creating another review.</div>
            <form method="post" action="/cases/{escape(case_id)}/review">
            <input type="hidden" name="decision" value="{escape(str(interrupted_review.get("decision", "request_information")))}">
            <input type="hidden" name="reason" value="{escape(str(interrupted_review.get("reason", "Retry saved review")))}">
            <input type="hidden" name="idempotency_key" value="retry-{uuid4().hex}">
            <input type="hidden" name="csrf" value="{csrf_token(security_config, case_id)}">
            <button class="button primary" type="submit">Retry agent continuation</button></form>"""
        else:
            review = reviews[-1] if reviews else state.get("review", {})
            history = "".join(
                f'<tr><td>{index}</td><td>{_humanize(str(item["decision"]))}<br><span class="meta">{escape(item["reason"])}</span></td><td>{escape(item["reviewer_id"])}</td></tr>'
                for index, item in enumerate(reviews, start=1)
            )
            review_panel = f"""<div class="notice" style="border-color:var(--good);background:var(--goodbg);color:var(--good)">
            <strong>Latest review</strong><br>{_humanize(str(review.get("decision", "complete")))}</div>
            <table class="table" style="margin-top:12px"><tr><td>Reviewer</td><td>{escape(str(review.get("reviewer_id", "—")))}</td></tr>
            <tr><td>Reason</td><td>{escape(str(review.get("reason", "—")))}</td></tr><tr><td>Recorded</td><td>{escape(str(review.get("created_at", "—")))}</td></tr></table>
            <h3 style="margin-top:20px">Review history</h3><table class="table"><tr><td>#</td><td>Decision</td><td>Reviewer</td></tr>{history}</table>
            <details style="margin-top:18px"><summary style="cursor:pointer;font-weight:700;color:var(--brand)">Add a follow-up review</summary>
            <p class="meta">The earlier decision remains in the audit history.</p>{_decision_form(security_config, case_id, follow_up=True)}</details>"""
        followup = state.get("agent_followup", {})
        followup_panel = ""
        if followup:
            checklist = "".join(
                f"<li>{escape(str(item))}</li>" for item in followup.get("collection_checklist", [])
            )
            origin = (
                "Model-generated agent continuation"
                if followup.get("provider") and followup.get("model")
                else "Legacy deterministic demo continuation"
            )
            provider = ""
            if followup.get("provider"):
                provider = f'<div class="meta">{escape(str(followup["provider"]))} · {escape(str(followup["model"]))}</div>'
            followup_panel = f"""<section class="card"><div class="eyebrow">{origin}</div>
            <h2 style="margin-top:6px">{_humanize(str(followup.get("action", "follow_up")))}</h2>
            {provider}<p>{escape(str(followup.get("summary", "")))}</p>
            {f"<ul>{checklist}</ul>" if checklist else ""}
            <a class="button secondary" href="/cases/{escape(case_id)}/activity?tab=run">Inspect agent activity</a></section>"""
        body = f"""<main class="shell"><section class="hero"><div><a href="/">← Review queue</a><div class="eyebrow" style="margin-top:18px">Synthetic claim</div>
        <h1>{escape(str(claim.get("display_name", case_id)))}</h1><p class="subtle">{escape(case_id)} · Policy {escape(str(claim.get("policy_id", "—")))} · Decision model {escape(str(triage.get("model_version", "—")))}</p></div>
        <div><span class="badge {triage.get("category", "")}">{_humanize(str(triage.get("category", "Unknown")))}</span> <span class="badge {state["stage"]}">{_humanize(state["stage"])}</span></div></section>
        <section class="stats">{stats_html}</section><div class="grid"><div class="stack"><section class="card"><h2>Why this case was prioritized</h2>{signal_html}</section>
        <section class="card"><h2>Source evidence</h2><table class="table">{evidence_html}</table></section>{followup_panel}</div><aside class="stack">
        <section class="card"><h2>Workflow</h2><div class="timeline">{steps}</div></section><section class="card"><h2>Reviewer action</h2>{review_panel}</section>
        <section class="card"><h2>Governance</h2><table class="table"><tr><td>Audit chain</td><td style="color:{audit_color}">{audit_label}</td></tr>
        <tr><td>Threshold</td><td>{escape(str(triage.get("threshold_version", "—")))}</td></tr><tr><td>Evidence cited</td><td>{len(triage.get("evidence_ids", []))}</td></tr></table></section></aside></div></main>"""
        return _layout(f"Case {case_id}", body, case_id=case_id, active_page="case")

    @app.get("/cases/{case_id}/activity", response_class=HTMLResponse)
    def activity_page(
        case_id: str,
        tab: str = "run",
        _: str = Depends(authorized),  # noqa: B008
    ) -> str:
        if tab not in {"run", "trace", "thread"}:
            raise HTTPException(status_code=400, detail="unknown activity tab")
        service = runtime["service"]
        try:
            service.status(case_id)
        except ToolError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        thread_id = service.thread_id(case_id)
        thread = service.trajectories.get_thread(thread_id)
        traces = service.trajectories.traces_for_thread(thread_id)
        tabs = "".join(
            f'<a class="tab {"active" if name == tab else ""}" href="/cases/{escape(case_id)}/activity?tab={name}">{name.title()}</a>'
            for name in ("run", "trace", "thread")
        )
        if tab == "run":
            run_cards = []
            for trace in reversed(traces):
                evaluations = service.trajectories.evaluations_for_trace(trace["trace_id"])
                has_findings = any(item["severity"] == "fail" for item in evaluations)
                trace_badge_class = "findings" if has_findings else trace["status"]
                trace_status_label = (
                    "Complete with findings" if has_findings else _humanize(trace["status"])
                )
                evaluation_html = "".join(
                    f'<li class="eval-{item["severity"]}"><strong>{escape(item["severity"].upper())}</strong> · {escape(item["message"])}</li>'
                    for item in evaluations
                )
                run_cards.append(f"""<article class="run-card"><div class="run-head"><div>
                <strong>{_humanize(trace["task_type"])} trace checks</strong>
                <div class="id">{escape(trace["trace_id"])}</div></div>
                <span class="badge {trace_badge_class}">{trace_status_label}</span></div>
                <ul>{evaluation_html}</ul></article>""")
                for run in service.trajectories.runs_for_trace(trace["trace_id"]):
                    duration_label = (
                        f"{run['duration_ms']:.3f} ms"
                        if run["duration_ms"] > 0
                        else "duration not captured"
                    )
                    detail_label = {
                        "tool": "Tool call and result",
                        "generation": "Model request and response metadata",
                        "human_input": "Human action and persisted result",
                        "workflow": "Workflow output",
                        "node": "Internal node operation",
                        "evaluator": "Evaluation result",
                    }.get(run["run_type"], "Run output")
                    run_cards.append(f"""<article class="run-card"><div class="run-head"><div>
                    <strong>{_humanize(run["step_name"])}</strong><div class="id">{escape(run["run_id"])}</div></div>
                    <span class="badge {run["status"]}">{_humanize(run["status"])}</span></div>
                    <p class="meta">Trace {escape(trace["trace_id"])} · {escape(run["run_type"])} · {duration_label}</p>
                    <details><summary>Prior context</summary><div class="code">{_pretty(run["prior_context"])}</div></details>
                    <details><summary>Decision</summary><div class="code">{_pretty(run["decision"])}</div></details>
                    <details><summary>{detail_label}</summary><div class="code">{_pretty({"operation": run["tool_name"], "arguments": run["tool_arguments"], "result": run["tool_result"]})}</div></details></article>""")
            content = "".join(run_cards) or '<p class="subtle">No runs have been recorded.</p>'
            intro = "Inspect what each step received, decided, called, and returned."
        elif tab == "trace":
            cards = []
            for trace in reversed(traces):
                runs = service.trajectories.runs_for_trace(trace["trace_id"])
                evaluations = service.trajectories.evaluations_for_trace(trace["trace_id"])
                has_findings = any(item["severity"] == "fail" for item in evaluations)
                trace_badge_class = "findings" if has_findings else trace["status"]
                trace_status_label = (
                    "Complete with findings" if has_findings else _humanize(trace["status"])
                )
                sequence = " → ".join(_humanize(run["step_name"]) for run in runs)
                grounding_runs = [run for run in runs if run["step_name"] == "grounding_validation"]
                model_citations = (
                    grounding_runs[-1]["tool_result"].get("cited_evidence_ids", [])
                    if grounding_runs
                    else []
                )
                available_evidence = trace["outcome"].get("brief", {}).get("evidence_ids", [])
                evidence_note = (
                    f'<p class="meta">Model-cited evidence: {escape(", ".join(model_citations) or "none")}.'
                    + (
                        f" Available case evidence: {escape(', '.join(available_evidence))}."
                        if available_evidence
                        else ""
                    )
                    + "</p>"
                )
                findings = "".join(
                    f'<li class="eval-{item["severity"]}"><strong>{escape(item["severity"].upper())}</strong> · {escape(item["message"])}</li>'
                    for item in evaluations
                )
                if trace["status"] == "awaiting_human" and not has_findings:
                    trace_status_label = "Reached human checkpoint"
                cards.append(f"""<article class="run-card"><div class="run-head"><div><strong>{_humanize(trace["task_type"])}</strong>
                <div class="id">{escape(trace["trace_id"])}</div></div><span class="badge {trace_badge_class}">{trace_status_label}</span></div>
                <p>{escape(trace["user_intent"])}</p><p class="code">{escape(sequence)}</p>{evidence_note}
                <details><summary>Outcome and evaluations</summary><div class="code">{_pretty(trace["outcome"])}</div><ul>{findings}</ul></details></article>""")
            content = "".join(cards) or '<p class="subtle">No traces have been recorded.</p>'
            intro = "Review the ordered strategy and diagnostics for each single task."
        else:
            timeline = "".join(
                f"""<article class="run-card"><strong>{index}. {_humanize(trace["task_type"])}</strong>
                <div class="id">{escape(trace["trace_id"])}</div><p>{escape(trace["user_intent"])}</p>
                <span class="badge {trace["status"]}">{_humanize(trace["status"])}</span></article>"""
                for index, trace in enumerate(traces, start=1)
            )
            content = f"""<div class="notice"><strong>Thread identity</strong><br><span class="id">{escape(thread_id)}</span>
            <br>Case {escape(str(thread.get("case_id") if thread else case_id))}</div>{timeline}"""
            intro = "Follow every task and human turn across the durable case session."
        body = f"""<main class="shell"><section class="hero"><div><a href="/cases/{escape(case_id)}">← Case details</a>
        <div class="eyebrow" style="margin-top:18px">Agent observability</div><h1>Execution activity</h1>
        <p class="subtle">{escape(intro)}</p></div><a class="button secondary" href="/cases/{escape(case_id)}/graph">Open node graph</a></section>
        <section class="card"><nav class="tabs">{tabs}</nav>{content}</section></main>"""
        return _layout(f"Agent activity · {case_id}", body, case_id=case_id, active_page="activity")

    @app.get("/cases/{case_id}/graph", response_class=HTMLResponse)
    def execution_graph_page(
        case_id: str,
        trace_id: str | None = None,
        _: str = Depends(authorized),  # noqa: B008
    ) -> str:
        """Render interactive selected-trace and whole-thread execution graphs."""
        service = runtime["service"]
        try:
            service.status(case_id)
        except ToolError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        thread_id = service.thread_id(case_id)
        traces = service.trajectories.traces_for_thread(thread_id)
        if not traces:
            selected = None
        elif trace_id is None:
            selected = traces[-1]
        else:
            selected = next((item for item in traces if item["trace_id"] == trace_id), None)
            if selected is None:
                raise HTTPException(status_code=404, detail="trace was not found in this thread")
        options = "".join(
            f'<option value="{escape(item["trace_id"])}" {"selected" if selected and item["trace_id"] == selected["trace_id"] else ""}>{_humanize(item["task_type"])} · {escape(item["trace_id"][-8:])}</option>'
            for item in traces
        )
        selected_graph = '<p class="subtle">No traces have been recorded.</p>'
        if selected:
            selected_runs = service.trajectories.runs_for_trace(selected["trace_id"])
            selected_evaluations = service.trajectories.evaluations_for_trace(selected["trace_id"])
            selected_graph = "".join(
                _graph_node(run, selected_evaluations) for run in selected_runs
            ) + _human_checkpoint(selected)
        lanes = []
        for index, trace in enumerate(traces, start=1):
            runs = service.trajectories.runs_for_trace(trace["trace_id"])
            evaluations = service.trajectories.evaluations_for_trace(trace["trace_id"])
            nodes = "".join(_graph_node(run, evaluations) for run in runs)
            nodes += _human_checkpoint(trace)
            lanes.append(f"""<section class="thread-lane"><div class="run-head"><div>
            <span class="node-kind">Trace {index}</span><strong>{_humanize(trace["task_type"])}</strong>
            <div class="id">{escape(trace["trace_id"])}</div></div>
            <span class="badge {trace["status"]}">{_humanize(trace["status"])}</span></div>
            <div class="graph-flow">{nodes}</div></section>""")
        body = f"""<main class="shell"><section class="hero"><div>
        <a href="/cases/{escape(case_id)}/activity?tab=trace">← Execution activity</a>
        <div class="eyebrow" style="margin-top:18px">Interactive topology</div><h1>Agent execution graph</h1>
        <p class="subtle">Follow system nodes, tool operations, and human review checkpoints.</p></div></section>
        <section class="card"><div class="graph-toolbar"><div><h2>Selected trace</h2>
        <div class="legend"><span><i></i>Agent or tool</span><span><i class="human-key"></i>Human in the loop</span><span><i class="failed-key"></i>Failed</span></div></div>
        <form method="get"><label><strong>Trace</strong><br><select name="trace_id" onchange="this.form.submit()">{options}</select></label>
        <noscript><button class="button secondary" type="submit">Show trace</button></noscript></form></div>
        <div class="graph-flow">{selected_graph}</div></section>
        <section class="card" style="margin-top:20px"><h2>Whole thread flow</h2>
        <p class="subtle"><span class="id">{escape(thread_id)}</span> · Each lane is one task or continuation. Expand any node for its recorded details.</p>
        {"".join(lanes) or '<p class="subtle">No thread activity has been recorded.</p>'}</section></main>"""
        return _layout(f"Execution graph · {case_id}", body, case_id=case_id, active_page="graph")

    @app.post("/cases/{case_id}/review")
    def submit_review(
        case_id: str,
        decision: str = Form(),  # noqa: B008
        reason: str = Form(),  # noqa: B008
        idempotency_key: str = Form(),  # noqa: B008
        csrf: str = Form(),  # noqa: B008
        reviewer_id: str = Depends(authorized),  # noqa: B008
    ) -> RedirectResponse:
        service = runtime["service"]
        if not secrets.compare_digest(csrf, csrf_token(security_config, case_id)):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        try:
            is_resume = service.status(case_id)["stage"] in {"pending_review", "post_review"}
            if is_resume:
                service.resume(
                    case_id,
                    actor_id=reviewer_id,
                    roles=frozenset({"reviewer"}),
                    decision=decision,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    correlation_id=f"ui_{uuid4().hex}",
                )
            else:
                service.follow_up_review(
                    case_id,
                    actor_id=reviewer_id,
                    decision=decision,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    correlation_id=f"ui_followup_{uuid4().hex}",
                )
        except ToolError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail="agent execution could not complete"
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=503, detail="agent provider is temporarily unavailable"
            ) from error
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.post("/api/v1/cases/{case_id}/reviews")
    def review_webhook(
        case_id: str,
        payload: ReviewWebhookRequest,
        request: Request,
    ) -> dict[str, object]:
        """Continue the real LangGraph workflow from an authenticated API request."""
        configured_key = os.getenv("CLAIMTRIAGE_WEBHOOK_API_KEY", "").strip()
        supplied_key = request.headers.get("x-api-key", "")
        if not configured_key:
            raise HTTPException(status_code=503, detail="webhook API key is not configured")
        if not secrets.compare_digest(supplied_key, configured_key):
            raise HTTPException(status_code=401, detail="invalid API key")
        service = runtime["service"]
        try:
            is_resume = service.status(case_id)["stage"] in {"pending_review", "post_review"}
            if is_resume:
                result = service.resume(
                    case_id,
                    actor_id=payload.actor_id,
                    roles=frozenset({"reviewer"}),
                    decision=payload.decision,
                    reason=payload.reason,
                    idempotency_key=payload.idempotency_key,
                    correlation_id=f"webhook_{uuid4().hex}",
                )
            else:
                result = service.follow_up_review(
                    case_id,
                    actor_id=payload.actor_id,
                    decision=payload.decision,
                    reason=payload.reason,
                    idempotency_key=payload.idempotency_key,
                    correlation_id=f"webhook_followup_{uuid4().hex}",
                )
        except ToolError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=503, detail="agent provider is temporarily unavailable"
            ) from error
        traces = service.trajectories.traces_for_thread(service.thread_id(case_id))
        stage = result["stage"] if is_resume else "complete"
        agent_followup = result.get("agent_followup", {}) if is_resume else result
        return {
            "case_id": case_id,
            "thread_id": service.thread_id(case_id),
            "trace_id": traces[-1]["trace_id"],
            "stage": stage,
            "agent_followup": agent_followup,
        }

    @app.post("/showcase/reset")
    def reset_showcase(
        csrf: str = Form(),  # noqa: B008
        _: str = Depends(authorized),  # noqa: B008
    ) -> RedirectResponse:
        if not security_config.allow_showcase_reset:
            raise HTTPException(status_code=404, detail="showcase reset is disabled")
        if not secrets.compare_digest(csrf, csrf_token(security_config, "showcase-reset")):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        runtime["service"].close()
        prepare_showcase_database(database_path)
        runtime["service"] = WorkflowService(database_path)
        app.state.workflow_service = runtime["service"]
        return RedirectResponse("/", status_code=303)

    return app
