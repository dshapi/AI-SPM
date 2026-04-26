# opa/policies/model_policy.rego
package model_policy

import future.keywords.if
import future.keywords.in

# Default deny
default allow = false

# Allow if no model_id specified (backward compat with old clients)
allow if {
    not input.model_id
}

# Allow if model is not in blocked or retired sets
allow if {
    input.model_id
    not input.model_id in data.blocked_models
    not input.model_id in data.retired_models
}
