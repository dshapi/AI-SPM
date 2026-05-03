#!/bin/sh
# This script was removed in May 2026.
#
# It was a Rancher-Desktop-Lima-VM-only helper for installing the
# runsc containerd handler.  AISPM now runs exclusively on kind, and
# install-gvisor.sh handles the per-kind-node patching natively
# (docker exec into each `io.x-k8s.kind.cluster`-labelled container).
#
# `git rm deploy/scripts/patch-containerd-runsc.sh` after this change
# is merged.
echo "patch-containerd-runsc.sh has been removed.  Use install-gvisor.sh instead." >&2
exit 1
