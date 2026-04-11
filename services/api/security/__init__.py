"""
security — reusable prompt security evaluation package.

Exposes:
    PromptSecurityService   core evaluation service (evaluate async method)
    PromptDecision          decision data-class returned by evaluate()
    ScreeningContext        caller-supplied context (tenant, roles, session)

Usage::

    from security import PromptSecurityService, PromptDecision, ScreeningContext
    from security.adapters.guard_adapter import LlamaGuardAdapter
    from security.adapters.policy_adapter import OPAAdapter

    svc = PromptSecurityService(
        guard_adapter=LlamaGuardAdapter(guard_url="http://guard:8200"),
        policy_engine=OPAAdapter(opa_url="http://opa:8181"),
    )
    decision = await svc.evaluate(prompt, ScreeningContext(tenant_id="t1"))
    if decision.is_blocked:
        ...
"""
from security.service import PromptSecurityService
from security.models import PromptDecision, ScreeningContext

__all__ = ["PromptSecurityService", "PromptDecision", "ScreeningContext"]
