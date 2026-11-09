# Multi-tenant website hosting on Docker Desktop Kubernetes

Layout: `app/` Flask app + Dockerfile, `chart/` Helm chart, `tenants/` per-user values,
`k8s/` cluster issuer, `kafka/` compose, `scripts/` event helpers, `.github/workflows/deploy.yml` CI/CD.

## Dynamic domain mapping
Each tenant is one Helm release in its own namespace. Domains are a list in the tenant values file and
render into that tenant's Ingress (host rules + TLS). To map a new domain, add it to `domains:` and run
`helm upgrade`: only the Ingress changes, the cluster is never redeployed. cert-manager issues the
certificate automatically from the Ingress annotation (self-signed locally; swap the ClusterIssuer for
Let's Encrypt in a real cluster).

## Deploy
```
kubectl apply -f k8s/cluster-issuer.yaml
docker build -t multitenant-site:v1 app/
for u in user1 user2 user3; do
  helm upgrade --install $u ./chart -n $u --create-namespace -f tenants/$u.yaml --rollback-on-failure --wait
done
curl -k https://user1.localtest.me
```

## Scaling
HPA per tenant: 2-5 replicas, CPU 50% / memory 70%. ResourceQuota caps each tenant's total CPU/memory/pods.
PDB keeps at least 1 pod up during rollouts and node drains.

## Rollback
`helm upgrade --rollback-on-failure --wait` rolls back automatically when readiness fails. Manual: `helm rollback <user> -n <user>`.
Demo: run the workflow with `bad_deploy=true`.

## Kafka
`docker compose -f kafka/docker-compose.yml up -d`; consume with `scripts/consume-events.sh`.

## Scaling strategy and resource allocation
- Each tenant runs in its own namespace with a ResourceQuota (1 CPU / 1Gi requested, 2 CPU / 2Gi limits, 10 pods).
- Each pod requests 100m CPU / 128Mi and is limited to 250m / 256Mi. HPA targets 50% CPU and 70% memory, 2 to 5 replicas.
- Memory requests were raised from 64Mi to 128Mi after the HPA scaled on idle memory (85% of the request).
- A PodDisruptionBudget (minAvailable 1) and RollingUpdate with maxUnavailable 0 keep the site up during releases.
- Load test: `hey -z 4m -c 40 https://user2.localtest.me:8443/load` scaled user2 from 2 to 5 replicas (CPU peaked at 244% of target).

## Network isolation
A default-deny ingress NetworkPolicy plus an allow rule for the ingress controller. A pod in user2 cannot reach user1 (wget times out).

## Rollback
`helm upgrade --rollback-on-failure --wait` reverts automatically when readiness fails. Demo: run the workflow with `bad_deploy=true`.
`helm history` shows the failed revision followed by "Rollback to N", and the site keeps serving the previous version.

## Notes for local setup
- TLS uses a cert-manager self-signed ClusterIssuer. In production, replace it with a Let's Encrypt ClusterIssuer (needs a public domain).
- Domains use localtest.me (resolves to 127.0.0.1); ingress is reached via `kubectl port-forward ... 8443:443`.
- The runner is self-hosted so the pipeline can reach the local cluster.
- Monitoring: kube-prometheus-stack with the operator pinned to v0.94.2 (v0.95.1 had no arm64 image).
