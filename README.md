# Multi-Tenant Website Hosting on Kubernetes (Docker Desktop)

A multi-tenant hosting setup: each user gets a website in its own namespace, served over HTTPS on its own domain,
with autoscaling, resource quotas, network isolation, CI/CD with automatic rollback, Kafka events and Grafana dashboards.

## Repository layout

| Path | Purpose |
|---|---|
| `app/` | Flask sample app (`/`, `/health`, `/ready`, `/load`) and Dockerfile. Publishes `WebsiteCreated` to Kafka on startup |
| `chart/` | Helm chart: Deployment, Service, Ingress (TLS), HPA, PDB, ResourceQuota, NetworkPolicy |
| `tenants/` | One values file per user (`user1.yaml`, `user2.yaml`, `user3.yaml`) |
| `k8s/cluster-issuer.yaml` | cert-manager self-signed ClusterIssuer |
| `kafka/docker-compose.yml` | Single-node Kafka (KRaft) |
| `scripts/` | `publish-event.sh` and `consume-events.sh` |
| `.github/workflows/deploy.yml` | CI/CD pipeline |

## Prerequisites

- Docker Desktop with Kubernetes enabled (4 CPUs, 6-8 GB RAM), `kubectl`, `helm`, `hey`
- A GitHub repo with a self-hosted runner on the same machine (see CI/CD)

## 1. Install cluster add-ons (once)

```bash
helm upgrade --install ingress-nginx ingress-nginx --repo https://kubernetes.github.io/ingress-nginx \
  -n ingress-nginx --create-namespace

helm upgrade --install cert-manager cert-manager --repo https://charts.jetstack.io \
  -n cert-manager --create-namespace --set crds.enabled=true

helm upgrade --install metrics-server metrics-server --repo https://kubernetes-sigs.github.io/metrics-server \
  -n kube-system --set 'args={--kubelet-insecure-tls}'

# The operator tag is pinned because the chart's default tag had no linux/arm64 image (Apple Silicon).
helm upgrade --install monitoring kube-prometheus-stack --repo https://prometheus-community.github.io/helm-charts \
  -n monitoring --create-namespace \
  --set alertmanager.enabled=false \
  --set prometheusOperator.image.tag=v0.94.2 \
  --set prometheusOperator.prometheusConfigReloader.image.tag=v0.94.2 \
  --set prometheusOperator.admissionWebhooks.enabled=false \
  --set prometheusOperator.tls.enabled=false
```

## 2. Deploy the tenants

The Docker Desktop node is a container, so it cannot see images built on the host. Build and load the image into it:

```bash
kubectl apply -f k8s/cluster-issuer.yaml
docker build -t multitenant-site:v1 app/
docker save multitenant-site:v1 | docker exec -i desktop-control-plane ctr -n k8s.io images import -

for u in user1 user2 user3; do
  helm upgrade --install $u ./chart -n $u --create-namespace -f tenants/$u.yaml \
    --rollback-on-failure --wait --timeout 120s
done
kubectl get all -n user1
```

## 3. Access the sites

Ingress is reached through a port-forward (leave it running):

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8443:443
curl -k https://user1.localtest.me:8443
```

`localtest.me` and all its subdomains resolve to 127.0.0.1, so no hosts-file edits are needed.

## Dynamic domain mapping

A tenant's domains are a list in its values file and are rendered into that tenant's Ingress (host rules and TLS).
Adding a domain only changes the Ingress; the cluster is not redeployed. cert-manager issues the certificate automatically.

```bash
helm upgrade user1 ./chart -n user1 --reuse-values \
  --set 'domains={user1.localtest.me,shop.user1.localtest.me}' --rollback-on-failure --wait
curl -k https://shop.user1.localtest.me:8443
```

To keep the change, also add the domain to `tenants/user1.yaml`.

## TLS

A cert-manager self-signed ClusterIssuer is used locally. In production, replace `selfsigned-issuer` with a
Let's Encrypt ClusterIssuer (requires a public domain); the Ingress annotation stays the same.

## Scaling and resource allocation

- Pod: requests 100m CPU / 128Mi, limits 250m / 256Mi (memory request raised from 64Mi after the HPA scaled on idle memory).
- HPA per tenant: 2 to 5 replicas, 50% CPU and 70% memory targets.
- ResourceQuota per namespace: 1 CPU / 1Gi requested, 2 CPU / 2Gi limits, 10 pods. Pods without requests and limits are rejected.
- PodDisruptionBudget (minAvailable 1) and RollingUpdate with maxUnavailable 0 keep each site up during releases.
- NetworkPolicy: default-deny ingress, allow only the ingress controller. A pod in one tenant cannot reach another tenant.

Load test (watch the HPA in another terminal with `kubectl get hpa -n user2 -w`):

```bash
hey -z 4m -c 40 https://user2.localtest.me:8443/load
```

Grafana: `kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80`, then open http://localhost:3000
(user `admin`; password: `kubectl get secret -n monitoring monitoring-grafana -o jsonpath='{.data.admin-password}' | base64 -d`).
Dashboard: Kubernetes / Compute Resources / Namespace (Pods).

## Kafka

```bash
docker compose -f kafka/docker-compose.yml up -d      # single-node KRaft broker, topic website-events (auto-created)
./scripts/consume-events.sh                           # consumer (replays from the beginning)
./scripts/publish-event.sh WebsiteCreated user1 test  # manual event
```

The broker advertises `host.docker.internal:9092` so both the host and the pods can reach it.
Each pod publishes `WebsiteCreated` on startup (two gunicorn workers, so a pod start can produce two events).

## CI/CD (GitHub Actions)

`deploy.yml` runs on push to `main` and on manual dispatch, on a self-hosted runner so it can reach the local cluster.

1. **build**: build the image, push to GHCR (`ghcr.io/<owner>/multitenant-site:<sha>`), load it into the cluster.
2. **deploy**: matrix over user1, user2, user3; `helm upgrade --install ... --rollback-on-failure --wait --timeout 90s`.
3. **events**: success publishes `WebsiteCreated`; failure prints `helm history` and publishes `DeploymentRolledBack`.

Register the runner (Repo > Settings > Actions > Runners > New self-hosted runner, macOS ARM64), then run
`./config.sh --url <repo-url> --token <registration token>` followed by `./run.sh` and keep it running.
The registration token is short-lived; never commit it.

## Rollback

`--rollback-on-failure --wait` reverts the release automatically when the new pods do not become ready.
Demo: Actions > deploy > Run workflow > tick `bad_deploy`. This points the readiness probe at a path that does not exist,
the deploy jobs fail, and `helm history <user> -n <user>` shows a failed revision followed by "Rollback to N".
The site keeps serving the previous version throughout.

Manual rollback: `helm rollback <user> -n <user>`.

## Cleanup

```bash
for u in user1 user2 user3; do helm uninstall $u -n $u; kubectl delete ns $u; done
docker compose -f kafka/docker-compose.yml down
helm uninstall monitoring -n monitoring
```
