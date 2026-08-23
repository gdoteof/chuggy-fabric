# chuggy-fabric — k3s nodes for the chuggy fabric

NixOS configuration for repurposed mini PCs acting as the build and run target for
[chuggy](https://github.com/kasofsk/chuggy), so development doesn't need paid cloud
infrastructure.

Each box runs a **single-node k3s cluster**: server and worker on the same
machine, which is the steady state. Cloud spot instances join as agents when work
needs to burst; that isn't built yet, but the pieces that are expensive to
retrofit are in place.

Every dev runs their own independent cluster from this shared config. Hosts differ
only by their own directory.

## Layout

    flake.nix                       one nixosConfiguration per host
    flake.lock                      the pin — commit every change to it

    modules/common.nix              identity, access, packages, nix settings
    modules/node-prep.nix           k8s prerequisites, workstation teardown
    modules/wireguard.nix           the mesh, with chuggy.wireguard.* options
    modules/k3s-server.nix          the cluster role, with chuggy.k3s.* options

    modules/cloudflare-tunnel.nix   public ingress, with chuggy.tunnel.* options
    modules/flux.nix                bootstraps Flux from the machine layer

    cluster/flux-system/            Flux install + what repo it follows
    cluster/apps/                   the cluster state this repo declares
    cluster/apps/kustomization.yaml the enumeration of that state, and two
                                    generated ConfigMaps
    cluster/apps/ory/               config documents those ConfigMaps carry --
                                    not manifests, and not in `resources`

    hosts/gtr/default.nix           geoff's Beelink GTR: hostname, radios, mesh, k3s, tunnel
    hosts/gtr/hardware-configuration.nix

    nixos-live/                     the original /etc/nixos, captured verbatim

Anything in `modules/` must be true of every node. Anything hardware-specific —
disks, radios, hostname — belongs in `hosts/<name>/`. The Wi-Fi blacklist is the
worked example: `iwlwifi` is correct for the GTR's AX200 and wrong for any box
with a different card, so it lives in the host file.

`nixos-live/` is history, not input. Nothing imports it.

What `cluster/apps/` declares is deliberately less than what the cluster runs.
The `chuggy-git` and `chuggy-work` namespaces were bootstrapped by hand from the
[chuggy](https://github.com/kasofsk/chuggy) repo as deployment rehearsal
fixtures — transient by intent, so declaring them here would commit Flux to
maintaining state the rehearsal means to tear down.

One of those fixtures is a **second Flux control loop**, which is why the
[ownership label](#verified) has to be read by value rather than by presence.
`Kustomization/rig` in `chuggy-git` follows an in-cluster git server and
reconciles a ConfigMap beside it every minute, so that object carries
`kustomize.toolkit.fluxcd.io/name: rig` — Flux-managed, and no business of this
repo. What this repo owns is `name: apps` in `namespace: flux-system`. Anything
else, labelled or not, came from somewhere that is not `cluster/apps/`.

## Workflow

The box is not the source of truth, and neither is a copy of this directory
sitting on it. Two loops, and keeping them apart is the point.

**Iterating** — fast, no commit needed. Copy the tree over and build there:

    rsync -a --delete --exclude nixos-live --exclude .git \
      ~/claude/chuggy-fabric/ geoff@192.168.0.114:/home/geoff/fabric-test/

    ssh geoff@192.168.0.114 \
      'cd fabric-test && nixos-rebuild build --flake .#gtr'

`build` and `test` are what that copy is for. Delete it when you are done — it is
scratch, not a checkout.

**Landing** — commit, push, and build the commit, not a copy of it:

    sudo nixos-rebuild switch \
      --flake github:gdoteof/chuggy-fabric/<full-commit-sha>#gtr

**Pin the full SHA. Do not use the bare `github:owner/repo` form.** That form
resolves the branch head through a cache with a one-hour TTL (`tarball-ttl`), so
pushing and immediately rebuilding quietly builds the *previous* revision. There
is no error: the build succeeds, activation succeeds, and your change is simply
not there. Adding the first mesh peer hit exactly this — `wg show` listed no
peer, and grepping the new generation found no trace of the key.

The tell is in the output. When Nix really fetches it prints
`unpacking 'github:...'`; when it serves the cache it prints nothing and goes
straight to `building the system configuration`. A pinned SHA sidesteps the
question entirely, and leaves shell history that records exactly what was
deployed — which is the point of building from a commit at all.

The running system then corresponds to a revision you can name, instead of to
whatever happened to be in someone's working tree at the time. Flux already works
this way for the cluster layer; this is the machine layer catching up, and it
means both can be checked against the same commit.

| Command | Effect |
|---|---|
| `nixos-rebuild build` | builds only, no activation |
| `nixos-rebuild test` | activates now, **not** the boot default — reboot undoes it |
| `nixos-rebuild switch` | activates and makes it the boot default |

`test` before `switch`. If a change breaks the network, a power cycle recovers it.

### Never `switch` from the rsync copy

Two reasons, and the second one is quiet:

- Nothing would record what the box is running. Lose the workstation and the
  config is gone — the exact failure this repo exists to prevent.
- **A flake built from a dirty git tree silently omits untracked files.** This
  scratch directory once acquired a stray `.git` with zero commits in it —
  `git init` and `git add`, never committed — which made every build print a
  dirty-tree warning and quietly drop anything unstaged. That time it was
  harmless, because the one untracked file was a cluster manifest the Nix build
  never reads. The next time it is a file a module imports.

Note that `--exclude .git` in the rsync above is what let that stub survive: the
copy's own git state is never overwritten, only its files are.

## The cluster

k3s, chosen over kubeadm because it is a single binary that expects agents to
join over a network and tolerates them vanishing — which is the spot-worker shape.
kubeadm on NixOS fights the FHS assumptions for no benefit here.

Bundled components are left **on**: Traefik (ingress), ServiceLB (LoadBalancer
services), local-path (default StorageClass), CoreDNS, metrics-server. Fastest
path to a usable target, each removable with one flag.

**Know the sharp edge:** a `local-path` PVC is a directory on the node that
created it, so any pod with one is pinned to that node. Correct for the durable
box, wrong for spot agents. Keep stateful work — chuggy's journal above all — on
the durable node using the label below.

The server carries `chuggy.dev/durable=true`. Spot agents will not, so a
`nodeSelector` is enough to pin work that must not evaporate.

**Set the hostname before k3s first starts.** A k8s node name is fixed at
registration, and `networking.hostName` does not take effect on the running system
during `nixos-rebuild switch` — it writes `/etc/hostname`, which systemd only reads
at boot. So k3s registers under the *old* kernel hostname, and the next reboot
registers a *second* node under the new one, leaving a stale `NotReady` entry.

This happened here: the node came up as `nixos` and had to be re-registered as
`gtr`. If you hit it, `hostnamectl set-hostname <name>`, restart k3s, then
`kubectl delete node <old-name>`. Trivial on an empty cluster, unpleasant once
workloads have scheduled.

kubeconfig is written world-readable (`--write-kubeconfig-mode=0644`). That grants
nothing new: `geoff` already has passwordless sudo, so the admin credential is
reachable regardless. Revisit if these boxes ever get a second human user.

## Ingress

Public traffic arrives through a **Cloudflare Tunnel**, not a port-forward. The
tunnel is an outbound connection from the box to Cloudflare's edge, so the router
needs no configuration and the residential IP can change freely. That kills the
inbound-HTTP half of the NAT problem that dropping Tailscale created — the other
half, agents dialling 6443, still needs the WireGuard mesh.

    internet -> Cloudflare edge -> tunnel -> cloudflared -> Traefik :80
             -> Ingress -> Service -> Pod

cloudflared forwards to Traefik rather than to individual services, so Traefik
owns per-app routing. Adding an app is three things: a hostname in
`chuggy.tunnel.hostnames`, a DNS route, and a k8s Ingress.

    cloudflared tunnel route dns 84115dde-a1d0-4e8a-832a-e4da2cf98180 <host>

**Use the tunnel UUID, not its name.** `cloudflared tunnel route dns gtr ...`
silently created the CNAME against a *different* tunnel here — an unrelated older
one — and reported success. Pass the UUID and verify what the log says it routed.

Hostnames are enumerated rather than wildcarded. A `*.vteng.io` rule would work
and would save a rebuild per app, but then nothing in the repo would say what is
publicly reachable. The list is the record.

### What is and is not exposed

Only HTTP, and only for hostnames in that list. The Kubernetes API is never a
tunnel ingress rule. Verified from outside: `whoami.vteng.io` serves, `6443` and
`22` both refuse.

Routing 6443 through the tunnel was considered for remote `kubectl` and
rejected. It works, and cloudflared cannot read the traffic — kubectl verifies
the k3s certificate end to end — but the gate would then be a Cloudflare Access
policy, putting a third party in the auth path. That is the same objection that
removed Tailscale. Remote `kubectl` goes over the WireGuard mesh instead; see
[Giving someone else access](#giving-someone-else-access).

Be precise about *why* 6443 is safe, though: k3s binds it on `*:6443` and the
NixOS firewall allows it, so it is reachable from anything on the house LAN and
over the mesh — by design, that is how `kubectl` works from the workstation. It is
not reachable from the internet because there is no port-forward. Protection is
NAT, not the firewall. If a port-forward is ever added for WireGuard, forward
**only** UDP 51820.

Worth knowing what "reachable" would cost if that ever changed: an
unauthenticated caller gets `401 Unauthorized`, and `system:anonymous` is granted
nothing. Exposure would mean the control plane's authn surface faces the
internet, not that anyone walks in.

### Deliberate deviation

This is a *locally managed* tunnel — ingress rules live in this repo. Cloudflare
recommends token-based remotely managed tunnels for new deployments, with the
config in the dashboard. That would split the source of truth across a dashboard
and a git repo right when a second dev starts reusing this one.

### Credentials

The tunnel secret is at `/var/lib/cloudflared/<id>.json`, `0400
cloudflared:cloudflared`, copied out of band. **It is not in this repo and must
not be** — this repository is public. `chuggy.tunnel.credentialsFile` is a path,
never a value.

Note the ordering trap: the `cloudflared` user does not exist until the first
`nixos-rebuild switch` that enables the service, so the file cannot be chowned to
it beforehand. Switch, chown, restart.

## GitOps

Cluster state is reconciled by **Flux**, not applied by hand. `cluster/apps/` is
the desired state; if the cluster drifts from it, Flux corrects it.

### Three layers, three change rates

| Layer | What | Changes | Applied by |
|---|---|---|---|
| Machine | OS, k3s itself, cloudflared, WireGuard | rarely | `nixos-rebuild` |
| Cluster | apps, ingresses, addons | constantly | Flux, continuously |
| App | chuggy's own manifests and image tags | per commit | Flux, from its own repo |

Machine and cluster share this repo because for a single-node cluster they are
one unit of reproducibility: clone, `nixos-rebuild switch`, and the box *and* its
workloads exist. `hosts/<name>/` and `cluster/` sit side by side for the same
reason. chuggy's own manifests belong in the chuggy repo when it has them, added
as a second Flux `GitRepository` — no need to decide that now.

What does *not* belong in the machine layer is app config. NixOS could write app
manifests into k3s's auto-deploy directory and they would be declarative, but
every app change would become an OS rebuild on every box, and nothing would
correct drift.

### Bootstrap, and why it is this short

`services.k3s.manifests` links Flux's manifests into
`/var/lib/rancher/k3s/server/manifests`, which k3s applies at startup:

    nixos-rebuild switch -> k3s starts -> k3s applies Flux
      -> Flux reads this repo -> apps exist

Nobody runs `kubectl`. A fresh box, or the second dev's box, reaches a populated
cluster from one command.

This deliberately is **not** `flux bootstrap`. That command wants a GitHub token
with write scope so it can commit manifests and create a deploy key. Those
manifests are already committed here, and the repo is public, so Flux needs no
credentials at all — which matters given how tangled the GitHub identities on
these machines are. Fewer moving parts, nothing to rotate.

`source-controller`, `kustomize-controller`, and `helm-controller` are
installed. `helm-controller` arrived with kube-prometheus-stack: a chart that
size is worth consuming as a `HelmRelease` rather than vendoring its rendered
output into `cluster/apps/`. `notification-controller` is still omitted — it
exists to route alerts outward, and there is nowhere to route them yet, which is
the same reason Alertmanager is disabled in `cluster/apps/monitoring.yaml`.

### Adding an app

Drop a manifest in `cluster/apps/`, commit, push. Flux picks it up within 5
minutes, or immediately with `flux reconcile kustomization apps`.

**State the namespace on every resource.** Flux rejects namespaced resources that
declare none when the Kustomization sets no `targetNamespace` — the error is
`namespace not specified: the server could not find the requested resource`,
which does not obviously mean what it says.

If the app needs to be public it also needs a hostname in
`chuggy.tunnel.hostnames` and a DNS route, which is a NixOS rebuild.

`prune: true` is set, so deleting a file deletes the resource. Without it,
removals in git are silently ignored.

**Add the file to `cluster/apps/kustomization.yaml` as well.** That directory
carries its own kustomization now — needed so two Ory ConfigMaps get a name
derived from their content — and a kustomization applies what it enumerates and
nothing else. A manifest that is in the directory and not in that list is not
applied, and `prune` then deletes it if it was there before. There is no check
for this; the list and `ls` have to agree, and a reviewer is what makes them.

### Verified

- Flux installed itself via k3s auto-deploy on `nixos-rebuild switch`.
- `whoami` was deleted by hand first, then **created by Flux** from git — it
  carries `kustomize.toolkit.fluxcd.io/name: apps`, which a hand-applied resource
  does not.
- Drift test: `kubectl delete deploy whoami` and Flux restored it on the next
  reconcile. `https://whoami.vteng.io` returned to HTTP 200.

### Running flux by hand

`flux` needs a kubeconfig, and `sudo` drops the `KUBECONFIG` environment
variable, so `sudo flux ...` silently talks to `localhost:8080` and fails. Run it
as your own user — the kubeconfig is world-readable.

## Monitoring

`kube-prometheus-stack`, pinned to 88.5.0 and installed as a `HelmRelease` —
which is what made `helm-controller` necessary. There is no sensible
plain-manifest equivalent: the chart is the Prometheus operator, its CRDs,
node-exporter, kube-state-metrics, and a few dozen dashboards.

| Component | What it gives you |
|---|---|
| Prometheus | 15d of metrics, scraped from the cluster and the node |
| Grafana | `grafana.vteng.io`, through the tunnel |
| node-exporter | the box itself — CPU, memory, disk, load |
| kube-state-metrics | object state — restarts, phases, PVC usage |

Both Prometheus and Grafana carry `nodeSelector: chuggy.dev/durable=true`. They
hold `local-path` volumes and so are pinned to this box regardless; saying it
out loud is the habit that keeps stateful work off spot agents later.

**The Grafana admin credential is not in this repo**, the same rule as the
cloudflared tunnel secret. It is a Secret created out of band:

    kubectl create secret generic grafana-admin -n monitoring \
      --from-literal=admin-user=admin --from-literal=admin-password=<pw>

Without `admin.existingSecret` the chart falls back to the well-known default
`prom-operator`, which on a publicly reachable Grafana is the same as no
password at all. Anonymous access and sign-up are both off, so that credential
is the whole of the auth surface.

`server.root_url` is set to the public address. Without it Grafana builds
redirect and share links from the in-cluster address, and they break the moment
you follow one.

### Control-plane targets are switched off

`kubeControllerManager`, `kubeScheduler`, `kubeEtcd`, and `kubeProxy` are all
disabled. k3s runs the control plane as a single process, so none of them has a
separately scrapeable endpoint. Left enabled they become targets that are
permanently down and alerts that never clear — and an alert you have learned to
ignore is worse than no alert.

### Alerts evaluate, and go nowhere

Alertmanager is disabled and `notification-controller` is not installed. The
rules still evaluate and still show as firing in the Prometheus UI; there is
simply nothing to route them to.

Two alerts therefore fire permanently: `Watchdog`, which is designed to, and
`PrometheusNotConnectedToAlertmanagers`, which is the stack correctly noticing
the above. **Both are expected. Anything else firing is real.**

What this costs is worth naming: monitoring here is pull-only. Nothing pages,
nothing mails, nothing posts to a channel — you find out by looking. That is a
fair trade while one person watches one box, and it is the first thing to
revisit when that stops being true.

### The storage numbers are not real

**Know the second sharp edge on `local-path`:** it does not enforce quota. The
[cluster section](#the-cluster) covers what a node-local directory does to
*scheduling*; this is what it does to the *numbers*. A PVC is a directory on the
root filesystem, so the `20Gi` on Prometheus and the `5Gi` on Grafana are what
was requested, not a ceiling.

The tell is that every volume reports the same figure —
`kubelet_volume_stats_used_bytes` reads identically for all four PVCs on this
box, because it is measuring one filesystem four times.

So Prometheus is bounded by `retention: 15d`, not by its claim, and the only
honest storage signal on this node is root disk usage. Watch that. Ignore the
per-volume percentages, and do not write an alert against them.

### Grafana's memory, and the GOMEMLIMIT trap

Grafana runs with a 1Gi limit and a 256Mi request. It arrived at 512Mi and was
OOMKilled on roughly an 18-minute cycle — four restarts in the 35 minutes after
the stack first came up.

**Do not set `GOMEMLIMIT` from `grafana.env`.** The chart already emits it,
wired by `resourceFieldRef` to whatever `resources.limits.memory` says, and
offers no values key to override it. A second one merges by name into a single
entry carrying both `value` and `valueFrom`, which the API server rejects:

    spec.template.spec.containers[2].env[8].valueFrom: Invalid value: "":
    may not be specified when `value` is not empty

Helm cannot patch that, the release stalls on `RetriesExceeded`, and Grafana
stays on the old spec and keeps dying — a fix that ships without taking effect,
which is the worst shape a fix can have. Raise `resources.limits.memory`
instead; the soft ceiling moves with it.

That ceiling was never the problem, though, and the reasoning that first put it
there was wrong. Go paces the heap against the live set rather than growing to
fill the limit, so at 512Mi it was already collecting hard with the heap pressed
against the cap — leaving no room for what the runtime does not account for,
which here is the page cache behind the mmap'd bleve index Grafana 13 keeps at
`GF_UNIFIED_STORAGE_INDEX_PATH`. The cgroup went over on memory Go was never
counting. Raising the limit fixes that; lowering the soft ceiling would have
made it worse.

## The chuggy control plane

Five processes, one per responsibility, all out of one image:

| Workload | Command | Database role | Listens |
|---|---|---|---|
| `chuggy-api` | `src/roots/nativeHttp.ts` | `chuggy_api`, and `chuggy_selector_review` on a second pool | yes, 3000 |
| `chuggy-ticket-service` | `src/roots/ticketService.ts` | `chuggy_ticket_service` | no |
| `chuggy-selector` | `src/roots/selector.ts` | `chuggy_selector_service` | no |
| `chuggy-scheduler` | `src/roots/scheduler.ts` | `chuggy_scheduler` | no |
| `chuggy-finalizer` | `src/roots/finalizer.ts` | `chuggy_finalizer` | no |

Plus `chuggy-migrate-<tag>`, a Job that applies the schema and is named after
the image it applies it from.

The image is `chuggy.invalid/api:<tag>`, which already contains every command —
its Dockerfile copies the whole source tree and sets a default command of the
API alone. The name is the only API-specific thing about it, and renaming it
belongs to the repository that builds it. **The tag is written in six files and
they move together.**

Four of the five open no socket, so they have no probe and no Service. They
report an unmet precondition by name and exit; the kubelet restarts them. A
process that is alive and making no progress is therefore invisible to
Kubernetes, and closing that needs a health listener in chuggy itself.

### Before any of it runs

Six things, none of which a manifest can do, and each argued in the file that
needs it:

1. **Build and import an image** from a chuggy commit carrying
   [kasofsk/chuggy#242](https://github.com/kasofsk/chuggy/pull/242), and set the
   six tags to it. Without that PR there are no login roles for three of the
   processes and no migration command at all.
2. **Create the host directory** the artifact volume binds, owned `1000:1000`.
   Its path is an option of the machine layer.
3. **Synchronize `chuggy-postgres-credentials`** with one key per login role.
   The host generates them; the four keys past `owner-password` and
   `api-password` arrive with #242's roles file.
4. **Create `chuggy-selector` and `chuggy-finalizer-credentials`** by hand — the
   selector's two bearer tokens and the finalizer's git credential. Values never
   go in this repository; it is public.
5. **`GRANT chuggy_selector_review TO chuggy_api_login`.** No migration and no
   roles file does it, and the API refuses to listen without it.
6. **Insert the first recovery epoch.** The table is created empty and the
   scheduler and the finalizer both fence against its newest row.

### What does not work yet, and why

- **The finalizer cannot start.** Its first precondition runs `git --version`,
  and the image's base — `node:26.7.0-trixie-slim` — has no git. Verified by
  running it. The fix is in the Dockerfile, in chuggy's repository.
- **The selector cannot start.** It needs a trusted selector policy service, and
  no server implements that protocol anywhere. Its API token is also a static
  string against an issuer that signs short-lived tokens, so even with a policy
  host it would authenticate for one token lifetime.
- **The scheduler starts and places nothing.** Its credential may read one
  namespace and may not create a pod there. The worker namespace, its RBAC, the
  image allowlist and the resource budgets are the next stage's.

Each of those is a `CouldNotRun` reported by name in the pod's log, which is the
shape this design asks for — but it also means `flux get kustomization apps`
reports NotReady until they clear, because a Deployment that never has an
available replica never passes the `wait`.

### Storage, and what it does and does not survive

Artifacts are a static `PersistentVolume` over a host directory, in a
`chuggy-retained` StorageClass that provisions nothing and reclaims `Retain`.
Deleting the claim leaves the data and leaves the volume `Released`, which an
operator has to clear before it binds again. The finalizer writes it; the API
reads it read-only.

**PostgreSQL is not on that.** `pgdata-postgres-0` is still a dynamically
provisioned `local-path` claim with `Delete` on it, holding live data. Moving it
means stopping the database, copying the data directory, and deleting and
recreating the claim — destructive work on a running rig, and its own change.

Neither claim is proved against a reboot. `Retain` and a host path are the
argument, not the evidence: nothing here has replaced a pod and read the data
back, and nothing has rebooted the box. What would prove it is exactly that —
write through the finalizer, delete the pod, read through the API; then reboot
and repeat.

## Giving someone else access

Two separable questions, and conflating them is the trap: *what may they do*
(authorization) and *how do they reach the API* (transport).

### Deploying is a git question, not a cluster question

Cluster state comes from `cluster/apps/`, so the way to let someone ship
something is a pull request, not a kubeconfig. Flux applies it and the audit
trail is the commit history.

Notice the converse, because it is the part that bites: **kustomize-controller
applies this directory as cluster-admin**, so anyone who can merge to `main` can
grant themselves anything — including by editing `cluster/apps/dev2-access.yaml`.
Branch protection is the real security boundary. RBAC only constrains what they
can do with `kubectl`.

That leaves debugging — logs, describe, exec, port-forward — as the only thing
that genuinely needs API access.

### Why not SSH, and why not a client certificate

Handing over an SSH key grants everything, with no dial to turn:

- `security.sudo.wheelNeedsPassword = false`, so `wheel` is root.
- `/etc/rancher/k3s/k3s.yaml` is mode 0644, so even a user kept out of `wheel`
  reads it.
- That kubeconfig authenticates as `system:admin` in group `system:masters`,
  which the API server special-cases *before* RBAC runs. It cannot be scoped and
  it cannot be revoked without rotating the cluster CA.

Note what this means for `--write-kubeconfig-mode=0644`: its justification is
that geoff is the only human with a shell, which stays true as long as access is
granted the way below. Give anyone a shell and that mode has to drop to 0600
first.

Kubernetes has no user database either — an identity is an x509 CN/O or a token.
Client certs are the usual reflex and the wrong one for a person: **the API
server has no CRL support**, so an issued cert stays valid until the cluster CA
rotates. Deleting a ServiceAccount invalidates every token ever minted for it, at
once. `kubectl create token` caps at 365 days here and re-issuing is cheap, so
prefer a short duration.

### Transport: the mesh, not the tunnel

The API stays off the internet. A peer joins the WireGuard mesh and dials
`10.100.0.1:6443`, which is already on the API certificate's SANs — that is what
`chuggy.k3s.apiSans` was staged for.

The tunnel was the tempting alternative, since it needs no router configuration.
It was rejected: without a Cloudflare Access policy the route is 6443 on the
public internet, and with one, a third party sits in the auth path. See
[What is and is not exposed](#what-is-and-is-not-exposed).

The mesh costs a **UDP 51820 port-forward and dynamic DNS**, which is item 1 of
[Remaining](#remaining) — needed for spot agents regardless, so it is scheduled
work being done early rather than new work.

Two things the router needs, and the second is easy to miss:

- Forward **UDP 51820 only** to the node. Not TCP, nothing else.
- **Reserve the node's DHCP address first.** `192.168.0.114` is a lease, not a
  static address. A forward pointing at an address the node can lose is a
  failure that shows up weeks later as "the mesh stopped working."

### What the roles carry

`cluster/apps/dev2-access.yaml` binds `view` cluster-wide, `edit` in the
`chuggy` namespace, and a two-rule `node-reader`. Landing it in `cluster/apps/`
*is* applying it — there is no separate apply step.

| | `view`, everywhere | `edit`, in `chuggy` |
|---|---|---|
| pod logs | yes | yes |
| exec, port-forward | no | yes |
| secrets | no | **read and write** |
| nodes | `kubectl top` only | — |

`node-reader` exists because `view` grants nodes only under `metrics.k8s.io`, so
`kubectl get nodes` is otherwise denied — a papercut, given it is the first thing
anyone types.

`edit` reading secrets in `chuggy` is the line to be deliberate about. It is what
`edit` means, so anything that must stay private to the cluster operator does not
belong in that namespace.

### Setting it up

1. **Turn `PasswordAuthentication` off, from the console.** Dropping
   `trustedInterfaces` means a mesh peer reaches sshd where before only the LAN
   did. A key is still required, so this is not a hole — but a password prompt
   facing one more network is not worth keeping.
2. Router: DHCP reservation for the node, then forward UDP 51820 to it.
3. They run `wg genkey | tee private.key | wg pubkey` and send the **public** key
   only.
4. Add them to `chuggy.wireguard.peers` with a `/32` from the human range, then
   `nixos-rebuild switch`.
5. Push `cluster/apps/dev2-access.yaml`. Flux applies it within 5 minutes.
6. `kubectl create token dev2 -n chuggy --duration=720h`. Send them that and the
   cluster CA out of `/etc/rancher/k3s/k3s.yaml` — never the kubeconfig itself,
   which carries the `system:masters` client cert.

Their `wg0` points at the node's public endpoint with
`AllowedIPs = 10.100.0.1/32`, and their kubeconfig at `https://10.100.0.1:6443`.
Revoke by deleting the ServiceAccount, removing the peer, or both — the first
kills the credential, the second kills the route.

## Scaling out to spot workers

Not built. What is in place, what it costs, and what remains.

### Why WireGuard, and what it gives up

Tailscale was removed in favour of raw WireGuard: no third-party control plane, no
account to be logged out of, fully declarative, and free. It is the right call for
a small fixed set of machines.

**Be clear about the one real loss.** Tailscale's main value here was NAT
traversal — STUN hole-punching with DERP relays as a fallback — so a box behind a
home router was reachable without touching the router. Raw WireGuard has none of
that, and **k3s agents dial the server**, so the server must be reachable. The GTR
sits behind a TP-Link at `192.168.0.1`. That means:

- **A UDP port-forward of 51820** to the node, configured on the router. Without
  it no cloud agent can establish a tunnel, and there is no relay to fall back on.
- **Dynamic DNS**, because a residential IP is not stable. The agents need a name
  that keeps resolving after the ISP changes the address.

Neither is hard, but both are outside this repo — they live in the router and in
DNS, and nothing here will tell you when they break.

### In place

Firewall opens 6443 (API), 8472/udp (flannel VXLAN) and 51820/udp (WireGuard).
Those are global rules, so they already cover the mesh — `wg0` is deliberately
**not** a trusted interface. It was, on the theory that trusting it kept 6443 and
8472 off the LAN-facing rules; it never did, since those ports are opened
globally either way, and the trust meanwhile exposed every other listening port
on the box to any peer. A peer now gets 22, 6443 and 8472/udp and nothing else.

`10.100.0.1` is already on the API certificate's SANs, so a peer's kubectl
verifies TLS without any per-client certificate work. The durable node is
labelled.

The private key is generated on the host at first activation and never leaves it.
**No key material belongs in this repo** — peers carry public keys only, which are
not secret. This repository is public.

### Remaining

1. **Port-forward UDP 51820 and set up dynamic DNS.** See above.
2. **Get the node token to the cloud side.** It is at
   `/var/lib/rancher/k3s/server/node-token` and is a joining credential — cloud
   provider secret store, or sops-nix/agenix if it must be declared.
3. **Solve peer churn.** NixOS WireGuard peers are declarative, so adding one is a
   rebuild — which does not fit instances that appear and vanish. The pattern that
   does fit: **pre-allocate a pool of worker slots.** Generate N keypairs offline,
   bake the public keys into `chuggy.wireguard.peers` with fixed addresses
   (`10.100.0.10/32` upward), and keep the private keys in the cloud secret store.
   A launching instance claims an unused slot and comes up as an already-known
   peer, with no server rebuild.

   Costs: concurrency is capped at N until you rebuild to raise it, slot claiming
   needs some coordination (an ASG instance index is usually enough), and a
   reclaimed slot reuses a key a previous instance held — fine inside a trust
   boundary you own, but rotate periodically. The escape hatch is
   `wg set wg0 peer ...` at runtime, which works but does not survive a reboot and
   drifts from the declared config.
4. **Taint the spot agents** so only work tolerating eviction lands there. Spot
   instances are reclaimed with roughly two minutes' notice; nothing holding a PVC
   or unreplicated state should be schedulable onto them.

## Adding the second box

1. `nixos-generate-config` on the new machine; copy its
   `hardware-configuration.nix` into `hosts/<name>/`.
2. Copy `hosts/gtr/default.nix`, set the hostname, and **replace the radio
   blacklist** with whatever that machine's Wi-Fi/Bluetooth drivers are —
   `lspci -k` will tell you. Blacklisting `iwlwifi` on a box with a MediaTek card
   silently does nothing.
3. Pick the right `nixos-hardware` modules for its CPU/GPU.
4. Add one entry to `nixosConfigurations` in `flake.nix` (there's a commented
   `dev2` example).

It gets its own cluster. Nothing is shared at runtime — only the config.

## What changed from the original desktop config

The box was a workstation with a root-owned, unversioned `/etc/nixos` that
imported three paths out of `/home/geoff/nixconfig/`, a directory scheduled for
deletion. That coupling is gone — `nixos-hardware` is a pinned flake input.

**Stripped:** X11, xmonad, lightdm + the enso greeter, DisplayLink, PipeWire,
PulseAudio, Bluetooth, CUPS, Noisetorch, Alacritty, the font set, GDK scaling
vars. lightdm is the *display manager* — the graphical login screen that starts X
and hands off to the window manager; the chain was lightdm → X11 → xmonad.
Closure went 11.5 GB → 4.9 GB, 395 packages removed.

**Radios off.** The AX200 is a combo Wi-Fi/Bluetooth card. Disabling the stacks
removes the daemons, but the devices still enumerate and NetworkManager still
wants a supplicant — so `iwlwifi` and `btusb` are blacklisted and
`wpa_supplicant` masked. Gives up wireless as a fallback; acceptable with a second
unused NIC and physical access.

**Firewall cut to what's needed.** Was `[ 2375 22 80 443 ]` plus TCP 4000–5550 and
UDP 24800. Port **2375 is the unauthenticated, unencrypted Docker daemon API** —
nothing was bound to it, so not a live breach, but anything that bound it would
have had root-equivalent access from the LAN. 80/443 had no server, 4000–5550 was
1,551 ports for dev servers dead since 2024, 24800 was Synergy.

**Dropped broken and dead config.** `programs.ssh.extraConfig` set a system-wide
`IdentityFile` of `/home/geoff/.ssh/id_rsa_github`, a file that does not exist.
`cachix.nix` was never in `imports`, so its substituter had never applied.
`networking.extraHosts` mapped `192.168.0.107 nixos` — the box's own hostname
pointing at an IP it no longer held.

**Fixed `NetworkManager-wait-online`.** It failed on every rebuild but never at
boot: the journal shows `Finished` at each real boot and `Failed` only on live
restarts. After a live restart NetworkManager stops re-signalling startup
completion — `nmcli` reports `STARTUP=starting` indefinitely while
`STATE=connected` — so `nm-online -s` times out. It is NM's own flag, not a stuck
device; unmanaging the idle Wi-Fi and cable-less second NIC changed nothing, and
NetworkManager 1.48 has no `--any`. The unit is masked. Note that k3s orders
itself `After=network-online.target`, which now activates immediately rather than
waiting for a real link — k3s restarts on failure, so this is tolerable, but it is
the thing to look at first if k3s ever comes up before the network.

**Added.** `configurationLimit = 10` (/boot hit 96% because nothing capped
generations), weekly `nix.gc` with 30-day retention plus `nix.optimise` (the store
had reached 217 GB), and `nvme-cli`/`smartmontools`, both missing when an SSD
health check was first needed.

**Kept deliberately.** The `geoff` user — it is the SSH path, and removing it
removes the way in — along with `programs.zsh.enable`, without which that user's
login shell breaks. NetworkManager, because it holds the DHCP lease and swapping
to systemd-networkd is a console job. `PasswordAuthentication` at its default;
disabling it is right, but from the console. `system.stateVersion = "23.05"`,
which is frozen at install value by design and must never be bumped to match the
release.
