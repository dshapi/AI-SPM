"""
Policy Simulator — dry-run policy testing before deployment.
"""
from __future__ import annotations
import logging
import time
from fastapi import FastAPI, Header
from platform_shared.models import (
    PolicySimulationRequest, PolicySimulationResult, HealthStatus, ServiceInventory,
)
from platform_shared.opa_client import get_opa_client
from platform_shared.security import extract_bearer_token, validate_jwt_token

log = logging.getLogger("policy-simulator")
_start_time = time.time()
app = FastAPI(title="CPM Policy Simulator v3", version="3.0.0")


@app.get("/health", response_model=HealthStatus)
def health():
    return HealthStatus(
        status="ok", service="policy_simulator", version="3.0.0",
        checks={"opa": get_opa_client().health_check()},
        uptime_seconds=int(time.time() - _start_time),
    )


@app.get("/inventory", response_model=ServiceInventory)
def inventory():
    return ServiceInventory(
        service="cpm-policy-simulator", version="3.0.0",
        capabilities=["policy_dry_run", "batch_simulation", "decision_trace"],
    )


@app.post("/simulate", response_model=PolicySimulationResult)
def simulate(req: PolicySimulationRequest, authorization: str = Header(None)):
    token = extract_bearer_token(authorization)
    validate_jwt_token(token)

    opa = get_opa_client()
    results = []
    allow_count = escalate_count = block_count = 0

    for sample in req.sample_events:
        event_id = sample.get("event_id", "unknown")

        prompt_r = opa.eval("/v1/data/spm/prompt/allow", sample)
        tool_r = opa.eval("/v1/data/spm/tools/allow", sample)
        memory_r = opa.eval("/v1/data/spm/memory/allow", sample)
        agent_r = opa.eval("/v1/data/spm/agent/resolve_tool", sample)

        prompt_decision = prompt_r.get("decision", "block")
        if prompt_decision == "allow":
            allow_count += 1
        elif prompt_decision == "escalate":
            escalate_count += 1
        else:
            block_count += 1

        results.append({
            "event_id": event_id,
            "posture_score": sample.get("posture_score"),
            "signals": sample.get("signals", []),
            "prompt": prompt_r,
            "tool": tool_r,
            "memory": memory_r,
            "agent_tool_resolution": agent_r,
        })

    return PolicySimulationResult(
        tenant_id=req.tenant_id,
        total_events=len(req.sample_events),
        allow_count=allow_count,
        escalate_count=escalate_count,
        block_count=block_count,
        results=results,
    )
