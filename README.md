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
  helm upgrade --install $u ./chart -n $u --create-namespace -f tenants/$u.yaml --atomic --wait
done
curl -k https://user1.localtest.me
```

## Scaling
HPA per tenant: 2-5 replicas, CPU 50% / memory 70%. ResourceQuota caps each tenant's total CPU/memory/pods.
PDB keeps at least 1 pod up during rollouts and node drains.

## Rollback
`helm upgrade --atomic --wait` rolls back automatically when readiness fails. Manual: `helm rollback <user> -n <user>`.
Demo: run the workflow with `bad_deploy=true`.

## Kafka
`docker compose -f kafka/docker-compose.yml up -d`; consume with `scripts/consume-events.sh`.
