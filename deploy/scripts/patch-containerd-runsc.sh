#!/bin/sh
# deploy/scripts/patch-containerd-runsc.sh
#
# Run this INSIDE the Rancher Desktop Lima VM. It appends the runsc
# runtime handler to /etc/containerd/config.toml if it's not there
# already, then restarts containerd so the new handler is loaded.
#
# Idempotent — safe to re-run.
#
# Usage from your Mac shell:
#   cat deploy/scripts/patch-containerd-runsc.sh | rdctl shell sudo sh

set -e
CFG=/etc/containerd/config.toml

if [ ! -f "$CFG" ]; then
  echo "MISSING: $CFG"
  exit 1
fi

if grep -q "runtimes.runsc" "$CFG"; then
  echo "runsc already configured in $CFG (no change)"
else
  cp "$CFG" "${CFG}.bak.$(date +%s)"
  printf '\n# gVisor runsc handler\n[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]\n  runtime_type = "io.containerd.runsc.v1"\n' >> "$CFG"
  echo "appended runsc handler to $CFG"
fi

# Restart containerd — try whichever supervisor this VM uses.
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q '^containerd'; then
  systemctl restart containerd
  echo "restarted containerd via systemd"
elif command -v rc-service >/dev/null 2>&1 && rc-service -e containerd 2>/dev/null; then
  rc-service containerd restart
  echo "restarted containerd via openrc"
elif [ -x /etc/init.d/containerd ]; then
  /etc/init.d/containerd restart
  echo "restarted containerd via init.d"
else
  echo "WARNING: could not find a supervisor for containerd — restart Rancher Desktop manually"
fi

# Show the runsc block from the live config so you can confirm.
echo
echo "=== runsc block in $CFG ==="
grep -A2 "runtimes.runsc" "$CFG" || echo "(not present — patch failed)"
