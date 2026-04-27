set -e

CORE=$(kubectl -n kube-system get pod -l k8s-app=kube-dns -o jsonpath='{.items[0].metadata.name}')
CORE_IP=$(kubectl -n kube-system get pod "$CORE" -o jsonpath='{.status.podIP}')
echo "coredns pod: $CORE @ $CORE_IP"
echo

echo "=== is coredns actually listening on :53 ==="
kubectl -n kube-system exec "$CORE" -- /bin/sh -c 'netstat -tlnup 2>/dev/null || ss -tlnup' || true
echo

echo "=== kube-dns endpoints ==="
kubectl -n kube-system get endpoints kube-dns -o yaml | grep -A1 -E 'addresses|ports' | head -30
echo

echo "=== does anything in kube-system look like kube-proxy / kube-router ==="
kubectl -n kube-system get pods | grep -iE 'proxy|router|cni|flannel|cilium|kindnet'
echo

echo "=== NetworkPolicies in kube-system ==="
kubectl -n kube-system get netpol 2>/dev/null
echo

echo "=== NetworkPolicies in aispm (anything blocking egress) ==="
kubectl -n aispm get netpol 2>/dev/null
echo

echo "=== direct pod-IP DNS test (bypasses Service) ==="
kubectl run dns-direct --rm -i --restart=Never --image=busybox:1.36 -- \
  sh -c "nslookup istiod.istio-system.svc.cluster.local $CORE_IP" || true
echo

echo "=== service-IP DNS test ==="
kubectl run dns-svc --rm -i --restart=Never --image=busybox:1.36 -- \
  sh -c 'nslookup istiod.istio-system.svc.cluster.local 192.168.194.138' || true
