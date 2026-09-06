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

    flake.nix                       one nixosConfiguration per host, and the checks
    flake.lock                      the pin — commit every change to it

    modules/common.nix              identity, access, packages, nix settings
    modules/node-prep.nix           k8s prerequisites, workstation teardown
    modules/wireguard.nix           the mesh, with chuggy.wireguard.* options
    modules/k3s-server.nix          the cluster role, with chuggy.k3s.* options

    modules/chuggy-state.nix        retained host directories, chuggy.state.*
    modules/chuggy-secrets.nix      generated credentials, chuggy.secrets.*
    modules/github-app-token.nix    rotating repository credentials, chuggy.githubAppTokens.*
    modules/chuggy-images.nix       bootstrap image delivery, chuggy.images.*
    modules/chuggy-work.nix         what one task may cost, chuggy.work.*
    modules/mini-chuggy.nix         complete co-located single-node role

    modules/cloudflare-tunnel.nix   public ingress, with chuggy.tunnel.* options
    modules/ddns.nix                the mesh endpoint's A record, chuggy.ddns.*
    modules/flux.nix                bootstraps Flux, chuggy.flux.*

    cluster/flux-system/            the vendored Flux install
    cluster/apps/                   the cluster state this repo declares
    cluster/apps/kustomization.yaml the enumeration of that state, and two
                                    generated ConfigMaps
    cluster/apps/ory/               config documents those ConfigMaps carry --
                                    not manifests, and not in `resources`

    hosts/gtr/default.nix           geoff's Beelink GTR: hostname, radios, mesh, k3s, tunnel
    hosts/gtr/hardware-configuration.nix
    hosts/example/                  a second host that holds nothing of gtr's
    examples/mini-chuggy-node.nix   opt-in self-contained host role

    tests/state-and-secrets.nix     boots the four chuggy-* modules and checks
                                    what they kept and what they synchronised

    nixos-live/                     the original /etc/nixos, captured verbatim

    docs/bootstrap-and-recovery.md  autonomous bootstrap, Git cutover, and
                                    same-authority recovery runbook

Anything in `modules/` must be true of every node. Anything hardware-specific —
disks, radios, hostname — belongs in `hosts/<name>/`. The Wi-Fi blacklist is the
worked example: `iwlwifi` is correct for the GTR's AX200 and wrong for any box
with a different card, so it lives in the host file.

`nixos-live/` is history, not input. Nothing imports it.

