set -e

kubectl run cni-debug --rm -i --restart=Never \
  --overrides='{"spec":{"hostNetwork":true,"hostPID":true,"containers":[{"name":"d","image":"alpine:3.19","command":["/bin/sh","-c"],"args":["echo === /etc/cni/net.d ===; ls -la /host/etc/cni/net.d/ 2>/dev/null; echo; echo === conflist before ===; cat /host/etc/cni/net.d/*.conflist 2>/dev/null || cat /host/etc/cni/net.d/*.conf 2>/dev/null; echo; echo === stripping istio plugin ===; for f in /host/etc/cni/net.d/*.conflist; do test -f \"$f\" || continue; sed -i.bak -E '\''s/,\\{[^{}]*\"type\": *\"istio-cni\"[^{}]*\\}//g; s/\\{[^{}]*\"type\": *\"istio-cni\"[^{}]*\\},?//g'\'' \"$f\"; echo patched $f; done; echo; echo === conflist after ===; cat /host/etc/cni/net.d/*.conflist 2>/dev/null"]}],"volumes":[],"hostPath":null}' \
  --image=alpine:3.19 \
  -- /bin/true || true

kubectl run cni-debug --rm -i --restart=Never \
  --overrides="$(cat <<'JSON'
{
  "spec": {
    "hostNetwork": true,
    "hostPID": true,
    "containers": [{
      "name":"d",
      "image":"alpine:3.19",
      "command":["/bin/sh","-c"],
      "args":["echo === before ===; cat /host/etc/cni/net.d/*.conflist 2>/dev/null; echo; for f in /host/etc/cni/net.d/*.conflist; do [ -f \"$f\" ] || continue; cp \"$f\" \"$f.bak.$(date +%s)\"; python3 -c 'import json,sys,re; p=sys.argv[1]; d=json.load(open(p)); d[\"plugins\"]=[x for x in d[\"plugins\"] if x.get(\"type\")!=\"istio-cni\"]; json.dump(d,open(p,\"w\"),indent=2)' \"$f\" 2>/dev/null || sed -i -E 's/,?\\{[^{}]*\"type\": *\"istio-cni\"[^{}]*\\}//g' \"$f\"; echo patched $f; done; echo; echo === after ===; cat /host/etc/cni/net.d/*.conflist"],
      "volumeMounts":[{"name":"host","mountPath":"/host"}],
      "securityContext":{"privileged":true}
    }],
    "volumes":[{"name":"host","hostPath":{"path":"/"}}]
  }
}
JSON
)" \
  --image=alpine:3.19
