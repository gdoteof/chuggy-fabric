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
    cluster/apps/                   everything running on the cluster

    hosts/gtr/default.nix           geoff's Beelink GTR: hostname, radios, mesh, k3s, tunnel
    hosts/gtr/hardware-configuration.nix

    nixos-live/                     the original /etc/nixos, captured verbatim

Anything in `modules/` must be true of every node. Anything hardware-specific —
disks, radios, hostname — belongs in `hosts/<name>/`. The Wi-Fi blacklist is the
worked example: `iwlwifi` is correct for the GTR's AX200 and wrong for any box
with a different card, so it lives in the host file.

`nixos-live/` is history, not input. Nothing imports it.

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

    sudo nixos-rebuild switch --flake github:gdoteof/chuggy-fabric#gtr

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

Only `source-controller` and `kustomize-controller` are installed.
`helm-controller` and `notification-controller` are omitted until something needs
them.

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

`cluster/apps/dev2-access.yaml` binds `view` cluster-wide, `edit` in one
namespace, and a two-rule `node-reader`. It is deliberately not committed yet —
landing it in `cluster/apps/` *is* applying it, so it arrives with the peer it is
for, not before.

| | `view`, everywhere | `edit`, their namespace |
|---|---|---|
| pod logs | yes | yes |
| exec, port-forward | no | yes |
| secrets | no | **read and write** |
| nodes | `kubectl top` only | — |

`node-reader` exists because `view` grants nodes only under `metrics.k8s.io`, so
`kubectl get nodes` is otherwise denied — a papercut, given it is the first thing
anyone types.

`edit` reading secrets in their namespace is the line to be deliberate about. It
is what `edit` means; pick the namespace accordingly.

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
6. `kubectl create token dev2 -n dev2 --duration=720h`. Send them that and the
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