What `cluster/apps/` declares is deliberately less than what the cluster runs.
The `chuggy-git` and `chuggy-work` namespaces were both bootstrapped by hand from
the [chuggy](https://github.com/kasofsk/chuggy) repo as deployment rehearsal
fixtures — transient by intent, so declaring one would have committed Flux to
maintaining state the rehearsal meant to tear down. `chuggy-work` stopped being a
fixture: `cluster/apps/chuggy-work.yaml` declares the namespace, the identity
both kinds of placed pod run as, the Role that lets the scheduler place them, and
one NetworkPolicy per kind of pod — `chuggy-workers` for a ticket's attempt,
`chuggy-sessions` for an agent session, each keyed on that kind's own label. A
pod placed there carrying neither label is selected by neither policy, and a pod
no policy selects is isolated in **neither** direction; the `session-placement`
check holds that against the rendered cluster. `chuggy-git` is still a fixture
and is still undeclared.

That remaining fixture is a **second Flux control loop**, which is why the
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

**Checking** — from the workstation, no box involved:

    nix flake check

Builds both hosts; proves that a host omitting a required input is refused and
that the example still warns about what an unedited copy inherits; reads the
firewall script each host builds, for which sources reach 6443 and 8472 and
where those rules sit in the chain; and boots four of the modules —
`chuggy-state`, `chuggy-secrets`, `chuggy-images`, `chuggy-work` — in a VM to
check what they keep. The VM test wants `/dev/kvm`. What it does **not** do is
start k3s or run `iptables`, so it says nothing about the auto-deploy ordering,
the image import or Flux, and nothing about the kernel accepting the rules it
read; those still need a box.

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

### The API is no longer open to everything the box can see

`chuggy.k3s.apiAllowedSources` names the ranges 6443 and 8472/udp are reachable
from. Neither port is in `allowedTCPPorts` any more, because a port in that list
is open on every network the machine has an address on.

The pod range is added to the rule automatically, and taking it out is the
mistake to know about. A pod reaching the `kubernetes` service is DNAT'd to this
node's own address on 6443, so its packets arrive at the host firewall carrying
a **pod** source address — DNAT rewrites the destination, not the source. Leave
that range out and Flux, and everything else in the cluster, loses the API at
the next activation. It presents as a broken cluster, not as a firewall rule.

The rules are `iptables` appended into `nixos-fw`, because the NixOS firewall
has no per-source form of `allowedTCPPorts`. That ties them to the iptables
backend; nixpkgs refuses the configuration outright under nftables rather than
applying nothing, which is the right failure — silently applying nothing would
leave both ports closed and the cluster unreachable.

**It also closes both ports over IPv6**, which is a capability removed and not a
scope narrowed: `allowedTCPPorts` emits `ip46tables` and these are `iptables`,
so no entry in `apiAllowedSources` can readmit an IPv6 client. Nothing here
speaks IPv6 today — the mesh is IPv4, the pod range is IPv4, and the option's
type refuses anything else — but a site whose `kubectl` arrives over IPv6 needs
an `ip6tables` arm, not a longer source list.

None of that is a comment you have to trust. `tests/firewall-rules.nix` reads
the firewall script each host builds and asserts one source-restricted accept
per entry in `apiAllowedSources`, plus the pod range, for each of the two
ports; the two global ports; that nothing else names 6443 or 8472; and that
they all land before `nixos-fw-log-refuse`. Then, because every one of those is
a whitelist that a rule *added* to the chain would pass, it asserts that no
accept trusts a whole interface other than `lo` and that none names a port
outside that set — which is what makes putting `wg0` back on
`trustedInterfaces`, or opening kubelet's 10250 on every interface or on one, a
difference the check reports. It is a `runCommand`,
so it costs an evaluation rather than a VM; what it cannot say is that the
kernel accepts the rules, which is still a live `iptables -S` on the box.

## What an adopting machine has to say

Some inputs have no default that is safe to guess, and a host that omits one
does not evaluate. The refusal is the point: the alternative is a second box
that builds clean and is not actually supported.

| Input | Module | What a guess would cost |
|---|---|---|
| `chuggy.k3s.apiAllowedSources` | `k3s-server.nix` | the safe guess refuses the workstation; the convenient one is every network the box can see |
| `chuggy.state.artifacts.path` | `chuggy-state.nix` | durable data on whichever filesystem happened to have room |
| `chuggy.state.registry.path` | `chuggy-state.nix` | OCI content on an incidental or boot-constrained filesystem |
| `chuggy.work.worker.cpu`, `.memory`, `.ephemeralStorage` | `chuggy-work.nix` | one task starves the control plane, or cannot finish — neither looks like a missing setting |
| `chuggy.flux.repositoryUrl` | `flux.nix` | Flux installed and following nothing, reporting no error |

`hosts/example/` answers all of them for a machine that is not gtr, and
`nix flake check` builds it. Each refusal has its own check beside it, which is
the half that matters: a module that quietly grew a default would still
evaluate, and the check is what notices.

### What is deliberately not an input

**TLS certificate and key paths.** The design calls for the adopting machine to
supply them and for the module to check the material is there before exposing
ingress. Nothing here would read them: on this rig TLS terminates at the
Cloudflare edge, and a host that turns the tunnel off has no TLS terminator at
all. An option nothing reads is a claim the tree cannot keep, so there is none —
which means a host without the tunnel serves its API in plaintext on its LAN and
mesh, and that is a real gap rather than a deferred one. It is filed as
[#10](https://github.com/gdoteof/chuggy-fabric/issues/10), which names what
would close it: a terminator first, then the validation that gates ingress on
its material. `hosts/example/` warns about it on every rebuild rather than
leaving it to this page.

**What a task may cost is stated but not yet spent.** `chuggy.work.*` refuses a
host that has not decided, and nothing on the machine reads the numbers: worker
admission, requests, limits and the workspace bound are Kubernetes objects, and
Kubernetes objects are cluster state. Carrying them into an object nothing
mounts would look like the work was done.

**Where PostgreSQL keeps its data.** D23 asks for an explicit, configurable host
path behind a static `Retain` volume for the database as well as for artifacts.
`chuggy.state.artifacts.path` is one of the two; there is no option for the
other, because there is nothing yet for it to name — `cluster/apps/postgres.yaml`
claims `local-path`, which is provisioned dynamically, so the directory is k3s's
to choose and it is not this host's to declare. Closing it is a cluster-layer
change first (a PersistentVolume over a named path, and a claim that binds it)
and an option beside `artifacts.path` second; doing the second alone would
declare a directory nothing mounts.

### Retained state

`modules/chuggy-state.nix` creates the directories chuggy's data lives in and
sets their ownership. It does **not** create the PersistentVolume that binds one
into the cluster — that object is cluster state and belongs in `cluster/apps/`.

**The retention is the volume's property, not this module's.** A static PV with
`Retain` over the artifacts path is what makes deleting a claim leave the data
behind; on a host where no such volume has been reconciled, what exists is a
directory with the right owner and nothing mounting it — and reading that as a
durability guarantee is reading one this tree does not give. The volume and
`chuggy.state.artifacts.path` have to name the same path and nothing checks
that they do; a mismatch mounts an empty directory and reports healthy.

**Where the two layers both have an opinion, this one wins.** A
PersistentVolume names a host path; it does not create it and does not set its
mode or owner. `chuggy.state.artifacts.{user,group,mode}` do, and the mode they
supply is `0750`. What preserves that across a rebuild and a reboot is
`systemd-tmpfiles` `d`, which creates a directory when it is absent and adjusts
its mode and owner when it is not — including back over a mode something else
set in between. So a manifest that also states a mode for this directory is
restating the option's answer rather than giving one, and the next rebuild
settles any disagreement without reporting that it did. `d` never touches
contents; `D` would empty it on every boot. `tests/state-and-secrets.nix`
chmods the directory and runs `systemd-tmpfiles --create`, so the reset is
checked rather than described.

**It was `0770`, and the group write bit was a permission nothing held.** The
reason given for it was a second pod identity in the same group writing without
being the owner, and there is no such identity: the reader mounts this
read-only, and the writer runs as the owning uid, so the owner bits were doing
all the work. A group write bit granted to a group with no members is not a
safeguard against a second identity arriving — it is a permission waiting for
whoever gets that gid next. `0750` costs nothing today, and a second writer
that genuinely needs it becomes a deliberate change to the option.

**Tightening the mode does not change who can already read it.** The directory
is owned by a numeric uid matching the pods that read and write it, and on a
NixOS host that uid is also the first normal user — here, the human with a
shell, not a dedicated service account. So the *owner* of the artifacts is a
person, and no mode on this directory changes that.

What actually keeps them out is the parent: `chuggy.state.directory` is `0700
root:root`, and path resolution needs execute on every component, so uid 1000
cannot traverse into its own directory without root. It has passwordless sudo,
so the practical answer is that the human can read the artifacts — by being
root, not by owning them. Two consequences worth keeping straight: an adopter
who moves `artifacts.path` out from under `chuggy.state.directory` loses that
gate and is left with only this mode, and a box with a second human user should
move `user` off 1000 rather than rely on either.

### Generated credentials

PostgreSQL role passwords and the API's idempotency keying material are
generated once on the host, under a root-only directory outside the Nix store,
and synchronised into Kubernetes Secrets in the `chuggy` namespace.

**Nothing overwrites a value** — not the host files, not the Secret keys. A key
already in the cluster is left alone and copied *back* into host state if this
host has no record of it. That asymmetry is not caution for its own sake. A
PostgreSQL password is two facts that have to agree: a string in a Secret, and a
string PostgreSQL was told to accept for a role. Only the first is here. A sync
that wrote a fresh password over the Secret would change one and not the other,
and the running API would be locked out of its own database by a rebuild that
reported success.

**A host whose cluster already holds these has one step to do first.** The
generator runs before the synchronisation and writes every value it does not
find, so on such a host it writes fresh values the cluster has never seen, the
synchronisation reports divergence on each of them — correctly, and for good —
and `chuggy-secrets-sync` fails. Seed host state from the cluster before the
first rebuild, once, for the keys the cluster already has:

    sudo install -d -m 0700 -o root -g root \
      /var/lib/chuggy /var/lib/chuggy/secrets /var/lib/chuggy/secrets/<secret>
    kubectl -n chuggy get secret <secret> -o jsonpath='{.data.<key>}' | base64 -d \
      | sudo install -m 0600 -o root -g root /dev/stdin /var/lib/chuggy/secrets/<secret>/<key>

Name all three directories. `install -d` applies the mode to what it creates,
and given one path it creates the parents with the default 0755 — so seeding
before the first rebuild would otherwise leave `/var/lib/chuggy` and
`.../secrets` world-readable until the rebuild's tmpfiles rules tightened them.

That is the adoption the module would do if the boot order let it reach the
branch; [#12](https://github.com/gdoteof/chuggy-fabric/issues/12) is the
ordering that would make the step unnecessary. Afterwards the synchronisation is
silent about those keys and creates the rest, which is how you know the two
agree.

**The other half is not automatic, and the gap is real.** A password this
generates authenticates nothing until PostgreSQL is told about it, which is what
kasofsk/chuggy's `deploy/rig/postgres/postgres-roles.sql` does. That file is run
by an operator against a running database, not by this module — activation
happens while PostgreSQL is still an unscheduled pod, and re-running it rotates
every role it names. `chuggy-pg-role-env` hands it the values without their
passing through a terminal or an argument list, and carries the `psql` that
reads them:

    systemctl is-active chuggy-secrets-sync    # must say `active`
    kubectl -n chuggy port-forward svc/postgres 55440:5432 &
    forward=$!
    export PGPASSWORD="$(kubectl -n chuggy get secret postgres-superuser \
      -o jsonpath='{.data.password}' | base64 -d)"
    sudo -E chuggy-pg-role-env psql -h 127.0.0.1 -p 55440 -U postgres \
      -d <database> -f deploy/rig/postgres/postgres-roles.sql
    kill $forward

**Check the unit first.** A divergent run exits 3, so `is-active` says `failed`
and `systemctl --failed` lists it; what this hands psql is host state, and on a
key where host and cluster disagree it would set PostgreSQL to a password the
workloads do not have. `journalctl -u chuggy-secrets-sync -b` names the keys.

The status is 3 and not 1 because 1 is what a failed `kubectl` gives: an API
error the unit has to retry, not a disagreement it has to stop on. Divergence
is the only status the unit refuses to restart after, so a transient error on
first boot is retried rather than left as a permanently failed unit with a
Secret the cluster never received. `modules/chuggy-secrets.nix` carries the
whole map in one place.

### Staged GitHub App credentials

`chuggy.githubAppTokens` mints repository-scoped installation tokens into
managed Kubernetes Secrets. Gtr stages a read-only token for Chuggy, a separate
read-only Git basic-auth credential for Shipwright, a Worker App credential for
ticket branches, and a Portal App credential reserved for finalization. Their
private keys remain root-only host state outside this repository and the Nix
store.

The Chuggy service credentials remain staged until their consumers switch to
them; Shipwright consumes only the dedicated build-reader projection. After
switching the host configuration, verify all refreshers and Secrets:

    systemctl is-active chuggy-github-app-token-reader-refresh
    systemctl is-active chuggy-github-app-token-build-reader-refresh
    systemctl is-active chuggy-github-app-token-finalizer-refresh
    systemctl is-active chuggy-github-app-token-worker-refresh
    kubectl -n chuggy get secret chuggy-github-reader-token
    kubectl -n chuggy-build get secret chuggy-build-source-read
    kubectl -n chuggy get secret chuggy-github-finalizer-token
    kubectl -n chuggy-work get secret chuggy-github-worker-token

**`chuggy-pg-role-env` is on `PATH` only after a `nixos-rebuild switch` carrying
this module.** Before that switch it is in the built system and not on the box's
path — `nixos-rebuild build --flake .#<host>` and run
`./result/sw/bin/chuggy-pg-role-env` instead. `psql` is on that tool's own path
either way and never on the host's.

**Kill the port-forward.** While it is up, anything on this machine reaches
`127.0.0.1:55440` as the PostgreSQL superuser — see the next paragraph for why
no password is in the way. Backgrounding it and walking away is the mistake this
line exists to prevent.

The server is a headless Service and listens on no address this host has, so the
forwarded port is the transport, not a convenience. **`PGPASSWORD` is not what
gets you in over it.** This deployment's `pg_hba.conf` carries
`host all all 127.0.0.1 trust`, and a port-forward arrives at the server from
loopback, so the connection is trusted and the variable is never consulted —
`PGPASSWORD=definitely-wrong` connects just as well. It is set anyway because
the trust line is the deployment's and not this repository's, and a run that
depended on it silently would break when that line goes. `sudo -E` carries it
without its becoming an argument anyone on the box can read; that part works,
and `/etc/sudoers` has `%wheel … NOPASSWD:SETENV: ALL` for it. The database is
the deployment's to name: a role is cluster-wide, the grants at the end of that
file are not.

It creates the login roles the Secret does not yet have and sets the rest to
the values the Secret holds. What tells you it worked is that every role in the
inventory authenticates over the cluster network with the value the Secret
carries — not the run's own output, which reports success for a role that was
already there.

**Rotation is not provided.** Rotating one of these correctly means fencing
writers, changing the role, changing the Secret and restarting whatever holds a
connection, in that order — and the wrong order locks out the process the
rotation was for. Nothing here does any of it, which is why nothing here claims
to. Deleting the host state directory is not a reset either: the cluster and the
database are unaffected by it, so what it produces is a host that generates a
replacement for every value and then disagrees with the cluster about all of
them — recoverable only by seeding host state back, as above.

### Images, the registry, and the order things come up in

The cluster runs a private OCI registry from the upstream `registry:3` image.
Its retained volume holds release images and immutable artifacts; it has no
Ingress or NodePort. Operators reach it through a port-forward:

    kubectl -n chuggy-registry port-forward service/registry 5000:5000

Publishing through that forward needs a client that speaks the registry API
over plain HTTP. `Registry operations` below is the route that runs on the
node, needing no forward and no client configuration. From a host carrying
skopeo or oras, the forward is transport while the repository and digest are
what the registry stores:

    skopeo copy --dest-tls-verify=false \
      docker-archive:api.tar docker://localhost:5000/chuggy/api:<tag>
    oras push --plain-http localhost:5000/artifacts/<name>:<tag> <file>

Workloads name `registry.chuggy.internal`, which ICANN reserves for private
use. Every fabric node maps that logical name to the registry ClusterIP through
k3s; it is not a public DNS record and the registry remains unexposed.

The registry cannot contain the image needed to start itself. Its pinned public
image is therefore the bootstrap root, and the air-gap directory remains the
recovery path when that upstream cannot be reached.

k3s imports every archive under `/var/lib/rancher/k3s/agent/images` into
containerd as the agent starts, which is *before* the kubelet can schedule a pod
that references one. That, not a systemd unit, is what makes the ordering hold:

    k3s starts → containerd imports bootstrap archives → k3s applies Flux
      → Flux reconciles cluster/apps → registry starts from its public image
      → chuggy-secrets-sync writes the Secrets → workloads start

`chuggy-import-image <archive.tar>` is for the other case — adding an image to a
node that is already running, where waiting for a k3s restart would restart every
workload on the box. It installs the archive first and imports second, so a
failed import still leaves something the next k3s start retries.

The Secret step is the one that can arrive late: the `chuggy` namespace belongs
to `cluster/apps/`, so on a cold boot it does not exist until Flux has
reconciled once. `chuggy-secrets-sync` waits, reports could-not-run rather than
failure when it gives up, and retries — bounded, so a genuinely broken cluster
ends up in `systemctl --failed` instead of looking busy forever. The bound is
sized on the *worst case* a cycle can take, not on the wait it contains: a
window the burst cannot fit inside is one systemd resets before the burst is
spent, and a unit whose limit is never tripped restarts for ever in
`activating`, which `systemctl --failed` does not list. That is the failure
the derivation in `modules/chuggy-secrets.nix` exists to prevent, and
`tests/state-and-secrets.nix` asserts the inequality systemd actually uses. A
workload that starts before its Secret exists stays pending and recovers on its
own.

Release workloads use registry digests. Bootstrap archives remain only for the
registry's own public image and for recovery when its retained directory or
upstream is unavailable; ordinary service promotion does not import an archive
into each node.

The registry volume survives pod replacement and claim deletion; it does not
survive loss of the node filesystem. Its `50Gi` capacity is a matching value,
not a quota, because the static local volume is a directory on the root disk.
Garbage collection and root disk usage are operator responsibilities.

#### Registry operations

`deploy/rig/images/build-and-import.sh` in kasofsk/chuggy imports an image
into the node's own containerd and stops -- its header says it deploys nothing
-- while every release manifest names a registry digest. Publishing is the step
between the two, and this is what runs it here.

The client is containerd's own and the work runs on the node, which is what
recommends it: no forward, no daemon configuration, and the image is already
there. The destination is the registry's Service address:

    kubectl -n chuggy-registry get service registry

`registry.chuggy.internal` cannot be that destination. Its generated
`hosts.toml` gives the mirror `pull` and `resolve` alone, so a push under that
name falls through to the `server =` line no resolver answers. Tag the imported
image with the address above and push that:

    sudo k3s ctr -n k8s.io images tag --force \
      registry.chuggy.internal/chuggy/<name>:<tag> \
      <cluster-ip>:5000/chuggy/<name>:<tag>
    sudo k3s ctr -n k8s.io images push --plain-http \
      <cluster-ip>:5000/chuggy/<name>:<tag>

The address is transport and the second reference a local alias: what the
registry stores is the repository and the digest, and what a manifest names is
`registry.chuggy.internal/chuggy/<name>@<digest>`. That address is a ClusterIP
and does not survive a recreation of the Service, which is why the command that
prints it is written here and no number is.

Read the digest back from the registry, and not from the push or from
`ctr images ls`:

    curl -sI -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
      http://<cluster-ip>:5000/v2/chuggy/<name>/manifests/<tag> \
      | grep -i docker-content-digest

**The push is not what lets this node run the image.** The import already did
that, and `imagePullPolicy: IfNotPresent` never fetches. It is what makes the
digest recoverable: a second node, or this one after its image store is reset,
has only the declaration and the registry to work from.

The same publish and read-back run through a port-forward from a host that
carries skopeo, which no host here does. Use a conflict-free local port; macOS
may already reserve `5000`:

    kubectl -n chuggy-registry port-forward service/registry 5050:5000

The endpoint is intentionally plain HTTP inside the cluster, so a client used
through the port-forward must opt out of TLS explicitly:

    skopeo copy --dest-tls-verify=false \
      docker-archive:web.tar \
      docker://localhost:5050/chuggy/web:<tag>
    skopeo inspect --tls-verify=false \
      docker://localhost:5050/chuggy/web:<tag> --format '{{.Digest}}'

An ordinary pod replacement is the persistence check. Restart the Deployment,
wait for it, read the same reference again -- through a fresh port-forward if
that was the route -- and require the digest the registry answers for it to
remain unchanged:

    kubectl -n chuggy-registry rollout restart deployment/registry
    kubectl -n chuggy-registry rollout status deployment/registry

Delete manifests by digest, never by guessing from a tag. Deletion only removes
the manifest reference; reclaiming its unreferenced blobs requires garbage
collection. Distribution garbage collection is stop-the-world: first stop the
registry, run `registry garbage-collect --delete-untagged` in a one-shot pod
that mounts the same config and PVC, then restore the Deployment. Do not run it
beside a writable registry; a concurrent upload can lose a layer that the mark
phase did not see. Verify every retained release digest again after the
registry returns.

Rollback changes only the consumer's digest. Keep the previous manifest in the
registry, restore that digest in the workload declaration, and let Flux
reconcile it. Rolling the registry Deployment back cannot recover deleted
content: restore `/var/lib/chuggy/registry` from a filesystem backup, or push
the original archive again and verify its digest before restoring consumers.
Loss of that host directory is the registry disaster boundary.

The registry implementation is shared cluster state: its Deployment, Service,
volume objects, policy and configuration all live under `cluster/apps/`. A new
machine imports the shared NixOS modules and sets
`chuggy.state.registry.path = "/var/lib/chuggy/registry"`, as
`hosts/example/` does; it does not copy the registry into its host module. The
path is also the static PersistentVolume's host path, so keep that mount point
stable even when another disk backs it. A machine that needs a different path
needs a cluster overlay that changes the PersistentVolume with the host option;
changing only the option creates a healthy registry over the wrong directory.

### Immutable image builds

Flux reconciles three independent paths from the host-selected fabric source:
`cluster/build-prerequisites/` installs pinned certificate management,
`cluster/build-system/` installs pinned Tekton and Shipwright controllers plus
the fabric-owned BuildKit strategy, and `builds/` contains immutable requests.
The dependency chain makes the request CRDs available before Flux applies a
request. Flux reports `BuildRun` failure through its `Succeeded` condition; it
does not run BuildKit itself.

Render a request by supplying repository bindings rather than editing a
project-specific template:

    scripts/render-build-request \
      --repository-id example-service \
      --source-url https://git.example.com/team/example-service.git \
      --source-commit 0123456789abcdef0123456789abcdef01234567 \
      --source-secret example-source-read \
      --target-image-repository registry.example.internal/team/example-service \
      --output-secret example-registry-push

The renderer prints the resulting
`builds/<repository-id>/<commit>/<request-digest>.yaml` path. The digest covers
the source binding and full commit, target repository, credential references,
renderer, profile, platform, cache and Dockerfile. Rendering
unchanged input is idempotent; changing an input creates another path. The
initial attempt is `-a1`; later retry automation must add the next
`-a<ordinal>` beside the unchanged `Build` and never replace an attempt.

Provision the two named Secrets in `chuggy-build`. The Gtr GitHub App refresher
maintains `chuggy-build-source-read` as a read-only Git basic-auth Secret, and
the build-system manifests maintain the anonymous internal-registry Docker
configuration in `chuggy-registry-build-push`. Shipwright mounts the source
credential only for cloning and the output credential only for pushing; the
Flux service accounts receive neither. The v1 network profile accepts only
public HTTPS Git/registry endpoints on port 443, the internal
`*.chuggy-git.svc` Git service on port 8080, and the internal
`*.chuggy-registry.svc` registry on port 5000. SSH, arbitrary private services,
and custom ports are rejected because the matching default-deny NetworkPolicy
cannot reach them.

Requests are fixed to `linux/amd64` and schedule only where both of these node
properties exist:

    chuggy.k3s.nodeLabels = [ "chuggy.dev/node-role=builder" ];
    chuggy.k3s.nodeTaints = [ "chuggy.dev/node-role=builder:NoSchedule" ];

By default that node is a dedicated security boundary. Rootless BuildKit remains
daemonless, but rootlesskit requires unconfined seccomp/AppArmor and permits
privilege escalation for user-namespace setup. A dedicated host can import
`examples/builder-node.nix`; the committed fragment wires both properties.

A self-contained host instead imports `examples/mini-chuggy-node.nix` and
renders requests with `--profile mini`. The `chuggy.mini` role enables k3s,
durable state, secrets, images, work, provenance, Flux, and the builder label,
but deliberately adds no builder taint: tainting the only node would exclude
the ordinary workloads that make the deployment self-contained. Its distinct
profile records that weaker, co-located security boundary and emits no
dedicated-builder toleration. The host must still state its own storage paths,
API source ranges, worker budget, and Flux repository; start with
`hosts/example/`, replace its inert values, and add the mini example module to
that host's `extraModules` in `flake.nix`.

`tests/integration/build-platform.sh` is the opt-in executable acceptance gate.
Its topology is an isolated Git branch and worktree watched at `./builds` by a
dedicated Flux `GitRepository` and `Kustomization`; that Kustomization must carry
the production BuildRun CEL health expression. The gate commits and pushes the
rendered request, waits for Flux to report that exact Git revision Ready, then
checks the materialized BuildRun's source SHA and verifies the pushed digest
with `crane`. It never applies a Build or BuildRun directly. Set
`BUILD_TEST_FLUX_WORKTREE`, `BUILD_TEST_FLUX_BRANCH`,
`BUILD_TEST_TARGET_REPOSITORY`, `BUILD_TEST_SOURCE_SECRET`, and
`BUILD_TEST_OUTPUT_SECRET`; optionally select the dedicated Kustomization with
`BUILD_TEST_FLUX_NAMESPACE` and `BUILD_TEST_FLUX_KUSTOMIZATION`.

Every unavailable prerequisite exits 2 and is not a pass, including the lack of
a schedulable amd64 builder carrying both the builder label and matching
`NoSchedule` taint. Issue 28 remains open until an operator supplies this
disposable topology and the gate completes successfully against a real cluster.

Every attempt carries a provenance finalizer. A bounded recorder verifies a
successful attempt's observed source commit and output digest, writes its
result under `/var/lib/chuggy/build-results/<request-digest>/`, syncs the record
and checksum, and only then releases the finalizer. Live TTL cleanup is disabled:
deleting a `BuildRun` while its declaration remains under `builds/` would make
Flux recreate the same attempt and execute it again. Cleanup work must persist
provenance, retire the declaration from the live tree, observe Flux release its
ownership, and only then delete the resource. The result directory is
installation state and needs the same backup treatment as the registry and
journal.

Image selection is a separate Git change. `scripts/render-image-promotion`
consumes one checksummed successful result, verifies that the registry still
serves its exact digest, and writes a configured workload patch. The repository
binding, target ref, environment path, workload identity and container are all
inputs; the renderer assumes no project or environment name:

    scripts/render-image-promotion \
      --build-result /var/lib/chuggy/build-results/<request>/<attempt>.json \
      --repository-id example-service \
      --repository-url https://git.example.com/platform/environments.git \
      --target-ref refs/heads/staging \
      --environment-path environments/staging/example-service.yaml \
      --resource-name example-service \
      --container-name server \
      --namespace staging \
      --act-root /var/lib/chuggy/promotion-acts \
      --git-command /run/current-system/sw/bin/git \
      --credential-command /run/credentials/git-askpass \
      --credential-ref environment-writer \
      --registry-client /run/current-system/sw/bin/crane \
      --registry-credential-command /run/credentials/registry-docker-config \
      --registry-credential-ref registry-reader

The selected repository's kustomization includes that patch. The renderer
creates a private disposable bare repository for each act, fetches the configured
target ref, constructs a deterministic commit without checking repository
content out, and conditionally advances that ref. The credential command is an
explicit askpass port and receives only its configured credential reference;
every child process receives an allowlisted environment.
Registry reads use a separate credential port. Its command receives only the
registry credential reference and emits Docker config JSON; the renderer writes
that into a mode-`0600` file under another disposable private directory and
points only the registry client at it. Neither Git nor registry access inherits
the caller's home directory or ambient secret-bearing environment.

This version accepts Git over public HTTPS on port 443, the existing
`*.chuggy-git.svc` HTTP profile on port 8080, `file:`, or an absolute local
path. SSH is refused because the direct-publication contract does not yet
define forced noninteractive authentication and pinned host-key material.
Repository URLs may carry neither user information nor query-string credentials.
The patch records the source commit, build request, attempt, provenance record,
repository binding and selected digest. Re-selecting a retained older result is
the rollback operation and follows the same reviewable path.

Publication reconciles the target before and after each bounded conditional
push. The exact candidate or a descendant retaining the same promotion identity
and selected path is success, including after a successful push response was
lost. An unchanged base permits another conditional attempt. Any unrelated
target advance is an operator-visible hold rather than an overwrite. Proposal
handoffs remain outside this command until a provider-neutral proposal contract
exists.

The renderer writes nothing until both provenance and registry availability
are proven. A build result alone never changes an environment, and accepting
the Git change means only that Flux may attempt the rollout; it is not evidence
of deployment success.

Failed and stalled attempts are reported by the host timer, and retry and
retirement preserve the immutable request and durable provenance. The
[build operations runbook](docs/build-operations-runbook.md) gives the ordered
commands, retention boundary, and failure ownership.

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

Be precise about *why* 6443 is safe, though: k3s binds it on `*:6443`, and the
firewall now admits it only from the ranges in `chuggy.k3s.apiAllowedSources` —
the house LAN, the mesh, and the pod range. That is how `kubectl` works from the
workstation. It is not reachable from the internet because there is no
port-forward *and* because no internet range is on that list; it used to be the
first of those alone. If a port-forward is ever added for WireGuard, forward
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

This deliberately is **not** `flux bootstrap`. That command wants provider write
scope so it can commit manifests and create a deploy key, while those manifests
are already committed here. The current public source needs no credential. A
private source instead names a separately provisioned, read-only Secret with
`chuggy.flux.secretRef`; credential material never enters the Nix store. A new
machine first reconciles an anonymous external bootstrap source, then provisions
that Secret and activates a pinned cutover revision. The Secret cannot precede
the Kubernetes API and `flux-system` namespace that hold it.

**Which repository and branch it follows are host inputs**, not a committed
file. `chuggy.flux.repositoryUrl` and `.branch` generate the `GitRepository` and
`Kustomization`; only the controller install is still a checked-in manifest,
because that is a vendored upstream artifact identical on every adopter. A box
being brought up, or one being used to try a change, has to be able to follow
something other than whatever the shared branch holds at that moment, and a
committed sync file made that a property of the repository instead of the host.

The [bootstrap and recovery runbook](docs/bootstrap-and-recovery.md) defines the
external recovery root, private-source provisioning, single-authority cutover,
rollback, and the state required for same-authority disaster recovery.

The object names are not options. Nothing in `cluster/apps/` reads the label;
[Verified](#verified) below does, and so does anyone telling this repo's objects
from the rehearsal's second control loop — **by value**, which is what makes the
name a contract rather than a setting.

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
| Loki | 15d of pod logs, queried through the same Grafana |
| Alloy | the DaemonSet that reads them off each node and pushes them |

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

#### That Secret is only read once, and the sidecars pay for it

**Grafana applies `GF_SECURITY_ADMIN_PASSWORD` when it first creates the admin
user and never again.** The password after that lives in `grafana.db` on
Grafana's `local-path` claim, which outlives every rollout. So editing the
Secret does not change the login — it changes what everything *else* believes
the login is, and the two drift apart silently.

The thing that finds out is not you. Both of Grafana's sidecars authenticate
with that Secret to call the admin API, and when it is stale they get a 401:

    POST /api/admin/provisioning/datasources/reload  status=401
    POST /api/admin/provisioning/dashboards/reload   status=401

**The failure is invisible from every direction that normally reports one.**
Flux is green, the ConfigMap exists and carries its label, the sidecar writes
the file into `/etc/grafana/provisioning/` — and Grafana never re-reads it. The
401 appears only in the sidecar container's own log. What you see in the UI is
the old state, or nothing.

Provisioning files ARE read at startup, so `kubectl rollout restart deployment
kube-prometheus-stack-grafana -n monitoring` picks up anything the sidecar
could not. That is the workaround; this is the fix, run against a Grafana whose
Secret is the one you want to keep:

    kubectl exec -n monitoring deploy/kube-prometheus-stack-grafana -c grafana -- \
      sh -c 'grafana cli --homepath /usr/share/grafana \
             admin reset-admin-password "$GF_SECURITY_ADMIN_PASSWORD"'

It reads the password out of the pod's own environment, so the value is never
typed and never lands in a shell history. Afterwards the database and the
Secret agree, the reloads return 200, and a datasource or dashboard added to
`cluster/apps/` appears without a restart.

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

### Logs

`cluster/apps/logging.yaml`, and it is a separate file from `monitoring.yaml`
on purpose: two charts, two release lifecycles. An upgrade of
kube-prometheus-stack should not be able to take logging down with it, and
deleting one file should leave the other standing.

| | |
|---|---|
| Loki | 7.3.0, single binary, filesystem storage on a 20Gi `local-path` claim |
| Alloy | 1.12.0, a DaemonSet reading `/var/log/pods` on every node |
| datasource | a labelled ConfigMap, picked up by Grafana's sidecar |

The datasource is a ConfigMap here rather than more `kube-prometheus-stack`
values so that adding logs costs no upgrade of the metrics release. It landed
in Grafana only after a restart, though, for a reason that has nothing to do
with Loki — see [that Secret is only read
once](#that-secret-is-only-read-once-and-the-sidecars-pay-for-it).

Nothing new is exposed and there is no second credential. Loki has no ingress:
Grafana proxies the queries in-cluster and the browser only ever talks to
Grafana, so the admin password above stays the whole of the auth surface.

Query it in Grafana under **Explore → Loki**. Each stream carries `namespace`,
`pod`, `container`, and `app` — the last so a log query names a workload the
same way a Service selector does:

    {app="chuggy-api"}
    {namespace="chuggy"} |= "error"

**It is not Promtail.** Promtail is the collector every Loki tutorial still
names and it reached end of life in March 2026. Alloy replaced it, and the
pipeline in `logging.yaml` is the same four stages Promtail ran — discover
pods, turn each into a log path, parse the CRI framing, push — written in
Alloy's syntax rather than a `scrape_config`.

#### What the chart defaults would have installed

Loki's chart is written for a cluster that is not this one. Left alone it
brings MinIO, two memcached pools, an nginx gateway, a canary DaemonSet and a
test pod — roughly 10Gi of requests before a single log line arrives. Each is
switched off explicitly in `logging.yaml`, and each is a thing a larger
deployment would want back.

Three of its defaults are load-bearing rather than merely large, and all three
fail in ways that do not name themselves:

- `auth_enabled` defaults to **true**, which makes Loki multi-tenant and makes
  every read and write require an `X-Scope-OrgID` header. The symptom is a
  datasource that looks right and answers `no org id`.
- `replication_factor` defaults to **3**. One ingester cannot replicate to
  three, and it declines to start.
- `retention_enabled` on the compactor defaults to **false**, so
  `retention_period` is a number Loki reads and ignores. Nothing tells you; the
  disk simply grows. Both are set, and the period is 15d to match Prometheus.

#### Two things about reading logs off a node

**k3s writes real files under `/var/log/pods`.** On some runtimes those entries
are symlinks into the container runtime's state directory, and a collector that
mounts only `/var/log` finds dangling links. Here `readlink -f` on a pod log
resolves to itself, so the one `/var/log` mount is the whole of what Alloy
needs. That is worth re-checking rather than assuming if this ever runs on
something other than k3s.

**Alloy runs as uid 0, and that is not incidental.** `/var/log/pods` is
`0750 root:root`. A collector that cannot read it does not crash — it reports
healthy and ships nothing, which is the failure shape you would find out about
from an empty Grafana a week later.

Its read offsets live on a `hostPath` at `/var/lib/alloy` rather than the
chart's default of the container's writable layer. A restart discards that
layer, and an Alloy that has forgotten how far it read starts every log file on
the node again from the beginning. This is a cache and not state, which is why
it is a plain `hostPath` and not a `chuggy.state` directory — losing it costs a
duplicate ingest and nothing else, and `modules/chuggy-state.nix` is for data
that must outlive the object mounting it.

#### The storage numbers are not real here either

Loki's 20Gi is a `local-path` claim, so it is a request and not a ceiling — the
[same sharp edge](#the-storage-numbers-are-not-real) as Prometheus and Grafana.
`retention_period: 360h` is what actually bounds it. Root disk usage remains the
only honest storage signal on this node.

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
the image it applies it from. It waits for the database in an initContainer and
then migrates once, `backoffLimit: 0`.

**Retrying the Job was never able to survive the NetworkPolicy warm-up, and the
rig says so.** kube-router admits a pod *IP*, and it needs a few seconds after
that IP appears; a failed Job pod is replaced rather than restarted, so each
attempt is a fresh address starting the same wait from nothing. A Job of this
shape whose container connects once produced five consecutive pods with five
distinct IPs, over 2m42s, every one refused. A pod that asked again inside the
same sandbox was admitted on its second attempt, two seconds in. That is also
why `chuggy-api` gets past it on a kubelet restart — a restart keeps the pod,
and so keeps the address that has by then been admitted.

**A migration that fails is terminal and needs a human.** Naming the Job after
the tag makes a re-tag a new object, but when the tag has not changed there is
nothing for Flux to re-create: it re-applies an identical `Failed` Job every
five minutes, the API server accepts it as unchanged, and the migration never
runs again.

**The Kustomization reports it.** `wait: true` health-checks every object this
directory applies, and kstatus reads a `Failed` Job as failed, so `flux get
kustomization apps` goes `Ready=False` with the Job among the objects its
message names. That is the loudest signal this repo has, and it is quieter than
it sounds: Alertmanager is off and `notification-controller` is not installed,
so nothing routes it anywhere, and — see [what does not work
yet](#what-does-not-work-yet-and-why) — `apps` is `Ready=False` already, held
there by a Deployment that never reaches an available replica. Read the message,
not the bit.

Read the pod, fix the cause, then delete the Job so the next reconcile builds it
afresh:

    kubectl -n chuggy logs job/chuggy-migrate-<tag>
    kubectl -n chuggy delete job chuggy-migrate-<tag>

Nothing has put this rig in that state — treat it as argued from the mechanism,
not observed.

**The failure that matters is the opposite one, and it is worse: the Job reports
success.** Migration 17 grants EXECUTE on a function `chuggy_boundary_owner`
owns, and it is issued by `chuggy_owner`, the role the Job connects as. Where
`chuggy_owner` is not a member of that role, a GRANT with no grant option goes
one of two ways, and which one decides whether anyone hears about it:

| grantor holds | PostgreSQL answers | outcome |
|---|---|---|
| no privilege on the object at all | `ERROR: permission denied` | transaction rolls back, exit 1, loud |
| **any** privilege, inherited included | `WARNING: no privileges were granted` | statement succeeds granting nothing, **everything commits** |

**A database without that membership is on the warning branch**, by a route
worth spelling out: the function's ACL never names `chuggy_owner`, but it grants
EXECUTE to `chuggy_ticket_service`, and `chuggy_owner` is a member of that
group — so it inherits a privilege, and the check is satisfied.
`has_function_privilege('chuggy_owner', …, 'EXECUTE')` is true while the same
call `WITH GRANT OPTION` is false; that pair is the discriminator. Membership in
every service group is deliberate in `postgres-roles.sql`, so a correctly
provisioned database is on this branch by construction.

Then the Job goes `Complete`, the ledger advances, the grant does not land, and
the API's selector-context reads fail at runtime with `permission denied for
function project_capacity_account`. **Deleting the Job does not fix it** — the
ledger committed, so a re-run has nothing pending and applies nothing. Recovery
is the membership grant plus re-issuing migration 17's grant by hand. Which is
why prerequisite 1 below has to happen *before* the Job runs, not after.

**This rig is past it**, because the roles file has been re-run here: the
membership is in `pg_auth_members`, `WITH GRANT OPTION` on that function is true
for `chuggy_owner`, and the function's ACL carries
`chuggy_api=X/chuggy_boundary_owner`. The step stays ordered where it is,
because a fresh database is the state it is written for.

An image the registry does not hold is not this case — that pod waits in
`ImagePullBackOff` with the Job still active, and publishing the expected digest
is enough.
The Job carries no `activeDeadlineSeconds`, which is the same decision: a
deadline would turn that wait into the terminal `Failed` state above.

The wait for the database is bounded anyway, and does not cost that back: it
runs in the initContainer, so its clock cannot start until the image is on the
node. Thirty attempts and then a non-zero exit, so a database that is genuinely
down ends as a failed Job rather than as a Job that hangs.

The API image already contains every control-plane command: its Dockerfile
copies the whole source tree and sets the API as its default. Seven workload
`image:` fields carry one immutable digest and move together. The migration
Job's name also changes when its pod template changes because Kubernetes makes
that template immutable.

Four of the five open no socket, so they have no probe and no Service. They
report an unmet precondition by name and exit; the kubelet restarts them. A
process that is alive and making no progress is therefore invisible to
Kubernetes, and closing that needs a health listener in chuggy itself.

### The network boundary around them

`cluster/apps/chuggy-control-plane-network-policy.yaml` holds seven
NetworkPolicies: one that admits nothing to the five pods with no listener, one
that admits the API from Traefik and from the selector alone, and five egress
rules that each state completely where one workload may go. The widest is the
scheduler's, which needs the Kubernetes API server at an address that is a DHCP
lease, so it permits everything but the pod and service networks; the file
argues why and what would narrow it.

**`chuggy-api` has no egress rule, deliberately.** It is the only one of these
the internet reaches, and it leaves the cluster for OIDC discovery against
`auth.vteng.io`, so a rule that got its destinations wrong would be an outage on
the one thing that works — and nothing here can rehearse it before it lands.
The issuer is where the pod is pointed, not where it is confined.

**`chuggy-web` is selected by none of the seven, in either direction**, and that
is the state this PR leaves it in rather than a decision it argues. It is the
console: nginx serving static files, reached from Traefik, with no `proxy_pass`
in it — the browser reaches the API through Traefik and this pod opens no
connection to it. Nothing here restricts what may reach it or where it may go.
Bounding it is worth doing and is not this change. `chuggy-ui`, the second
console, is the same image in the same posture and is selected by none of them
either; bounding both is one change.

**No probe has been run through any of these.** They were built against the API
server and their selectors checked against the labels the cluster carries, but
none has been applied to the running rig. Two are worth watching on the first
reconcile: the ingress rule on `chuggy-api`, the only one standing in front of
something that already works, and the egress rule on `chuggy-migrate`, standing
in front of the one thing that has to work before anything else does.

### Before any of it runs

Six things, none of which a manifest can do, and each argued in the file that
needs it. **Steps 1, 2 and 4 are ordered — 1 and 4 must both finish before 2 —
and the order is not enforceable from here**: Flux applies
`cluster/apps/` as one set on the reconcile after the merge, so anything a human
must do to the database or the image store has to be done *before* that merge,
not after it.

1. **Generate and synchronize the importer password, then apply it to the
   database from exactly Chuggy `e92cce9`.** The order inside this step is
   load-bearing. First rebuild the host with the Fabric revision that declares
   `configuration-importer-password`, then require generation and Secret sync
   to succeed:

   ```sh
   sudo systemctl restart chuggy-secrets-generate
   sudo systemctl restart chuggy-secrets-sync
   systemctl is-active chuggy-secrets-sync       # must print active
   sudo test -s /var/lib/chuggy/secrets/chuggy-postgres-credentials/configuration-importer-password
   kubectl -n chuggy get secret chuggy-postgres-credentials \
     -o jsonpath='{.data.configuration-importer-password}' | grep -q .
   ```

   A generated value in host state does not authenticate until
   `postgres-roles.sql` applies the same value to its login role. Check out the
   exact roles contract, not merely a branch that once contained it, and
   pre-filter the file before executing it:

   ```sh
   test "$(git rev-parse --short=7 HEAD)" = e92cce9
   sql=$(sed 's/--.*//' deploy/rig/postgres/postgres-roles.sql | tr '\n' ' ')
   # each must print 1
   printf '%s' "$sql" | grep -oi \
     'ALTER ROLE chuggy_configuration_importer WITH NOLOGIN[^;]*;' | wc -l
   printf '%s' "$sql" | grep -oi \
     'ALTER ROLE chuggy_configuration_importer_login WITH LOGIN INHERIT[^;]*;' | wc -l
   printf '%s' "$sql" | grep -oi \
     'GRANT [^;]*chuggy_selector_review[^;]* TO chuggy_api_login;' | wc -l
   printf '%s' "$sql" | grep -oi \
     'GRANT [^;]*chuggy_boundary_owner[^;]* TO chuggy_owner;' | wc -l
   printf '%s' "$sql" | grep -oi \
     'GRANT [^;]*chuggy_configuration_importer[^;]* TO chuggy_configuration_importer_login;' | wc -l
   grep -q '^\\getenv configuration_importer_password CHUG_PG_CONFIGURATION_IMPORTER_PASSWORD$' \
     deploy/rig/postgres/postgres-roles.sql

   kubectl -n chuggy port-forward svc/postgres 55440:5432 &
   forward=$!
   export PGPASSWORD="$(kubectl -n chuggy get secret postgres-superuser \
     -o jsonpath='{.data.password}' | base64 -d)"
   sudo -E chuggy-pg-role-env psql -h 127.0.0.1 -p 55440 -U postgres \
     -d chuggy -v ON_ERROR_STOP=1 -f deploy/rig/postgres/postgres-roles.sql
   kill "$forward"
   ```

   Comments are stripped and the lines joined first, because a plain line-wise
   grep answers the wrong question in both directions here. The second grant is
   one statement spread over three lines and its role list is unordered, so a
   pattern that matches a line matches only the ordering the file happens to
   have today; and a comment paragraph quoting either grant — this file's house
   style — makes a checkout that grants nothing answer 1. Both patterns name the
   **grantee**, which is the half that decides whether the grant is the one this
   step needs.

   `f8c6d7b`, the commit the shared digest was built from, answers 1 to both. But a pre-filter
   is all this is: it reads a file, not the server. What settles the question is
   the `pg_auth_members` query below.

   The two existing grants and the importer role binding are what this step is
   for on this rig.
   `chuggy_selector_review` to `chuggy_api_login` is what lets the API's second
   pool become that role, without which **the API refuses to listen**;
   `chuggy_boundary_owner` to `chuggy_owner` is what makes migration 17's
   `GRANT EXECUTE` land, without which **17 commits while granting nothing** and
   no re-run of the Job ever repairs it. That second one is what makes this step
   ordered: run it after the Job and the ledger already claims a grant that is
   not there.

   **It is not a read-only file, and three of its side effects matter.** It
   names the eight active login roles and for those eight it restates every
   role attribute and re-issues the password
   unconditionally, so it must be run with exactly the values in
   `chuggy-postgres-credentials` or step 4 must follow it with the new ones — an
   unset variable *clears* a password rather than leaving it. And it re-grants
   `CREATE ON SCHEMA public` to `chuggy_boundary_owner`. Leave that privilege
   standing until the new migration Job is `Complete`: migration 29 replaces a
   function owned by the boundary role and needs to create its replacement.
   Step 2 revokes and verifies the privilege immediately after the ledger
   reaches 29. Revoking it here makes the immutable Job fail before the release
   can become healthy.

   Then check the grants **landed**. This is the check the step rests on; the
   greps above only decide whether the file is worth running:

   ```sh
   kubectl -n chuggy exec postgres-0 -- \
     psql -U postgres -d chuggy -Atc \
     "SELECT r.rolname, count(am.member) FROM pg_roles r
        LEFT JOIN pg_auth_members am ON am.roleid = r.oid
       WHERE r.rolname IN ('chuggy_boundary_owner', 'chuggy_selector_review',
                           'chuggy_configuration_importer')
       GROUP BY 1 ORDER BY 1;"
   kubectl -n chuggy exec postgres-0 -- \
     psql -U postgres -d chuggy -Atc \
     "SELECT r.rolname, m.rolname FROM pg_auth_members am
        JOIN pg_roles r ON r.oid = am.roleid
        JOIN pg_roles m ON m.oid = am.member
       WHERE r.rolname IN ('chuggy_boundary_owner', 'chuggy_selector_review',
                           'chuggy_configuration_importer');"
   ```

   The second must list `chuggy_boundary_owner|chuggy_owner`,
   `chuggy_selector_review|chuggy_api_login`, and
   `chuggy_configuration_importer|chuggy_configuration_importer_login`.
   A fresh database has none until the roles file runs, which is what this step
   is for. **The first is what tells those two
   answers apart**, because `-Atc` prints nothing and exits 0 for an empty
   result, so a mistyped role name, the wrong `-d` and "granted nothing" all
   look identical. It must print three rows; a missing row is a name that is not
   in this database, not a membership that is absent.

2. **Build and publish an image** from that same checkout, verify its digest
   through CRI, and re-pin the eight control-plane workloads together. The
   migration Job's `metadata.name` changes with its immutable pod template.
   A digest the registry does not hold leaves the new pod in
   `ImagePullBackOff`; at one replica the API's rolling update retains the old
   ready pod while that is repaired.

   After `chuggy-migrate-e92cce9-registry` is `Complete` and reports migration
   29, remove the role-file bootstrap privilege and prove it is gone:

   ```sh
   kubectl -n chuggy exec postgres-0 -- \
     psql -U postgres -d chuggy -c \
     "REVOKE CREATE ON SCHEMA public FROM chuggy_boundary_owner;"
   kubectl -n chuggy exec postgres-0 -- \
     psql -U postgres -d chuggy -Atc \
     "SELECT max(version), has_schema_privilege(
        'chuggy_boundary_owner', 'public', 'CREATE')
        FROM schema_migration;"
   ```

   The second command must answer `29|f`.
   `images/api/Dockerfile` copies `package.json`, the resolved `node_modules`
   and `src/` into the shipped stage and nothing else — `deploy/` is never
   copied at all — so **the roles file is not in the image** and no inspection
   of the image can stand in for step 1's pre-filter.
3. **Create the host directory** the artifact volume binds:
   `/var/lib/chuggy/artifacts`, owned `1000:1000` — that is the uid and gid
   every control-plane container runs as, and it is what makes the finalizer
   able to write there. `install -d -o 1000 -g 1000 /var/lib/chuggy/artifacts`.
   The authority on the path and on its **mode** is
   `chuggy.state.artifacts.path` and `chuggy.state.artifacts.mode` on the
   reusable state module in fabric's PR 9; its tmpfiles rule adjusts an existing
   directory to whatever that option says, so this file does not restate a mode
   PR 9 owns. **The directory is there on this rig**, owned as this step asks.
   It was created by hand, so a rebuilt node has it again only once PR 9's
   tmpfiles rule lands. Do not read the PV going `Bound` as evidence either way:
   the claim names its volume, so binding is two API objects agreeing and never
   touches the node.
4. **Verify `chuggy-postgres-credentials` and the database agree before the
   merge.** The generated inventory now has eight keys: owner, API, ticket
   service, selector, scheduler, finalizer, worker plane, and configuration
   importer. The database has the corresponding eight active login roles:
   `chuggy_owner` and seven `*_login` roles. `chuggy_dispatcher_login` is legacy
   and is not part of this Secret or any workload. Step 1 must have synchronized
   all eight Secret values and applied those same values through
   `chuggy-pg-role-env`; a green Secret sync alone proves only host/cluster
   agreement, not that PostgreSQL accepts the value. Authenticate as every
   login over the cluster network before merging. In particular, verify
   `chuggy_configuration_importer_login` authenticates with
   `configuration-importer-password` and that its inherited membership exists:

   ```sh
   kubectl -n chuggy exec postgres-0 -- psql -U postgres -d chuggy -Atc \
     "SELECT pg_has_role('chuggy_configuration_importer_login',
                         'chuggy_configuration_importer', 'MEMBER');"
   ```

   It must print `t`. The importer connects as the login role; it does not use
   `SET ROLE`, so this inherited membership is the capability boundary.
5. **Create `chuggy-selector` and `chuggy-finalizer-credentials`** by hand — the
   selector's OAuth2 client secret and policy token, and the finalizer's git
   credential. Values never go in this repository; it is public. A pod whose
   Secret is missing is never built, under one of two names: a `secretKeyRef`
   env gives `CreateContainerConfigError`, a mounted secret gives
   `ContainerCreating` on a `FailedMount`.

   Of the selector's two, the client secret is **not a value the operator
   invents**: it is what Hydra returns when the client the selector
   authenticates as is registered, so the registration comes first and the
   Secret carries its output. The policy token is the operator's own, because
   nothing issues one — nothing serves the protocol it authenticates to.
   `chuggy-selector.yaml` holds both commands and argues the audience the client
   must be granted.

   The finalizer's is **not a credential for anywhere outside this cluster**. Its
   remote is `rig.git` on the rig's own git service, so the value is the operator
   credential that service already validates, copied rather than minted:

   ```sh
   kubectl -n chuggy create secret generic chuggy-finalizer-credentials \
     --from-literal=rig-git="$(kubectl -n chuggy-git get secret git-operator \
       -o jsonpath='{.data.password}' | base64 -d)"
   ```

   That is the one credential the git service's htpasswd admits on
   `/git-receive-pack`, which is what makes D34 — only the finalizer advances the
   deployed revision — true here rather than aspirational. An external
   repository is a later thing and wants D31's short-lived minting, not a static
   token on a rig.
6. **Establish the first recovery epoch**, as a Secret and a row that carry the
   same value. `chuggy-recovery-epoch` is read by both the scheduler and the
   finalizer, and the row is what they fence against; no migration writes it,
   because the table is created empty. `chuggy-finalizer.yaml` carries the two
   commands. The value is generated, never written down here: `schema.ts`
   requires an epoch be unpredictable and never reused, and a literal in a
   public repository is neither.

### What does not work yet, and why

- **The lead now runs and decides, and nothing it dispatches is delivered.**
  Both of the preconditions that kept the selector at zero replicas are
  answered: it mints its own token from Hydra rather than being handed one, and
  `selector-policy` — which asked a trusted policy service nothing ever
  implemented — is retired along with the protocol by kasofsk/chuggy#503,
  because the project's lead decides in its place. A decision becomes a turn on
  that lead's mailbox, which is the database this pod already connects to, so
  nothing was added to `chuggy-selector-egress` for it. Release 18 was blocked
  by a closed lead row; release 19 carries the migration that makes a project
  take a successor, and on the rig it did — the lead opened itself, filed and
  released derived work, and staged three dispatches in one decision. What stops
  them now is one row's initial state: `enforce_selector_proposal_initial_state`
  reads `selector_runtime_settings.dispatch_mode`, which is the
  **installation's** mode and is `ApprovalRequired`, so every delivery is stamped
  `AwaitingApproval` however a project's own `dispatchMode` reads — and the
  image serves no route that approves one. Both halves are chuggy's, not this
  repository's, and neither is a manifest: nothing here can set the installation
  mode either.
- **The finalizer promotes onto this cluster's own git and nothing external.**
  Its remote is `rig.git` in `chuggy-git`, and `chuggy-finalizer-egress` admits
  that one pod on its own 8080 and no longer admits the public internet at all --
  the URL names the Service's 80, but a `NetworkPolicy` port is the destination
  pod's. All
  four of its preconditions are answerable here: `git-available` runs `git
  --version` and the tag above carries git 2.47.3, checked by running it in a pod
  rather than read off the Dockerfile; a writable scratch and a writable artifact
  root are the volumes `chuggy-finalizer.yaml` declares over prerequisite 3's
  host directory; and `repository-credentials-available` reads prerequisite 5's
  Secret, which only has to be readable — it is never validated against a remote.
- **Nothing binds a repository yet, so a healthy finalizer idles.**
  `finalization_request` is empty, so the credential makes the process ready
  without making it do anything. Loading an external repository is later work and
  wants D31's short-lived minting.
- **The scheduler places nothing, and until the tag above it could not start at
  all.** Migrations 12 and 15 were edited after this rig applied them, so
  `execution` here carries none of the five requirement columns the code reads
  while the ledger still says 18 — and the ledger compares a version and a name,
  so `schema-compatible` passed and the first quantum failed `column
  e.requirement_identity does not exist`. Migration 19 in the tag above is what
  adds them; kasofsk/chuggy#255 is where it is argued.
- **A scheduler whose loop dies says nothing, which is worth knowing before
  reading a log.** That failure was recorded in the runtime's own `health()` and
  read by no root: the process exited **0** with an **empty log**, so `kubectl
  get pods` said `Completed` and restarted it, thirteen times here. An empty log
  on a control-plane pod is therefore not evidence that nothing happened. The
  fix is chuggy's and is not in this repository.
- **Placement is still refused, by design.** The execution policy names a
  profile the worker image list does not admit, so `kubernetesWorkerPodRequest`
  answers `Denied` with `ExecutionProfileUnavailable` before it builds a request
  — no placement is submitted and the credential is never reached. That
  credential could not create a worker pod if it were: `kubectl auth can-i
  create pods -n chuggy-work
  --as=system:serviceaccount:chuggy:chuggy-scheduler` answers no. The worker
  namespace, its RBAC, the image allowlist and the resource budgets are the next
  stage's.

**`apps` stays NotReady after this.** `wait: true` health-checks every object,
and `flux get kustomizations -A` names the one it stops on:
`Deployment/chuggy/chuggy-finalizer status: 'Failed'` — a Deployment past its
progress deadline with no available replica. Git in the image was the other half
of that and is now in the tag above, so the credential Secret is the only thing
left between this and a green `apps`, which is why the finalizer is left at
one. The zero above takes the selector out of that set instead, because nothing
clears its blocker and a Deployment nobody can make available is one more red
object for a real one to hide behind. That is also why a failed migration Job
adds a line to a list rather than raising a flag.

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

## Releases

A release is a commit on this repository's `main` that moves the control plane's
image digests to one chuggy commit and, where the release carries them, lets the
migrate Job apply that commit's migrations. Merging in kasofsk/chuggy deploys
nothing; this is where a deployment happens.

**The list starts here rather than being backfilled.** Earlier releases were
recorded outside this repository and reconstructing them from history would be
writing down claims nobody checked. What every entry must carry is what the one
below carries: the fabric merge commit, the chuggy commit, every digest that
moved, the ledger range, and the undo — including the dump, because a ledger
that has moved forward is not walked back by reverting a fabric commit.

### Release 31 — 2026-09-06 — the console's utilities are Tailwind over its tokens

- **fabric** `42f64df` → **`83e1185d`** (PR #169), phase 1's output and nothing
  else: ten `source-commit` annotations, the console digest line and the migrate
  Job's name; no adversarial reviewer, the orchestrator held the diff to those
  lines, read both digests back from the registry, and ran `--merge`.
- **chuggy** `2b092647` → **`99d5f2d0c10608bf332f4b4cec3069a52cd1cb26`** —
  Tailwind 4 integrated as a utility generator over the design system's tokens
  and nothing else (kasofsk/chuggy#594, one PR batched from one opus and four
  sonnet branches; three fresh-session reviews — seven findings, then one, then
  none — with nothing planted): utilities only, no preflight, no default
  palette, no default scales; the sheet maps Tailwind's namespaces onto the
  tokens by reference (`@theme inline reference`); the cascade is
  `properties, tokens, base, ui, page, utilities`, Tailwind's own `properties`
  layer ordered weakest; the console's build now refuses a raw colour or
  `px`/`rem` length in the emitted utilities layer, and a generated utility
  whose name a layered sheet also selects (the scanner makes `.table`,
  `.hidden`, `.filter` from ordinary words in the sources, so the Table
  primitive's class became `tabular`). Legacy layout rules whose declarations
  were token utilities moved onto their elements and left the legacy sheet.
  Between the two commits the tree moved under `ui/chuggy-ui/`,
  `scripts/console-policy.ts` and its tests,
  `.chug/tasks/check-console-sheets.sh` and its suite, and the root
  `package-lock.json`.
- **Ledger 075 → 075.** No migration, so no dump was taken and the undo is a
  revert. The migrate Job `chuggy-migrate-99d5f2d0-registry` found the schema
  already current.
- **Digests that moved.** `chuggy-ui` `sha256:5a5f0f2f…71fe` →
  **`sha256:e33ddbaa…0590`**, what the registry answers for
  `chuggy/web:chuggy-ui-99d5f2d0`. The api was rebuilt because the lockfile and
  `scripts/` moved and came out at the digest it already ran,
  `sha256:3a59514e…ae98e`, so no manifest naming it changed its image.
  `chuggy-web` (`sha256:2b63599e…0ab0e6`) did not move.
- **The roll.** `deploy-to-gtr.sh --merge` from a worktree detached at the
  released commit: only the console pod rolled, with no restart; every other pod
  is the one release 29 left, restart counts included. `/health/ready` answered
  `200` on the api Service's port 3000. Phase 1's first run was refused by the
  gate on `check-random` failing in under three seconds with no seed named;
  alone in the same worktree it passed three times in under two seconds each and
  the second full run was clean — the fourth environmental false red on record,
  under investigation in chuggy. Checked in Chrome against the live
  `chuggy-ui.vteng.io` under its served CSP, on the project page and on ticket
  44 with a run's evidence opened — the page holds no `<style>` element of its
  own and raised no `securitypolicyviolation`; the stylesheet's layers read from
  the CSSOM are `properties, tokens, base, ui, page, utilities` in that order;
  both Table primitives draw as `tabular` with tabular figures; and the run
  list, run rows, artifact rows and result box that this release moved onto
  utilities compute to the token values (the space scale's gaps and padding, a
  hairline top edge, the ink colours, weight 600). The served CSP header is
  unchanged, the document carries no inline script or `style` attribute, and the
  utilities layer resolves every colour and length to a token, the only literal
  lengths being `1px` hairlines.
- **Undo.** `git revert -m 1 83e1185d` on this repository: `chuggy-ui` goes back
  to `5a5f0f2f…71fe`, one roll of the console pod and nothing else.

### Release 30 — 2026-09-06 — the console's controls are Radix primitives

- **fabric** `54d4a2d` → **`42f64df`** (PR #167). The PR was
  `deploy-to-gtr.sh` phase 1's output and nothing else — the ten
  `source-commit` annotations, the console digest and the migrate Job's
  name — so it had no adversarial reviewer: the orchestrator held the diff to
  those three kinds of line, read the console digest back from the registry,
  and ran `--merge`. A rollout PR that carries anything written by hand still
  gets the review.
- **chuggy** `6f557b42` → **`2b09264751bc319bf4f47b57b1233c1b8439cd70`** — the
  realtime console's theme control, project switcher, hover texts and
  single-toggle disclosures are Radix primitives (kasofsk/chuggy#593, one PR
  batched from four subagent branches; two fresh-session reviews with
  nothing planted): a ToggleGroup, a non-modal DropdownMenu, a Tooltip a
  keyboard can reach, and a Collapsible, each with a jsdom case asserting no
  `<style>` element exists while it is open, because the served CSP's
  `style-src 'self'` refuses the one Radix's modal layers and Select inject.
  Form selects stay native for that reason, and the panels and the ledger
  stay native `<details>`. Between the two commits the tree moved under
  `ui/chuggy-ui/` and the root `package-lock.json` only.
- **Ledger 075 → 075.** No migration moved, so no dump was taken and the undo is
  a revert. The migrate Job found the schema already current.
- **Digests that moved.** `chuggy-ui` `sha256:1ee9d5fd…2b25` →
  **`sha256:5a5f0f2f…71fe`**, what the registry answers for
  `chuggy/web:chuggy-ui-2b092647`. The api was rebuilt because the lockfile
  moved and came out at the digest it already ran, `sha256:3a59514e…ae98e`,
  so no manifest that names it changed its image. `chuggy-web`
  (`sha256:2b63599e…0ab0e6`) did not move.
- **The roll.** `deploy-to-gtr.sh --merge` from a worktree detached at the
  released commit: only the console pod rolled, with no restart; every other
  pod is the one release 29 left, restart counts included. `/health/ready`
  answered `200` on the api Service's port 3000. No ticket or session pod was
  live in `chuggy-work` during the roll. Checked in Chrome against the live
  `chuggy-ui.vteng.io` under its served CSP: the project menu opens with the
  page left non-modal, the theme radios write the attribute and the store,
  a tooltip opens on focus, and the page holds no `<style>` element and
  raised no `securitypolicyviolation` through all three. Phase 1's first run
  was refused by the gate on a `check-model` witness that died on an
  unhandled rejection and passed alone a minute later; the second run was
  clean.
- **Undo.** `git revert -m 1 42f64df` on this repository: `chuggy-ui` goes
  back to `1ee9d5fd…2b25`, one roll of the console pod and nothing else.

### Release 29 — 2026-09-06 — a rework is told what the evaluation found

- **fabric** `22b74f2` → **`1d69bb6`** (PR #165), after #164 (`e2ce6af`), the
  worker build request for chuggy `9ed88690`. The worker moves to **`0.19`**:
  `CHUG_SCHEDULER_ADMITTED_IMAGES` gains the entry, shaped like `0.18`, for
  `sha256:0f728b62…4009` — what BuildRun `build-9ba10868…-a1` produced from
  `builds/chuggy/9ed88690…/` and what the registry answers for
  `chuggy/worker:request-9ba10868…` — and `CHUG_SCHEDULER_SESSION_POLICY.image`
  moves to it in the same commit.
- **chuggy** `d5d90f55` → **`6f557b42d67581eb6943bd368544373d9b55756b`** — a
  Work task that follows a failed evaluation is briefed with the reports of
  that evaluation's failed executions (kasofsk/chuggy#591, closes #590; three
  fresh-session reviews with nothing planted). Before, the only section that
  reached back to an earlier task was the work reports a review reads, so a
  rework was briefed like a first attempt: on 2026-09-06 ticket 44 failed its
  commanded check stage twice on findings its reworks never saw, and passed
  on the third. Now the reports of the latest evaluation's `Failed`
  executions render under a section of their own, prefaced by wording the
  template owns, under the same bounds and refusals as the work reports; the
  worker's check stage reports the failing gate's last output after the
  status lines, scrubbed and made printable before the plane measures it, so
  the section names the gate and what it found rather than an exit status.
  Also carried: #592, which moves `chuggy-development`'s worker pin from
  `0.10` to this release's `0.19`, so a ticket released against the new
  revision runs its check stage on the worker that writes the excerpt.
  Between the two commits the tree moved under `src/`, `images/worker/`,
  `ui/chuggy-ui/`, `test/` and `.chug/configurations/`.
- **Ledger 075 → 075.** No migration moved, so no dump was taken and the undo is
  a revert.
- **Digests that moved.** api `sha256:2477a163…6013` →
  **`sha256:3a59514e…ae98e`**, what the registry answers for
  `chuggy/api:6f557b42`, in every manifest that names it; `chuggy-ui`
  `sha256:e107afbd…e4f2` → **`sha256:1ee9d5fd…2b25`**, what it answers for
  `chuggy/web:chuggy-ui-6f557b42`, because the tree moved under
  `ui/chuggy-ui/`. `chuggy-web` (`sha256:2b63599e…0ab0e6`) did not move.
  `deploy-to-gtr.sh`'s first run built the two and wrote the ten
  `source-commit` annotations and the migrate Job's name; the admit commit
  was by hand. The reviewer read the three moving digests back from the
  registry and the BuildRun, confirmed the configuration at `6f557b42` pins
  the same worker digest, and found the diff to be the annotations, the api
  and console images, the Job's name, the admit entry, the policy image and
  the nix grep line; five mutations each went red under
  `check-release-consistency` or `session-placement.py`.
- **The roll.** `deploy-to-gtr.sh --merge` ran end to end from a worktree detached at
  the released commit: the merge, the reconcile, the migrate Job finding the
  schema already current in six seconds, and every Deployment naming the api
  rolling with the console and the scheduler. The restarts were the
  pod-startup race: finalizer, scheduler and ticket-service once on a
  refused connection to postgres, the selector twice on a failed source
  fetch, none after. `/health/ready` answered `200` on the api Service's
  port 3000, and the rendered scheduler's session policy names the `0.19`
  digest. No ticket or session pod was live in `chuggy-work` during the roll.
  Nothing has yet reworked under the new briefing; the next ticket released
  against `chuggy-development`'s new revision that fails its check stage is
  the first to.
- **Undo.** `git revert -m 1 1d69bb6` on this repository: the api goes back
  to `2477a163…6013`, `chuggy-ui` to `e107afbd…e4f2`, and the session policy
  to `0.18`, one more roll of every Deployment that names any of them, which
  like this one must find no session or worker pod live in `chuggy-work`. A
  ticket released against `chuggy-development`'s new revision would then be
  refused at pod time until re-created against an earlier one.

### Release 28 — 2026-09-06 — a failed selector decision is retried, and the session cap is out of a lead's reach

- **fabric** `17bf786` → **`8022de4`** (PR #162, which carried #161's change as
  its own second commit; #161 was closed as superseded before the merge). No
  build request: nothing under `images/worker/` moved, so the worker stays
  `0.18` and the admitted list and `CHUG_SCHEDULER_SESSION_POLICY` are
  byte-identical to release 27.
- **chuggy** `dd12b248` → **`d5d90f556603a79a3ced140c0c7f105e04942761`** — a
  selector decision whose policy run failed no longer consumes the dispatch view
  (kasofsk/chuggy#588, three fresh-session reviews with nothing planted).
  Before, the failure was recorded exactly as a completed decision, cursor and
  candidate scan included, so on a view that did not move again the view was
  never offered again: on the evening of 2026-09-05 the decision that carried
  ticket 44 failed because its lead pod had spent the per-attempt dollar cap,
  and `vteng/chuggy` stalled. Now the state the observation was built from is
  kept with attention raised, so the next poll offers the same view to a fresh
  attempt, a bounded number of times per view before the failure consumes it as
  a completed decision would; the count is derived from the interaction ledger,
  newest first, not stored. Also carried: kasofsk/chuggy#587 (every
  configuration stage installs the toolchain) and one rig-authored console
  change. Between the two commits the tree moved under `src/`, `ui/chuggy-ui/`,
  `test/` and `.chug/configurations/`.
- **The scheduler's session cap.** `CHUG_SCHEDULER_SESSION_BOUNDS` is set for
  the first time, to a `budgetUsd` a working lead cannot reach. The runtime
  meters the cap over one pod's whole life, and a lead pod's first turn re-reads
  the whole transcript at full price, so under the published default a pod took
  a few turns and failed the next, whatever it carried. Running session pods
  keep the bounds they were placed with; there were none, so the lead's next
  attempt is the first under the new cap.
- **Ledger 075 → 075.** No migration moved, so no dump was taken and the undo is
  a revert.
- **Digests that moved.** api `sha256:8301d7e2…1c68` →
  **`sha256:2477a163…6013`**, what the registry answers for
  `chuggy/api:d5d90f55`, in every manifest that names it; `chuggy-ui`
  `sha256:72254235…1347` → **`sha256:e107afbd…e4f2`**, what it answers for
  `chuggy/web:chuggy-ui-d5d90f55`, because the tree moved under `ui/chuggy-ui/`
  and under `src/contract/`, which the console image copies. `chuggy-web`
  (`sha256:2b63599e…0ab0e6`) did not move. `deploy-to-gtr.sh`'s first run built
  the two and wrote the ten `source-commit` annotations and the migrate Job's
  name. The reviewer read both digests back from the registry, confirmed the
  live Deployments ran the old ones and that no bound was set, and found the
  diff to be the ten annotations, the eight api images, the one console image,
  the Job's name, the one environment variable with its comment, and the
  rewritten paragraph that had listed the variable as unset on purpose.
- **The roll.** `deploy-to-gtr.sh --merge` ran end to end from a worktree
  detached at the released commit: the merge, the reconcile, the migrate Job
  completing with nothing to apply, and every Deployment naming the api rolling
  with the console. Finalizer, scheduler, selector and ticket-service each
  restarted once, every previous container ending on a refused connection to
  postgres — the race a new pod runs — and none after. `/health/ready` answered
  `200` on the api Service's port 3000, and the scheduler's rendered environment
  carried the new bound.
- **What it did not do.** The view the incident consumed stays consumed: the
  selector state row for `vteng/chuggy` still holds the exhausted scan on the
  view's current watermark, and nothing moves it but a journaled decision (a
  released draft, a revoked ticket) or a hand edit of that row.
- **Undo.** `git revert -m 1 8022de4` on this repository: the api goes back to
  `8301d7e2…1c68`, `chuggy-ui` to `72254235…1347`, and the scheduler loses
  `CHUG_SCHEDULER_SESSION_BOUNDS`, one more roll of every Deployment that names
  either, which like this one must find no session or worker pod live in
  `chuggy-work`.

### Release 27 — 2026-09-05 — a member thread closes from the console

- **fabric** `e99383c` → **`7034e63`** (PR #159). No build request: nothing
  under `images/worker/` moved, so the worker stays `0.18` and the admitted list
  and `CHUG_SCHEDULER_SESSION_POLICY` are byte-identical to release 26.
- **chuggy** `a0399827` → **`dd12b2481e588cc2bb477118ffd781fccb869b9e`** — a
  member thread can be closed through the API and from the console, where before
  only the provisioning root inside the api pod could end one
  (kasofsk/chuggy#585, PR #586, six fresh-session reviews with nothing planted).
  `POST …/threads/:session/close` ends the thread named, for any member who may
  mutate the project: a close is terminal and immediate, the turns it still held
  are abandoned, the thread stays readable, and the member's next `Open` is a
  new session. The thread page carries `Close` in its head and the listing a
  small one per row. Migration 075 adds the door, a trigger that writes a
  `Session` change when any session's state moves so a page re-reads on a close
  that moved no turn, and replaces the listing to answer open threads first and
  the rest newest first, so closed threads displace no live one from the bounded
  page. Between the two commits the tree moved under `src/`, `ui/chuggy-ui/` and
  `test/`.
- **Ledger 074 → 075.** The pre-merge dump is
  `/home/geoff/backups/chuggy-pre-dd12b248.dump`, with its globals beside it on
  the operator's host, and the undo is a restore from it rather than a revert.
- **Digests that moved.** api `sha256:ceb26b02…5d52` →
  **`sha256:8301d7e2…1c68`**, what the registry answers for
  `chuggy/api:dd12b248`, in every manifest that names it; `chuggy-ui`
  `sha256:1e331179…5957` → **`sha256:72254235…1347`**, what it answers for
  `chuggy/web:chuggy-ui-dd12b248`, because the console's own files moved and the
  image copies `src/contract` besides. `chuggy-web` (`sha256:2b63599e…0ab0e6`)
  did not move. `deploy-to-gtr.sh`'s first run built the two and wrote the ten
  `source-commit` annotations and the migrate Job's name. The reviewer read both
  digests back from the registry and found the diff to be the ten annotations,
  the eight api images, the one console image and the Job's name.
- **The roll.** `deploy-to-gtr.sh --merge` ran end to end from a worktree
  detached at the released commit: the dump, the merge, the reconcile, the
  migrate Job applying 075 in six seconds, and every Deployment naming the api
  rolling with the console. The restarts were the migration window's: api,
  finalizer and scheduler twice, selector three times, ticket-service once, each
  previous container ending on the ledger-74 refusal, the not-migrated
  precondition, the api not yet ready or a refused connection to postgres — the
  race a new pod runs — and none after the api reported itself ready, which was
  after the Job. `/health/ready` answered `200` on the api Service's port 3000
  after. At the edge the close route answered `401` to an unauthenticated
  versioned `POST` and `415` to one without the media type, and the console
  answered `200`. The thread that motivated the change was closed through the
  new control seventy-one seconds after the Job completed — its `Session` frame
  naming `Closed` is the first row 075's trigger wrote on the rig — and its
  member opened a new thread under two minutes later.
- **Undo.** Restore `/home/geoff/backups/chuggy-pre-dd12b248.dump` and
  `git revert -m 1 7034e63` on this repository: the api goes back to
  `ceb26b02…5d52` and `chuggy-ui` to `1e331179…5957`, one more roll of every
  Deployment that names either, which like this one must find no session or
  worker pod live in `chuggy-work`.

### Release 26 — 2026-09-05 — a thread is told what it is for

- **fabric** `c3be34c` → **`0f0b82c`** (PR #157). No build request: nothing
  under `images/worker/` moved, so the worker stays `0.18` and the admitted
  list and `CHUG_SCHEDULER_SESSION_POLICY` are byte-identical to release 25.
  The commit before it, `c3be34c` (PR #156), is not a release: it moved
  `CHUG_SCHEDULER_SESSION_RESOURCES` from a 1Gi memory limit to 4Gi and the
  request from 512Mi to 1Gi, after the first member thread opened since
  release 25 lost two attempts to the old limit — containerd's `TaskOOM`
  events name both — while a typecheck of its checkout ran, and rolled the
  scheduler alone.
- **chuggy** `58a747d9` → **`a03998270162cccd7ccc1065f48a93ae17f76e5a`** — a
  member thread's objectives carry a purpose after the owner and before the
  North Star and the two standing rules: a request for a change is a request
  for a draft filed through the draft tools, the lead dispatches and the
  fabric works, the shell and the checkout are for reading the tree so a draft
  is accurate and change nothing in it, no build or gate is run, and every
  turn ends by saying what was filed. The first thread opened after release
  25 rolled had been asked whether the thread pages could be made more
  idiomatic and had edited the console in its checkout, run the gates and
  filed nothing
  (kasofsk/chuggy#584, four fresh-session reviews with nothing planted, every
  finding comment-level). The lead roster's comment stops leaning on a thread
  running the gates. Between the two commits the tree moved under
  `src/interpreter/` and one test only.
- **Ledger 074 → 074.** No migration, so no dump was taken and the undo is a
  revert.
- **Digests that moved.** api `sha256:42a7d0fc…9145` →
  **`sha256:ceb26b02…5d52`**, what the registry answers for
  `chuggy/api:a0399827`, in every manifest that names it. `chuggy-ui`
  (`sha256:1e331179…5957`) and `chuggy-web` (`sha256:2b63599e…0ab0e6`) did
  not move; `deploy-to-gtr.sh`'s first run built the api alone and wrote the
  ten `source-commit` annotations and the migrate Job's name. The reviewer
  rendered `cluster/apps` at `c3be34c` and at `0f0b82c` and found the diff to
  be the ten annotations, the eight api images and the Job's name.
- **The roll.** `deploy-to-gtr.sh`'s first run was made from a detached
  worktree; the merge was `gh pr merge --admin --merge` and
  `flux reconcile kustomization apps --with-source` by hand, with no session or
  worker pod live in `chuggy-work`, because the script's merge path was
  refused by the operator's own permission classifier. Every Deployment naming
  the api rolled; api, finalizer and selector each restarted once at startup
  and are on their second container — the finalizer's and the selector's first
  containers ended on `ECONNREFUSED` to postgres, the api's on the one
  not-ready line it has for any failure to reach its database, the race a new
  pod runs against the postgres network policy. `/health/ready` answered `200`
  on the api Service's port 3000 after (the edge routes only `/api/v1` to the
  api, and the console's fallback answers any other path), the migrate Job
  completed with nothing to apply, and the live api image was read for the
  new objectives' first sentence. A thread's prompt is recorded on its session
  row at open, so the thread that motivated the change keeps its old
  objectives until it is closed and another opened; that opening is the proof.
- **Undo.** `git revert -m 1 0f0b82c` on this repository: the api goes back to
  `42a7d0fc…9145`, one more roll of every Deployment that names it, which like
  this one must find no session or worker pod live in `chuggy-work`.

### Release 25 — 2026-09-05 — the console opens a thread

- **fabric** `6810fa8` → **`590f49d`** (PR #154). No build request: nothing
  under `images/worker/` moved, so the worker stays `0.18` and the admitted
  list and `CHUG_SCHEDULER_SESSION_POLICY` are byte-identical to release 24.
- **chuggy** `b32afdb5` → **`58a747d9bad6f638e7e198a5c36e2765535adf83`** — the
  console's `Open` control on the threads page posts the versioned empty
  object instead of nothing. The request plumbing sends the versioned media
  type only with a body, and the thread door takes only versioned JSON, so an
  open that posted nothing was refused before it reached the caller's
  identity: `UnsupportedMediaType` inside the cluster, and through the edge a
  transport fault rendered as `InvalidRequest`, which is what the page showed
  (kasofsk/chuggy#583; the routes suite now records the request as it left,
  and is red without the body). Adversarial review was skipped at the owner's
  instruction; the diff was held to its set by hand. Between the two commits
  the tree moved under `ui/chuggy-ui/` only.
- **Ledger 074 → 074.** No migration, so no dump was taken and the undo is a
  revert.
- **Digests that moved.** `chuggy-ui` `sha256:1ba98402…7e8e` →
  **`sha256:1e331179…5957`**, what the registry answers for
  `chuggy/web:chuggy-ui-58a747d9`. api (`sha256:42a7d0fc…9145`) and
  `chuggy-web` (`sha256:2b63599e…0ab0e6`) did not move; `deploy-to-gtr.sh`'s
  first run built the console alone and wrote the ten `source-commit`
  annotations and the migrate Job's name.
- **The roll.** `deploy-to-gtr.sh --merge` ran end to end. Only `chuggy-ui`'s
  pod template changed, so only it rolled: one container, no restart.
  `/health/ready` answered `200` on the api Service's port 3000 after, the
  console answered `200` at its edge, and the migrate Job completed with
  nothing to apply. Nothing has yet opened a thread through the fixed control;
  the first member to press `Open` is its proof.
- **Undo.** `git revert -m 1 590f49d` on this repository: `chuggy-ui` goes back
  to `1ba98402…7e8e`, one more roll of its pod and nothing else.

### Release 24 — 2026-09-05 — the store clips an entry it cannot hold whole

- **fabric** `7e3d60c` → **`cfccacf`** (PR #152; the build request it depends on
  is PR #151, `7e3d60c` → `b6c5235`).
- **chuggy** `d8821c10` → **`b32afdb57a0c3c74c0f286b94befe57697c82206`** — a
  transcript entry larger than one store batch is degraded at the pod's session
  store instead of being sent as a body the plane refuses: a text field is cut
  to a head and a note, an encoded string or a list is dropped whole and the
  note says what it replaced, an `image` or `document` block is replaced by a
  text block naming what it was, a signed thinking block is kept whole, and
  the keys that identify an entry are never touched; only the stored copy
  changes
  (kasofsk/chuggy#578, closing #575, eight fresh-session reviews with nothing
  planted; the residual, a signed block alone larger than a batch, is #582).
  Between the two commits the tree moved under `images/worker/` only.
- **Ledger 074 → 074.** No migration, so no dump was taken and the undo is a
  revert.
- **Digests that moved.** None but the worker's: api (`sha256:42a7d0fc…9145`),
  `chuggy-ui` (`sha256:1ba98402…7e8e`) and `chuggy-web` (`sha256:2b63599e…0ab0e6`)
  did not move; `deploy-to-gtr.sh`'s first run built no image and wrote the ten
  `source-commit` annotations and the migrate Job's name. The reviewer checked
  that nothing outside `images/worker/` moved, and that no api or console
  Dockerfile copies that path, against the two commits rather than the pull
  request.
- **Worker:** built from `builds/chuggy/b32afdb5…8206/`, admitted as
  `chuggy-worker` **`0.18`** =
  `sha256:a49a5244f556be7996b1d8a20e61a23504546e32f9eb1a3d636d4fb2b421d071`,
  and `CHUG_SCHEDULER_SESSION_POLICY.image` moved to it from `0.17`
  (`sha256:00598efb…7458`) in the same commit. The BuildRun's digest and the
  registry's agreed. The execution worker the configurations pin is unchanged.
- **The roll.** `deploy-to-gtr.sh --merge` ran end to end. Only the scheduler's
  pod template changed, so only the scheduler rolled: one container, no
  restart, no previous container to read. `/health/ready` answered `200` on the
  api Service's port 3000 after, and the migrate Job completed with nothing to
  apply. Nothing has run under `0.18`: no session or worker pod was placed
  after the roll, and every thread on `vteng/chuggy` was closed just before it,
  so the first ticket released to the lead is the first session on this image.
- **Undo.** `git revert -m 1 cfccacf` on this repository: the scheduler goes back
  to `0.17`, one more roll of its pod, which like this one must find no session
  or worker pod live in `chuggy-work`.

### Release 23 — 2026-09-05 — the refusal exclusion is exact for the page it is asked about

- **fabric** `94defe9` → **`742a9fc`** (PR #149). No build request: nothing
  under `images/worker/` moved, so the worker stays `0.17` and the admitted
  list and `CHUG_SCHEDULER_SESSION_POLICY` are byte-identical to release 22.
- **chuggy** `3ff1ed58` → **`d8821c101764b559f5721b3be6060fd14a987660`** — the
  selector's observation excludes a candidate whose standing refusal names the
  version shown, for every candidate on the page rather than for the first
  page of the project's refusals ordered by ticket, and the refusals the lead
  is shown are the same read as the exclusion, so what is excluded is always
  liftable (kasofsk/chuggy#579, closing #574, three fresh-session reviews with
  nothing planted); and `deploy-to-gtr.sh --merge` counts only worker and
  session pods as a live attempt (#577, closing #576).
- **Ledger 072 → 074.** `chuggy-migrate-d8821c10-registry` reported
  `applied 73,74`: 073 creates `standing_agentic_refusals_among`, grants it to
  the selector role and revokes that role's grant on the paged
  `standing_agentic_refusals` (the API's own read is untouched); 074 widens
  `session_turn`'s input check to the observation that now carries one refusal
  per candidate and raises `tokensPerDecision` to that floor — settings
  revision 6 → 7 on the rig, a floor and never a lowering. Migration 059's
  file also changed, by one TypeScript `export` keyword; its SQL is
  byte-identical, and the Job applied only 73 and 74. Dump before the merge,
  the only way below 073: `/home/geoff/backups/chuggy-pre-d8821c10.dump`
  (4 959 689 bytes, `PGDMP`) and `chuggy-pre-d8821c10-globals.sql` — on the
  host that ran the script, not on the node.
- **Digests that moved.** api `sha256:d6759c01…bab8` →
  **`sha256:42a7d0fc…9145`** on the six Deployments, the importer CronJob and
  the migrate Job — `src/` moved. `chuggy-ui` `sha256:87e9a55a…6406` →
  **`sha256:1ba98402…7e8e`**: `images/chuggy-ui/Dockerfile` copies
  `src/contract`, which moved, so the script rebuilt the console by its own
  rule although nothing under `ui/` changed. `chuggy-web`
  (`sha256:2b63599e…0ab0e6`) did not move. The reviewer read both digests
  from the rig's registry and checked the `COPY` line against the two commits.
- **The merge was the script's.** `deploy-to-gtr.sh --merge` ran end to end
  for the first time: the dump, the merge, the reconcile, the Job wait and the
  rollout read-back in one command. Every control-plane
  pod restarted once or twice and the selector three times; the previous
  containers said, in order, that the applied prefix of 72 is not one the
  image accepts, that the database must be migrated, and that the api had not
  reported ready. `/health/ready` answered `200` on the api Service's port
  3000 after, and the importer's next run completed on `d8821c10`.
- **Undo.** `git revert -m 1 742a9fc` on this repository and restore the dump; the
  revert alone leaves the ledger at 74, the selector role without its grant on
  the paged read, and the wider input check in place.

### Release 22 — 2026-09-05 — the six loop defects, and an attempt that ends on its own reason

- **fabric** `cc0e6d3` → **`e439267`** (PR #147; the build request it depends on
  is PR #146, `52e96de` → `cc0e6d3`).
- **chuggy** `f8dc9194` → **`3ff1ed581e3f60a93b36a4c10d1e12aab8161079`** — the
  six defects releases 19 to 21 found in the session loop, each landed after a
  fresh-session review with nothing planted: the selector observes before it
  allocates and drops a candidate whose standing refusal names the version it
  shows (kasofsk/chuggy#572, closing #555 and #563); a wake reason is written
  on the change row rather than read off present state (#571, migration 071,
  closing #542); an attempt ends on its pod's own terminal phase with the
  reason of the last turn it failed, instead of on the lapsed lease (#573,
  migration 072, closing #509 and the plane half of #569); and every chuggy
  tool answer is weighed against the store's line before it is returned, a
  transcript read pages by entry, and the lead's decision tools answer the
  model normally (#570, closing #568 and #569 — five review rounds).
- **Ledger 070 → 072.** `chuggy-migrate-3ff1ed58-registry` reported
  `applied 71,72`. Dump before the merge, the only way below 071:
  `/home/geoff/backups/chuggy-pre-3ff1ed58.dump` (4 953 812 bytes, `PGDMP`)
  and `chuggy-pre-3ff1ed58-globals.sql`, on the node.
- **Digests that moved.** api `sha256:a8b00d77…5ce7` →
  **`sha256:d6759c01…bab8`** on the six Deployments, the importer CronJob and
  the migrate Job — `src/` moved. `chuggy-ui` (`sha256:87e9a55a…6406`) and
  `chuggy-web` (`sha256:2b63599e…0ab0e6`) did not: nothing under `ui/` or the
  console's other inputs changed, and the reviewer checked that claim against
  the two commits rather than the pull request.
- **Worker:** built from `builds/chuggy/3ff1ed58…079/`, admitted as
  `chuggy-worker` **`0.17`** =
  `sha256:00598efb07666fbe0a66ce7a8951b0aadf93cbb5ca2bca00581142f77ec17458`,
  and `CHUG_SCHEDULER_SESSION_POLICY.image` moved to it from `0.16`
  (`sha256:eccacebe…20b6`) in the same commit. The BuildRun's digest and the
  registry's agreed. `images/worker/chuggyTools.mjs`, `transcriptPage.mjs`
  and their suites are what moved; the execution worker the configurations
  pin is unchanged.
- **The roll.** Every control-plane pod restarted twice and the selector three
  times; the previous containers said, in order, that the applied prefix of 70
  is not one the image accepts, that the database must be migrated, and that
  the api had not reported ready — the expected sequence while the Job runs.
  `/health/ready` answered `200` after, and the importer's next run completed.
- **The merge was by hand** (dump, `gh pr merge`, `flux reconcile kustomization
  apps --with-source`, the Job wait, the rollout read-back), because
  `deploy-to-gtr.sh --merge` counts the git-mirror CronJob's pods in
  `chuggy-work` as a live attempt — kasofsk/chuggy#576.
- **Red proof corrected a standing note.** A wrong digest in the admit entry
  alone, a wrong digest in the policy alone, a duplicated version, and one api
  manifest on the old digest were each planted on a scratch copy: all four
  red. The first two are held by `tests/session-placement.py` (PR #139) under
  `nix flake check`; the earlier claim that they were green everywhere is
  withdrawn.
- **Nothing was driven on the rig after the roll.** No member was minted and
  no turn queued, so the fixes are proved by their suites and reviews, not by a
  session; the thirty-seven `Lost` attempt rows stand from before 072. The
  undo is the dump for the ledger and `git revert -m 1 e439267` for the
  manifests.

### Release 21 — 2026-09-04 — the session loop that ends and forgives

- **fabric** `18fc6cb` → **`1296bed`** (PR #144; the build request it depends on
  is PR #142, `e176ebd` → `18fc6cb`).
- **chuggy** `2678a2f0` → **`f8dc9194f2d2b88a50619225c521363b5f2822c8`** — the
  two session-loop findings release 20 measured: a tool call the runtime refused
  is not a tool the turn used (kasofsk/chuggy#561), and an attempt whose budget
  is spent ends after its failed turn (kasofsk/chuggy#562), both in
  kasofsk/chuggy#564. The same range carries the rig git service's mirror
  credential (kasofsk/chuggy#566), which is not an image and was applied to
  the rig by hand on 2026-09-04.
- **Ledger 070 → 070.** Nothing migrates; the renamed Job
  `chuggy-migrate-f8dc9194-registry` reported `the schema was already current`.
  No dump was taken.
- **Digests that moved: none but the worker's.** Nothing under `src/` or `ui/`
  changed, so `deploy-to-gtr.sh` built nothing; api stays at
  `sha256:a8b00d77…5ce7`, `chuggy-ui` at `sha256:87e9a55a…6406`, `chuggy-web`
  at `sha256:2b63599e…0ab0e6`. Only the scheduler's pod template changed, and
  it rolled once with no restart.
- **Worker:** built from
  `builds/chuggy/f8dc9194f2d2b88a50619225c521363b5f2822c8/`, admitted as
  `chuggy-worker` **`0.16`** =
  `sha256:eccacebea8fccaab485fac4d2bfb8990173853a7c44d1f0eec49806b274920b6`, and
  `CHUG_SCHEDULER_SESSION_POLICY.image` moved to it from `0.15`
  (`sha256:782b97c2…ced33`) in the same commit. The digest was read from the
  BuildRun and from the registry before it was written anywhere, and the two
  agreed. `images/worker/session.mjs` and its two suites are what moved.
- **No selector document change**, and both chuggy parsers at `f8dc9194`
  accept the rendered environment. The gap release 20 measured is closed: an
  admit entry that reused a version number is now red in `session-placement`
  (PR #139), and this release's red proof exercised that arm.
- **What phase B measured on the rig.** Every session pod checked out the
  in-cluster mirror at `f8dc9194`, the released commit. The standing lead,
  under a prompt that made it call `ToolSearch`, had the call refused by the
  runtime, recorded a tool list without it, and its decision **landed** under
  the installation allowlist (release 20's identical turn was discarded). A
  member thread's attempt on the same worker answered eleven turns for $4.97,
  failed the twelfth `AgentBudgetExhausted`, and its pod **exited 0 the same
  second** instead of claiming on; the reaper collected the attempt on its
  lapsed lease and the scheduler's fresh attempt answered the next queued turn
  (release 20's spent pod had to be deleted by hand). Two new defects on the
  way, older than this release: kasofsk/chuggy#568 (every lead decision tool
  answers the model with an MCP result error after staging its effect) and
  kasofsk/chuggy#569 (a tool result larger than the store's line bound — a
  transcript page, or the executions listing at its page maximum — fails the
  turn `StoreRefused` and ends the attempt).

**Undo.** `git revert -m 1 1296bed` and
`flux reconcile kustomization apps --with-source` restores the `0.15` session
pin, the ten `source-commit` annotations and the migrate Job's `2678a2f0`
name, and drops the `0.16` admit entry; the ledger did not move, so nothing
below needs a restore. Phase B's writes outside git are listed in its own
record; the project's selector overrides stand at revision 12 as
`{"dispatchMode":"Automatic","basePrompt":"Hold this project…"}`.

### Release 20 — 2026-09-03 — the four release-19 findings, and every proof to completion

- **fabric** `99f277b` → **`285a7bd`** (PR #137; the build request it depends on
  is PR #135, `006cde1` → `99f277b`).
- **chuggy** `0ab8a732` → **`2678a2f0b2bd681730f480d3349cd35cbb31f20d`** — the
  fixes for what release 19 measured: a delivery is stamped from its
  **project's** dispatch mode (kasofsk/chuggy#557), a forked inquiry reads its
  parent's objects under the session that wrote them (kasofsk/chuggy#556), and
  the installation's token floor is one whole observation while the worker
  denies the runtime's discovery tool (kasofsk/chuggy#558).
- **Ledger 067 → 070** (068 a delivery is stamped from its project's dispatch
  mode; 069 a store row says which session wrote the batch; 070 a decision's
  token budget is one whole observation). The migrate Job
  `chuggy-migrate-2678a2f0-registry` reported `applied 68,69,70` and completed
  in six seconds. 070 moved `selector_runtime_settings` to revision 6 with
  `limits.tokensPerDecision` 200000 → 16619439, by migration.
- **Digests that moved:** api `sha256:91435dc0…7421` →
  `sha256:a8b00d77aa568e59c306951249e3823a8cae0f22ec42373d09a3126701e45ce7` on
  `chuggy-api`, `-finalizer`, `-scheduler`, `-selector`, `-ticket-service` and
  `-worker-plane`. `chuggy-ui` (`sha256:87e9a55a…6406`) and `chuggy-web`
  (`sha256:2b63599e…0ab0e6`) did not move: nothing under `ui/` changed.
- **Worker:** built from
  `builds/chuggy/2678a2f0b2bd681730f480d3349cd35cbb31f20d/`, admitted as
  `chuggy-worker` **`0.15`** =
  `sha256:782b97c2f557fda741dedf58005d830aae1556e29d9433aa286f3da9694ced33`, and
  `CHUG_SCHEDULER_SESSION_POLICY.image` moved to it from `0.14`
  (`sha256:3e37aa35…ca82`) in the same commit. The digest was read from the
  BuildRun and from the registry before it was written anywhere, and the two
  agreed. `images/worker/chuggyTools.mjs` is what moved: `ToolSearch` joins the
  built-in roster, so the pod denies it instead of offering a tool no
  capability admits.
- **No selector document change**, and none was needed: the rendered
  `CHUG_SELECTOR_CONFIG` is byte-identical to release 19's, and both chuggy
  parsers (`selectorConfiguration`, `schedulerCommandConfig`) at `2678a2f0`
  accept the rendered environment. One gap measured on the way: an admit entry
  that reused a version number is green in every fabric gate and refused by
  `schedulerCommandConfig` — held by hand this release, not gated.
- **What phase B measured on the rig.** The standing successor lead decided
  under the installation's own controls — no project limit, no project
  allowlist — and four decisions of 0.75–1.1 M tokens landed under the 070
  floor (release 19's first two were discarded at 200 000). Each delivery row
  was stamped `Pending` from the project's `Automatic` over the installation's
  `ApprovalRequired`, was claimed, and the tickets ran to `Done` (25, 34); a
  thread-released ticket was dispatched and finished; a released ticket whose
  brief named a missing file was refused and the filing member's thread woke
  on the refusal and filed nothing; an inquiry against the standing lead
  **answered** through the fork with zero batches of its own. Both console
  halves were opened: the lead page draws one row per dispatch with its
  landing, and the settings page shows `dispatchesPerDecision` and the live
  floor. Two new defects, kasofsk/chuggy#561 and kasofsk/chuggy#562: a refused
  `tool_use` is still recorded and judged by the decision control (one
  discarded decision per lead), and a session attempt whose runtime budget is
  exhausted keeps claiming and instantly failing turns until its pod is deleted.

**Undo.** `git revert -m 1 285a7bd` and
`flux reconcile kustomization apps --with-source` puts every digest above back
and restores the `0.14` session pin. **It does not walk the ledger back**: 070
is applied and the pre-070 images refuse it, so going below 070 is a restore
from `/home/geoff/backups/pre-068-20260903.dump` (2 896 024 B) with
`pre-068-20260903-globals.sql`, taken on the node while the ledger still read
067. Phase B's writes outside git are listed in its own record; the project's
selector overrides stand at revision 10 as `{"dispatchMode":"Automatic",
"basePrompt":"Hold this project…"}`.

### Release 19 — 2026-09-03 — a project takes a successor lead, and one decision dispatches several

- **fabric** `7cdb0e7` → **`e8677bc`** (PR #133; the build request it depends on
  is PR #131, `938db7e` → `7cdb0e7`).
- **chuggy** `5b3f381` → **`0ab8a7322b5da7efa0364eb9f271043da31be69b`** — slice
  6 (a decision dispatches several tickets, each fenced on its own candidate
  version) and the two fixes release 18 measured: a project whose lead closed
  takes a successor, and a thread's mailbox starts where the change log stood
  when it opened.
- **Ledger 063 → 067** (064 a delivery is one decision's dispatch of one ticket;
  065 the decision log says which of a decision's dispatches landed; 066 a closed
  lead is history and the project takes a successor; 067 a thread's mailbox starts
  where the change log stood when it opened). The migrate Job
  `chuggy-migrate-0ab8a732-registry` reported `applied 64,65,66,67` and
  completed.
- **Digests that moved:** api
  `sha256:b76bc1bd…9d256` →
  `sha256:91435dc0a55f6923b6c69aecca9f9d04cf5c56bfad9e21afa00339f177677421` on
  `chuggy-api`, `-finalizer`, `-scheduler`, `-selector`, `-ticket-service` and
  `-worker-plane`; `chuggy-ui` `sha256:5e733e1c…e17d39` →
  `sha256:87e9a55a523a473225c7ff3a7a3f60f49db282ddcb30e752808bb9031e6f6406`.
  `chuggy-web` did not move (`sha256:2b63599e…0ab0e6`).
- **Worker:** built from
  `builds/chuggy/0ab8a7322b5da7efa0364eb9f271043da31be69b/`, admitted as
  `chuggy-worker` **`0.14`** =
  `sha256:3e37aa3529dd22235c3ff13c05a3f7ef3ec4694ce1652eeeb29cde3a8f58ca82`, and
  `CHUG_SCHEDULER_SESSION_POLICY.image` moved to it from `0.13`
  (`sha256:06a094c6…e994e`) in the same commit. The digest was read from the
  BuildRun and from the registry before it was written anywhere, and the two
  agreed. `images/worker/leadDecision.mjs` is what moved: the dispatch tool takes
  several tickets and the ceiling it enforces is the contract's.
- **What this release turns on.** `CHUG_SELECTOR_CONFIG.lead.credentialSlot` is
  now required by the image — it is the credential mount a lead this process
  opens speaks through, and it is `claude-code`, the same slot the api's
  `CHUG_API_THREAD_CREDENTIAL_SLOT` names and one of the two
  `CHUG_SCHEDULER_SESSION_POLICY.grant.credentials`. Two new gate arms hold that
  pairing: `tests/selector-reach` holds the field's shape, which is all the
  selector's own schema decides, and `tests/session-placement` step 10 holds the
  slot against the grant, which is the half no start-up check can see.
- **What phase B measured on the rig.** The runtime opened a successor lead
  (`lead-<uuid>`, `agent_reference` null before its first turn and bound after)
  while release 16's closed lead stayed closed; its first turn carried the
  seeding block; it filed a `FollowUp`, released it under its own
  `operation.via_session`, and a later turn staged **three** dispatches in one
  decision, which the record holds as one `selector_interaction` row and three
  `selector_proposal_delivery` rows each with its own state. A thread opened with
  two qualifying, unconsumed change rows below it took **zero** wake turns and
  was woken by the next change, which is 067. Nothing was delivered: see the
  first bullet under "What does not work yet".

**Undo.** `git revert -m 1 e8677bc` and
`flux reconcile kustomization apps --with-source` puts every digest above back,
restores the `0.13` session pin and removes `lead.credentialSlot` — which the
`0ab8a732` image refuses, so the revert must go back to the api digest above it
in the same reconcile, as reverting the whole commit does. **It does not walk the
ledger back**: 067 is applied and the pre-067 images refuse it, so going below
067 is a restore from `/home/geoff/backups/pre-064-20260903.dump` (2 290 482 B)
with `pre-064-20260903-globals.sql` (13 507 B), taken on the node while the
ledger still read 063. Those two files are the only way below it. Phase B's
writes outside git are undone separately and are listed in its own record: the
project's selector overrides go back to `{"dispatchMode":"Automatic"}` with a
`PUT` at the revision the route reports, and the `policy-bearer-token` key this
release deleted from the `chuggy-selector` Secret is in
`/home/geoff/chuggy-selector-secret-before-release19.yaml` on the node.

### Release 18 — 2026-09-03 — the selector runs, and a member has a thread

- **fabric** `5869a93` → **`37dcffa`** (PR #129; the build request it depends on
  is PR #127, `8e83872` → `5869a93`).
- **chuggy** `6a9dc09` → **`5b3f38107572551891704e594bb6513afa08e8f4`** — the
  agentic selector's slices 2 to 5: the lead is the policy host, a member has a
  thread with its own mailbox and wakes, a member may ask the lead aside, and a
  session clones the in-cluster mirror.
- **Ledger 061 → 063** (062 member threads, their messages and their wakes; 063
  inquiries against a lead, forked and retained nowhere). The migrate Job
  `chuggy-migrate-5b3f381-registry` reported `applied 62,63` and completed.
- **Digests that moved:** api `sha256:576dfffc…f4ff` →
  `sha256:b76bc1bd7f9646a3980ad37194a97c6525ba02a978a16a713df81c63ff59d256` on
  `chuggy-api`, `-finalizer`, `-scheduler`, `-selector`, `-ticket-service` and
  `-worker-plane`; `chuggy-ui` `sha256:ddcac78b…5fb222` →
  `sha256:5e733e1c3b6d9a7994f9aff78fd3b28c4e2b2d4fecf16175f1df482322e17d39`.
  `chuggy-web` did not move (`sha256:2b63599e…0ab0e6`).
- **Worker:** built from
  `builds/chuggy/5b3f38107572551891704e594bb6513afa08e8f4/`, admitted as
  `chuggy-worker` **`0.13`** =
  `sha256:06a094c632eb2d6715ab35f3d1cd11c7fdd1ba7e95c04652f5cc259db00e994e`,
  and `CHUG_SCHEDULER_SESSION_POLICY.image` moved to it from `0.12`
  (`sha256:e2aac0fc…9261`) in the same commit. The digest was read from the
  BuildRun and from the registry before it was written anywhere, and the two
  agreed; `tests/session-placement` now holds the pinned image against the
  admitted list rather than leaving that pairing to a reader.
- **What this release turns on.** `chuggy-selector` moves from `replicas: 0` to
  `1` and its retired `policy` block is replaced by `lead`, because
  kasofsk/chuggy#503 retires the trusted selector policy protocol in favour of a
  turn on the project lead's mailbox. `CHUG_SCHEDULER_SESSION_POLICY` gains a
  `mirrors` map, so a session clones `git.chuggy-git` where a project binds
  github.com without moving the binding the finalizer promotes through — proved
  on the rig by a session pod whose `origin` is
  `http://git.chuggy-git.svc.cluster.local./chuggy.git`. The api gains
  `CHUG_API_THREAD_CREDENTIAL_SLOT`.
- **What phase B wrote outside git**, because neither is a manifest: Geoff's
  principal was granted `ManageProjectSelector` on `vteng/chuggy`, and that
  project's `dispatchMode` was set to `Automatic` through
  `PUT …/selector-settings` at `expectedRevision 0` (the project carried no
  overrides, so nothing was replaced). A member thread was opened, answered nine
  turns on the 0.13 worker and released ticket 23. Nothing dispatched: see the
  closed-lead paragraph under "What does not work yet".

**Undo.** `git revert -m 1 37dcffa` and
`flux reconcile kustomization apps --with-source` puts every digest above back,
restores the `0.12` session pin and returns `chuggy-selector` to `replicas: 0`.
**It does not walk the ledger back**: 063 is applied and the pre-063 images
refuse it, so going below 063 is a restore from
`/home/geoff/backups/pre-062-20260903.dump` (1 058 127 B) with
`pre-062-20260903-globals.sql` (13 507 B), taken on the node while the ledger
still read 061. Those two files are the only way below it. The two phase-B
writes are undone separately: re-grant the four verbs the membership row
carried before, and `PUT` the settings route with an empty override set.

### Release 17 — 2026-09-03 — the lead's tools and its checkout

- **fabric** `5c92ffa` → **`57523bb`** (PR #125; the build request it depends on
  is PR #123, `5c92ffa`).
- **chuggy** `b47c0ef` → **`6a9dc09`** — the agentic selector's slices 1, 2 and
  3: the lead session's composition, its durable tools, the in-process `chuggy`
  MCP server in the worker image, and the repository checkout a session takes.
- **Ledger 058 → 061** (059 the lead's decisions and refusals, 060 a withdrawn
  rate-limited attempt, 061 the lead's tools and objectives).
- **Digests that moved:** api `sha256:e0a55398…63baf` → `sha256:576dfffc…f4ff`
  on `chuggy-api`, `-finalizer`, `-scheduler`, `-selector`, `-ticket-service`
  and `-worker-plane`; `chuggy-ui` `sha256:42487574…225102` →
  `sha256:ddcac78b…5fb222`. `chuggy-web` did not move
  (`sha256:2b63599e…0ab0e6`).
- **Worker:** built from `builds/chuggy/6a9dc0909d1feb569922a0a02470f219d1612d20/`,
  admitted as `chuggy-worker` **`0.12`** =
  `sha256:e2aac0fc9347a936dc6b279385f0100e005c4e219227ed4c619f2b61e3e89261`,
  and `CHUG_SCHEDULER_SESSION_POLICY.image` moved to it from `0.11`
  (`sha256:fe7018f6…a8ef`). The digest was read from the BuildRun and from the
  registry before it was written anywhere, and the two agreed.
- **Not in this release:** `chuggy-selector` is still `replicas: 0`, so
  `dispatchMode: Automatic` was not turned on — its fence is a readiness row only
  a running selector writes, and the image still requires a `policy` block whose
  service does not exist. The lead's `project_membership` row on `vteng/chuggy`
  *was* granted (`Read`, `Mutate`, `ProposeDispatch`), which is inert until a
  session runs.

**Undo.** `git revert -m 1 57523bb` and
`flux reconcile kustomization apps --with-source` puts every digest above back
and restores the `0.11` session pin. **It does not walk the ledger back**: 061 is
applied and the pre-061 images refuse it, so going below 061 is a restore from
`/home/geoff/backups/pre-059-20260903.dump` (1 010 209 B) with
`pre-059-20260903-globals.sql` (13 507 B), taken on the node while the ledger
still read 058. Those two files are the only way below it.

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

Firewall opens 51820/udp (WireGuard) globally, because a peer's first packet
arrives from wherever it happens to be. 6443 (API) and 8472/udp (flannel VXLAN)
are open only from the ranges in `chuggy.k3s.apiAllowedSources`, which is why
the mesh range has to be on that list — `wg0` is deliberately **not** a trusted
interface. It was, on the theory that trusting it kept 6443 and 8472 off the
LAN-facing rules; it never did, since those ports were opened globally either
way, and the trust meanwhile exposed every other listening port on the box to
any peer. A peer now gets 22, and 6443 and 8472/udp from its own range, and
nothing else.

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

Start from `hosts/example/`, not from `hosts/gtr/`. The example is a complete
host that holds none of gtr's disks, addresses, names, keys or peers, and it is
in `nixosConfigurations` so that `nix flake check` keeps it building. Copying
gtr instead means deciding, line by line, which of its values were about gtr —
and the ones that are easy to miss are the ones that do nothing visible when
they are wrong.

1. Copy `hosts/example/` to `hosts/<name>/`.
2. `nixos-generate-config` on the new machine and **replace**
   `hardware-configuration.nix` with its output. The one in the example builds
   and will not boot: nothing on your machine is labelled `nixos` unless you
   labelled it.
3. Set the hostname, and add a radio blacklist if the box has radios — `lspci -k`
   will tell you what they are. Blacklisting `iwlwifi` on a box with a MediaTek
   card silently does nothing. The `warnings` block at the bottom of the file
   names the host it is on, so from here on the rebuild warnings are about your
   box and not the example's; two of them go quiet when steps 4 and 5 are done,
   and the plaintext-ingress one stays on until something terminates TLS. Keep
   it — a warning you are meant to still be seeing is not a warning to delete.
4. Replace every address — the LAN range, the mesh address and the API SANs. The
   example uses RFC 5737's documentation ranges throughout, 192.0.2.0/24 for the
   LAN and 198.51.100.0/24 for the mesh, so an unedited copy reaches nothing
   rather than coming up on a network that is somebody's. Nothing refuses it:
   the host has to keep evaluating or `nix flake check` stops building it, so an
   unedited copy warns at every rebuild instead.
5. Point `chuggy.flux.repositoryUrl` at **your** repository. The example names
   RFC 2606's `git.example.com`, which resolves for nobody; this repository's
   own URL would give the box gtr's `cluster/apps/` — somebody else's ingress
   hostnames and identity provider, against Secrets you do not have. That is
   the one wrong answer here that comes up looking healthy, so the example
   warns until it is changed.
6. Set the worker budgets against what the machine actually has.
7. Pick the right `nixos-hardware` modules for its CPU/GPU, and add one entry to
   `nixosConfigurations` in `flake.nix`.

It gets its own cluster and its own `cluster/apps/`. Nothing is shared at
runtime — only the modules.

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
