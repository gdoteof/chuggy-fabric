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
    modules/github-app-token.nix    rotating App tokens, chuggy.githubAppTokens.*
    modules/chuggy-images.nix       bootstrap image delivery, chuggy.images.*
    modules/chuggy-work.nix         what one task may cost, chuggy.work.*
    modules/mini-chuggy.nix         complete co-located single-node role

    modules/cloudflare-tunnel.nix   public ingress, with chuggy.tunnel.* options
    modules/ddns.nix                the mesh endpoint's A record, chuggy.ddns.*
    modules/flux.nix                bootstraps Flux, chuggy.flux.*

    cluster/flux-system/            the vendored Flux install
    cluster/flux/                   what Flux reconciles, one Kustomization
                                    each, and the two sources of a release
    cluster/apps/                   the cluster state the `apps` layer
                                    applies: no part of a chuggy release
    cluster/apps/kustomization.yaml the enumeration of that state, and the
                                    generated ConfigMaps
    cluster/apps/ory/               config documents those ConfigMaps carry --
                                    not manifests, and not in `resources`
    cluster/chuggy-migrate/         a chuggy release's migration Job, and the
                                    dump it takes first
    cluster/chuggy/                 a chuggy release's services; a release is
                                    made over these two, and names itself in
                                    neither

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

What `cluster/` declares is deliberately less than what the cluster runs.
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
repo. What this repo owns carries the name of a layer `cluster/flux/` declares
— `apps`, `build-system`, `chuggy-migrate` or `chuggy` — in `namespace:
flux-system`. Anything else, labelled or not, came from somewhere that is not
this repo.

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
| `chuggy.state.dumps.path` | `chuggy-state.nix` | database dumps on an incidental filesystem |
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
that they do; a mismatch mounts an empty directory and reports healthy. For the
dumps directory the same pair is checked: `tests/dumps-wiring.nix` holds
`chuggy.state.dumps.path` on gtr to the volume `cluster/apps/chuggy-dumps.yaml`
declares, and `tests/rollout-order.nix` holds the directory's owner to the uid
the migration Job's `dump` container writes as.

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

PostgreSQL role passwords, the API's idempotency keying material and two
report tokens are generated once on the host, under a root-only directory
outside the Nix store, and synchronised into Kubernetes Secrets in the `chuggy`
namespace.

A report token is what a report of a declared action is proved with:
`chuggy-report-flux` holds a key a report is signed under, `chuggy-report-build`
a bearer one presents, each under the key `token`. The bearer alone is
synchronised into `chuggy-build` as well, where a build's pods run. Everything
below holds for that copy: host state is the one value, each namespace's
Secret is compared with it, and none is written over.

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

### GitHub App credentials

`chuggy.githubAppTokens` mints repository-scoped installation tokens into
managed Kubernetes Secrets, one for each entry of `tokens` a host declares. No
host here declares one or enables the delivery: gtr states the two Apps and
where their keys are, which `tests/forge-app-key.py` reads, and the keys remain
root-only host state outside this repository and the Nix store.

No pod is handed a repository's credential on a forge: the api, the ticket
service, the finalizer and the importer each mount a GitHub App's private key
and mint for the act they are performing, and a work pod's is minted for it by
the worker plane. The exception is this cluster's own git service, which no App
covers — `chuggy-git-worker` is mounted into work and session pods and named in
the one row of the scheduler's repositories map, and `chuggy-finalizer-credentials`
is the finalizer's for `rig.git`. Both are made by hand. On a host that does
declare a token, verify the refreshers and Secrets after switching — the unit
is named for its entry, and the Secret carries the label the module puts on
everything it manages:

    systemctl list-units --all 'chuggy-github-app-token-*-refresh.service'
    kubectl get secret --all-namespaces -l chuggy.dev/managed-by=github-app-token

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

Worker pools outside the cluster pull from `registry-public` instead: a second
Distribution serving the same volume read-only at
`chuggy-registry.vteng.io/v2`, where Traefik puts every request to the pool
plane's `/registry/authorize` first. `cluster/apps/registry-public.yaml` is the
front and `tests/registry-public.py` holds it read-only; the host is public
only once it is also a tunnel hostname with a CNAME, as `chuggy-ui.yaml`'s
"the host, three ways" describes.

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
ends up in `systemctl --failed` instead of looking busy forever. `chuggy-build`
belongs to `cluster/build-system/` and is waited for the same way, after
everything `chuggy` is owed has been written. The bound is
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
into the node's own containerd and stops -- its header says it deploys nothing.
A release's two images need none of this: [the release
pipeline](#the-release-pipeline) builds and pushes them. This is how an image
built any other way reaches the registry.

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
phase did not see. `registry-public` never writes and need not be stopped.
Verify every retained release digest again after the registry returns.

Rollback of an image a manifest names by digest changes only that digest. Keep
the previous manifest in the registry, restore that digest in the workload
declaration, and let Flux reconcile it. A release's two images are named by no
manifest in Git, and going back is [another
release](#operating-a-release). Rolling the registry Deployment back cannot recover deleted
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

### Where a build runs

`cluster/build-system/` installs pinned Tekton and the [release
pipeline](#the-release-pipeline), and nothing else here builds an image. A run
places its pods by the first of these node properties and tolerates the
second:

    chuggy.k3s.nodeLabels = [ "chuggy.dev/node-role=builder" ];
    chuggy.k3s.nodeTaints = [ "chuggy.dev/node-role=builder:NoSchedule" ];

By default that node is a dedicated security boundary: the build step is
rootless BuildKit, and RootlessKit requires unconfined seccomp and AppArmor and
permits privilege escalation for user-namespace setup. A dedicated host can
import `examples/builder-node.nix`; the committed fragment wires both
properties.

A self-contained host instead imports `examples/mini-chuggy-node.nix`. The
`chuggy.mini` role enables k3s, durable state, secrets, images, work, Flux, and
the builder label, but deliberately adds no builder taint: tainting the only
node would exclude the ordinary workloads that make the deployment
self-contained, so a build there shares its node with them. The host must
still state its own storage paths, API source ranges, worker budget, and Flux
repository; start with `hosts/example/`, replace its inert values, and add the
mini example module to that host's `extraModules` in `flake.nix`.

### The release pipeline

A chuggy release is one OCI artifact, and it is all the `chuggy-migrate` and
`chuggy` layers apply. Git names no release: `cluster/chuggy-migrate` and
`cluster/chuggy` are what one is made over, every line there that names one of
its two images carries a digest no image has, and `.chug/tasks/ci.sh` refuses a
release written into them. `cluster/chuggy/chuggy-ticket-service.yaml` argues
that. The trigger below starts each run.

A `PipelineRun` of `chuggy-release` in `chuggy-build` takes two repositories and
two full commit hashes and nothing else. It builds chuggy's API and console
images at the chuggy commit with rootless BuildKit, reusing an image the
registry already serves under that commit's tag, and then publishes one OCI
artifact to `chuggy/release` in the release registry: the fabric commit's
`cluster/chuggy-migrate` and `cluster/chuggy`, and beside them
`release/chuggy-migrate` and `release/chuggy`, two generated kustomize overlays
that write the two digests, the source-commit annotation and the migrate Job's
name. `OCIRepository` `chuggy-release` selects the highest version published,
and the two layers apply those overlays from it: the migration and then the
services, in the order [The chuggy control plane](#the-chuggy-control-plane)
gives. No task pod mounts a ServiceAccount token, and no policy gives one a
route to the API server.

**A release is two commits, this repository's and chuggy's, each the one its
source held when the run was started.** A change under the two directories
therefore reaches the cluster with the next release and not at its merge. A
change there and the chuggy commit that needs it -- a configuration key an
image requires and the image before it refuses -- are one release only when
both have landed before a run starts, and the trigger does not wait for the
second. So each of the two is written to be released without the other, or the
trigger is stopped as below while both land.
`cluster/apps` is no part of a release and is applied at its merge, so a change
there that the running release cannot live under goes in two commits, which
`cluster/flux/chuggy-migrate.yaml` argues.

The release registry is `release-registry` in `chuggy-registry`, a second
Distribution on the registry's volume, under a root of its own. It admits the
pods of the `publish-release` Task and Flux's source-controller. A build pod
does not reach it; `cluster/build-system/release-pipeline.yaml` says what one
can still write.

An operator reaches it from the node, by its Service's address, as
`Registry operations` reaches `registry`:

    kubectl -n chuggy-registry get service release-registry
    curl -s http://<cluster-ip>:5000/v2/chuggy/release/tags/list

A release is taken back by deleting it there. The registry deletes by digest,
which the version's manifest answers with, and every tag of that digest goes
with it:

    curl -sI -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
      http://<cluster-ip>:5000/v2/chuggy/release/manifests/<version> \
      | grep -i docker-content-digest
    curl -s -o /dev/null -w '%{http_code}\n' -X DELETE \
      http://<cluster-ip>:5000/v2/chuggy/release/manifests/<digest>

`202`, and within its interval `chuggy-release` selects the highest version
left and the two layers apply it: taking a release back is a rollout of the
one before it, and [going back](#operating-a-release) says what that cannot
cross. With none left the source keeps the artifact it last held, the layers
stay on it, and it reports that no version matches. The trigger does not
publish the release again while its newest run is the one that published it,
which `trigger.sh` argues.

The `release-trigger` CronJob, in a namespace of its own, is the one part that
reads the API server. Each time it runs it compares what `GitRepository`
`chuggy` and `fabric-release` hold with the newest run and creates at most one,
from `release-run.yaml`. Two admission policies beside it hold what its token
creates to that file, for the address and the commit each source holds. While
either source is missing the second refuses every `PipelineRun`, whoever
creates it and in any namespace, with `no params found for policy binding`.
A person can run that same comparison at any time, as [Operating a
release](#operating-a-release) starts one.

The CronJob is the `build-system` layer's, which puts its `suspend` back to
what Git declares at its next pass. So stopping the trigger for a while starts
by taking the object from the layer:

    kubectl -n chuggy-release-trigger annotate cronjob release-trigger \
      kustomize.toolkit.fluxcd.io/reconcile=disabled
    kubectl -n chuggy-release-trigger patch cronjob release-trigger \
      --type merge -p '{"spec":{"suspend":true}}'

That starts no further Job and stops no run already started. While the
annotation is there the layer applies nothing to the CronJob, and still
prunes around it: a commit that changes `trigger.sh` or `release-run.yaml`
renames their ConfigMap, and an annotated CronJob that is not suspended then
names one that is gone, and fails each minute. Removing the annotation gives
the object back, and at the layer's next pass it is what Git declares:

    kubectl -n chuggy-release-trigger annotate cronjob release-trigger \
      kustomize.toolkit.fluxcd.io/reconcile-

A stop that is to outlast that is a commit: `suspend: true` in
`cluster/build-system/release-trigger.yaml`, and `"suspend": True` in
`TRIGGER_TIMING` in `tests/release-pipeline.py`, which refuses the stop until it
is written there as well.

#### Operating a release

**Starting one.** The trigger starts a run in the minute it reads that the two
sources hold something the newest run did not release. While it is stopped a
person runs its comparison once, and its log says what it started or why it
started nothing:

    kubectl -n chuggy-release-trigger create job --from=cronjob/release-trigger by-hand-1

Then, in the order things happen:

    kubectl -n chuggy-build get pipelineruns
    flux get sources oci chuggy-release
    flux get kustomizations
    kubectl -n chuggy get jobs

The run succeeds; the source holds a new revision; `chuggy-migrate` applies it
and waits for the Job named for chuggy's commit; `chuggy` applies it once that
Job has completed. The **Chuggy releases** dashboard shows the same.

**Cancelling a run.**

    kubectl -n chuggy-build patch pipelinerun <run> --type merge \
      -p '{"spec":{"status":"Cancelled"}}'

It ends failed, having published nothing. The next comparison retries a failed
run once `RETRY_DELAY_SECONDS` in `release-trigger.yaml` have passed, or at
once if the run has been deleted.

**Stopping a published release from applying.**

    flux suspend kustomization chuggy-migrate chuggy

Both, so that neither half of a release is applied without the other. The root
declares no `suspend` on either and leaves the field as `flux` set it; set with
`kubectl`, it is put back at the root's next pass. The source goes on reading
releases, and nothing more is applied or pruned until

    flux resume kustomization chuggy-migrate chuggy

which applies the highest version there is by then. A Job the first layer had
already created runs on.

**Holding the cluster at one release** is a commit: `digest: sha256:<the
artifact's>` added to `ref` in `cluster/flux/sources.yaml`, which the source
reads in preference to the range, and to `SOURCES` in `tests/flux-layers.py`,
which refuses the pin until it is written there as well. The digest is the half
after the `@` of the revision the source holds, and the whole of that revision
while the pin stands:

    kubectl -n flux-system get ocirepository chuggy-release \
      -o jsonpath='{.status.artifact.revision}'

`flux get sources oci` prints the digest cut short, and a digest cut short is
one the source refuses: it goes not ready and reads no release. An earlier
release's digest is the `digest` result of the run that published it:

    kubectl -n chuggy-build get pipelinerun <run> \
      -o jsonpath='{.status.results[?(@.name=="digest")].value}'

Pinned to the release the cluster runs, nothing is applied; pinned to an earlier
one, that release is applied over the later, which is going back to it and
cannot cross what going back cannot. Runs go on publishing while it stands, and
reverting the commit applies the highest.

**Going back** is a revert on chuggy's `main`, and what releases it is a
release like any other: its images are built, the dump is taken, and the Job
runs under the revert's own commit. A revert of a change under the two
directories here is the same. **Back across a migration is not available.** An
image built from before a migration declares a ledger shorter than the
database's, so its Job applies nothing and fails, `chuggy` reports
`DependencyNotReady`, and the services stay on the release they were running
until one whose image declares that migration replaces the Job. The dump taken
before the migration is on the `chuggy-dumps` volume, and nothing restores it.

**A layer inside its wait reads nothing new.** While `chuggy-migrate` waits
for its Job or `chuggy` for a roll, a release published since, a commit to the
layer and a `flux reconcile` are all taken up only when that wait ends: when
the Job or the roll succeeds or fails, or at the layer's `timeout`. A Job whose
pod cannot pull its image does neither, and deleting it does not end the wait.
This does, and each layer then starts from what Git and the source hold:

    kubectl -n flux-system rollout restart deployment kustomize-controller

**A release published while the source is failing is not read within its
interval.** `interval` is how often a source that is ready looks again. One
whose last read failed -- the registry down, the node just started, no version
there -- is asked again by source-controller after a delay that doubles with
each failure, up to its `--max-retry-delay`: fifteen minutes by Flux's default,
and `cluster/flux-system/gotk-components.yaml` sets no other.
`flux get sources oci chuggy-release` says whether it is failing and what it
last read, and this asks at once:

    flux reconcile source oci chuggy-release

**A release registry that holds nothing while the newest run released** -- its
directory lost, or its one release deleted -- is a source that stays not
ready, because the trigger does not publish again what its newest run
published. The layers stay at what they last applied, and on a cluster that has
applied nothing they apply nothing. Delete that run and start the comparison:

    kubectl -n chuggy-build delete pipelinerun <run>

Where `registry` still serves the two images, what the new run publishes is the
release that was lost, byte for byte: the same digest under a higher version.
The layers apply it and change nothing.

**A fresh box has no release until the trigger starts its first.** Until one
is published `chuggy-release` reports that the registry does not know the
repository, and the two layers report `Source artifact not found`. The trigger
starts that run once `build-system` is Ready and `GitRepository` `chuggy` and
`fabric-release` each hold a revision, without which it starts nothing and says
so. The Job of that release migrates the database as soon as it is published,
and nothing waits for [Before any of it runs](#before-any-of-it-runs): a box
that needs any of that done first has the two layers suspended, as above,
until it is. That release is published while the source is failing, so it is
read as the paragraph above describes.

The scripts a pod runs are files beside the manifests — `fetch.sh`, `build.sh`,
`publish.sh`, `report.sh` and `trigger.sh` — and each argues its own rules in
its header. `tests/release-trigger.nix`, `tests/release-build.nix`,
`tests/release-publish.nix`, `tests/release-report.nix` and
`tests/release-pipeline.nix` run those bytes and hold the manifests.

A run's last task, `report`, tells chuggy how each of the other three ended:
one report a task, to the action of that task's name, as the reporter whose
bearer is the Secret `chuggy-report-build`. It is the one task pod given a
Secret, and it runs nothing a commit wrote. A report is no part of a release.
A `report` that fails, or runs past its own bound, leaves its run succeeded,
which `release-pipeline.yaml` argues, and what chuggy answered is a line a
report in that pod's log, which the release dashboard shows on the run's page.

What a release came to on this cluster Flux tells chuggy itself, as the action
`rig`. `cluster/apps/chuggy-rollout-reports.yaml` has notification-controller
post the `chuggy` layer's events and the `chuggy-migrate` layer's errors to the
API, signed with the Secret `chuggy-report-flux`, and chuggy records the last
layer's success, or either's failure, against the chuggy commit the release was
built from. Flux keeps no queue: a report that met an outage is lost, and the
layer says what it came to again at its next pass. A delivery chuggy refused,
or one that did not arrive, is an error in notification-controller's log and,
while the cluster keeps the event, a Warning on its Alert:

    kubectl -n chuggy get events --field-selector involvedObject.kind=Alert

A trigger that is not suspended and has stopped succeeding fires
`ReleaseTriggerNotSucceeding`, from `cluster/apps/release-trigger-alert.yaml`,
which `tests/release-alert.nix` evaluates. Like every alert here it is
[found by looking](#alerts-evaluate-and-go-nowhere).

`worker-image-run.yaml` is a `TaskRun` of the same `build-image` Task that
builds the worker image at a chuggy commit. Flux applies neither it nor
`release-run.yaml`; an operator writes the commit into it and creates it:

    sed 's/@chuggy-commit@/<full commit hash>/' cluster/build-system/worker-image-run.yaml |
      kubectl create --filename -

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

Cluster state is reconciled by **Flux**, not applied by hand. What
`cluster/flux/` names is the desired state; if the cluster drifts from it, Flux
corrects it.

### Three layers, three change rates

| Layer | What | Changes | Applied by |
|---|---|---|---|
| Machine | OS, k3s itself, cloudflared, WireGuard | rarely | `nixos-rebuild` |
| Cluster | apps, ingresses, addons | constantly | Flux, continuously |
| Release | chuggy's two images and its control plane's manifests | per release | Flux, from a published artifact |

Machine and cluster share this repo because for a single-node cluster they are
one unit of reproducibility: clone, `nixos-rebuild switch`, and the box *and* its
workloads exist. `hosts/<name>/` and `cluster/` sit side by side for the same
reason. chuggy's control plane is the one part that is not there after that
command: its manifests are in this repo, under `cluster/chuggy-migrate` and
`cluster/chuggy`, and what applies them is [a release](#the-release-pipeline).

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
cluster from one command, less chuggy's control plane, which waits for [the
first release](#operating-a-release).

This deliberately is **not** `flux bootstrap`. That command wants provider write
scope so it can commit manifests and create a deploy key, while those manifests
are already committed here. The current public source needs no credential. A
private source instead names a separately provisioned, read-only Secret with
`chuggy.flux.secretRef`; credential material never enters the Nix store. A new
machine first reconciles an anonymous external bootstrap source, then provisions
that Secret and activates a pinned cutover revision. The Secret cannot precede
the Kubernetes API and `flux-system` namespace that hold it.

**Which repository and branch it follows are host inputs**, not a committed
file. `chuggy.flux.repositoryUrl` and `.branch` generate two `GitRepository`
objects, `fabric` and `fabric-release`, and one root `Kustomization` named
`fabric`, and no other Flux object. `fabric-release` is the same repository and
branch with `spec.ignore` keeping only the files under `cluster/chuggy-migrate/`
and `cluster/chuggy/`, and no `Kustomization` reads it: the release trigger
does. The
root applies `cluster/flux/`, where each layer Flux reconciles is declared as
its own `Kustomization`, so what Flux reconciles, and in what order, is changed
by a commit and not by a host rebuild. `apps` and `build-system` read
`fabric`, each a directory of this repository;
`chuggy-migrate` and `chuggy` read `OCIRepository` `chuggy-release`, each an
overlay of the release it holds. `cluster/flux/sources.yaml` declares that
source and `GitRepository` `chuggy`, the two of a release that are the same on
every host. The controller install is a checked-in manifest too,
because that is a vendored upstream artifact identical on every adopter. A box
being brought up, or one being used to try a change, has to be able to follow
something other than whatever the shared branch holds at that moment, and a
committed sync file made that a property of the repository instead of the host.

The [bootstrap and recovery runbook](docs/bootstrap-and-recovery.md) defines the
external recovery root, private-source provisioning, single-authority cutover,
rollback, and the state required for same-authority disaster recovery.

The object names are not options. Nothing in `cluster/` reads the label;
[Verified](#verified) below does, and so does anyone telling this repo's objects
from the rehearsal's second control loop — **by value**, which is what makes the
name a contract rather than a setting.

`source-controller`, `kustomize-controller`, `helm-controller` and
`notification-controller` are installed. `helm-controller` arrived with
kube-prometheus-stack: a chart that size is worth consuming as a `HelmRelease`
rather than vendoring its rendered output into `cluster/apps/`.
`notification-controller` routes nothing: no `Alert`, `Provider` or `Receiver`
is declared under `cluster/`.

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

**A workload that runs a chuggy release image is not an app in this sense.** It
goes in `cluster/chuggy/` and in that directory's `kustomization.yaml`, so that
it rolls after the release's migration, and its `image:` line names the image
at the digest of sixty-four zeroes the others carry, which a release writes
over. The `rollout-order-gtr` check refuses one anywhere else, and
`.chug/tasks/ci.sh` another digest. It reaches the cluster with the next
release, not at its merge.

**Add the file to `cluster/apps/kustomization.yaml` as well.** That directory
carries its own kustomization now — needed so the Ory ConfigMaps get a name
derived from their content — and a kustomization applies what it enumerates and
nothing else. A manifest that is in the directory and not in that list is not
applied, and `prune` then deletes it if it was there before. There is no check
for this; the list and `ls` have to agree, and a reviewer is what makes them.

### Adding a repository

A repository is bound to a project from the console, and nothing here changes:
the binding lives in the database, and every credential a run needs is minted
for the act that needs it from a GitHub App key the pod mounts. This repository
carries nothing per repository, and one check holds that subtraction: it
refuses a rendered cluster in which any pod projects a per-repository token.

    nix build .#checks.x86_64-linux.github-repository-transition

One thing is not this repository's to do. The owner's repository needs a ruleset
that reserves updates to its default branch to the portal App integration and
repository admins, because the credential a work pod is given is the worker
App's, it is `contents: write`, and it reaches every agent-executed pod that can
reach github.com. The list endpoint omits `bypass_actors` and `rules`, so
resolve each ruleset by id; a reader should see rules covering `update`,
`deletion` and `non_fast_forward`, and bypass actors naming only repository
admins and the portal App integration, nothing else:

    gh api repos/<owner>/<name>/rulesets --jq '.[].id' \
      | xargs -I{} gh api repos/<owner>/<name>/rulesets/{} \
          --jq '{name, enforcement, rules: [.rules[].type], bypass_actors}'

**The mirror role and its bare copies are unused.** Nothing here copies a
repository into the rig's git service any more and no pod reads one of those
copies: the mirror CronJob, its ConfigMap and its NetworkPolicy are deleted,
and a work pod clones from GitHub with a credential the worker plane mints for
it. The bare repositories on that service and the `mirror` credential class
its `pre-receive` hook admits are the rig's own — `deploy/rig/git/` in
kasofsk/chuggy is where both are made — and retiring them is the rig's to do.

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

### Flux and Tekton are scraped, and a release has a page

`cluster/apps/release-dashboard.yaml` points Prometheus at the Flux controllers
and at Tekton's, and `monitoring.yaml` has kube-state-metrics read Flux's own
objects, so each layer and source is a series saying whether it is ready and
what revision it holds. That is Flux's documented arrangement; its controllers
report how long they took and never what state an object is in.

The **Chuggy releases** dashboard (`/d/chuggy-releases`) is built on those: the
layers and sources as they stand, the trigger, the release runs by outcome, how
long Flux took over the two release layers, and under them the logs of one run,
of the dump and migration, and of the rollout.
`?var-run=<run>` narrows the run panels to one PipelineRun. Tekton counts runs
by pipeline and not by run, so a single run's detail is its logs, and those are
gone when Loki's retention passes.

A link from that page to its data breaks silently. `tests/release-dashboard.py`
holds the ones its header lists, and what a query means is not among them.

### Control-plane targets are switched off

`kubeControllerManager`, `kubeScheduler`, `kubeEtcd`, and `kubeProxy` are all
disabled. k3s runs the control plane as a single process, so none of them has a
separately scrapeable endpoint. Left enabled they become targets that are
permanently down and alerts that never clear — and an alert you have learned to
ignore is worse than no alert.

### Alerts evaluate, and go nowhere

Alertmanager is disabled. The rules still evaluate and still show as firing in
the Prometheus UI; there is simply nothing to route them to.

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

One process per responsibility, all out of one image:

| Workload | Command | Database role | Listens |
|---|---|---|---|
| `chuggy-api` | `src/roots/nativeHttp.ts` | `chuggy_api`, and `chuggy_selector_review` on a second pool | yes, 3000 |
| `chuggy-ticket-service` | `src/roots/ticketService.ts` | `chuggy_ticket_service` | no |
| `chuggy-selector` | `src/roots/selector.ts` | `chuggy_selector_service` | no |
| `chuggy-scheduler` | `src/roots/scheduler.ts` | `chuggy_scheduler` | no |
| `chuggy-finalizer` | `src/roots/finalizer.ts` | `chuggy_finalizer` | no |
| `chuggy-worker-plane` | `src/roots/workerPlane.ts` | `chuggy_worker_plane` | yes, 3001 |
| `chuggy-pool-plane` | `src/roots/poolPlane.ts` | `chuggy_pool_plane` | yes, 3002 |

Plus `chuggy-migrate-<commit>-registry`, a Job that dumps the database and then
applies the schema, named by a release for the chuggy commit it applies it
from. It waits for the database in
one initContainer, dumps it in the next, and then migrates once,
`backoffLimit: 0`.

**A release rolls out in order: the dump, the migration, the services.** The
Job is a Flux layer of its own, `chuggy-migrate`, and the services are another,
`chuggy`, which depends on it; `apps` applies neither. So the services of a
release are applied only once its Job has completed, and when the dump or the
migration fails they stay as they were: `chuggy` reads `DependencyNotReady` and
applies nothing. That holds every later change to the services as well, until
a release of another chuggy commit replaces the Job or a person clears it.
Nothing restores the dump — it is on the `chuggy-dumps`
volume for a person to restore from.
`cluster/chuggy-migrate/chuggy-migrate.yaml` argues the order and says what it
costs.

**Retrying the Job was never able to survive the NetworkPolicy warm-up, and the
rig says so.** kube-router admits a pod *IP*, and it needs a few seconds after
that IP appears; a failed Job pod is replaced rather than restarted, so each
attempt is a fresh address starting the same wait from nothing. A Job of this
shape whose container connects once produced five consecutive pods with five
distinct IPs, over 2m42s, every one refused. A pod that asked again inside the
same sandbox was admitted on its second attempt, two seconds in. That is also
why `chuggy-api` gets past it on a kubelet restart — a restart keeps the pod,
and so keeps the address that has by then been admitted.

**A dump or a migration that fails is terminal and needs a human.** A release
of another chuggy commit carries a Job of another name, but until there is one
nothing about the Job changes and there is nothing for Flux to re-create: it
re-applies an identical `Failed` Job every five minutes, the API server accepts
it as unchanged, and neither runs again. The trigger starts no run for it
either: the run that published that release succeeded.

**The Kustomization reports it.** `wait: true` health-checks every object the
layer applies, and kstatus reads a `Failed` Job as failed, so `flux get
kustomization chuggy-migrate` goes `Ready=False` with the Job in its message,
and `chuggy` behind it reads `DependencyNotReady`. That layer applies the Job
and its script and nothing else, so no other workload is in that bit. It is
still quieter than it sounds: Alertmanager is off and no `Alert` is declared for
`notification-controller`, so nothing routes it anywhere.

Read the pod, fix the cause, then delete the Job so the next reconcile builds it
afresh:

    kubectl -n chuggy logs job/chuggy-migrate-<commit>-registry -c dump
    kubectl -n chuggy logs job/chuggy-migrate-<commit>-registry -c migrate
    kubectl -n chuggy delete job chuggy-migrate-<commit>-registry

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
deadline would turn that wait into the terminal `Failed` state above. While it
waits, the services are held as they are for a failure.

The wait for the database is bounded anyway, and does not cost that back: it
runs in the initContainer, so its clock cannot start until the image is on the
node. Thirty attempts and then a non-zero exit, so a database that is genuinely
down ends as a failed Job rather than as a Job that hangs.

The API image already contains every control-plane command: its Dockerfile
copies the whole source tree and sets the API as its default. A release writes
its one digest onto every `image:` field that names it, the Job's included, so
they move together. The migration Job's name changes with chuggy's commit
because Kubernetes makes its pod template immutable; a release that changes
the Job and not that commit is what `force` on its layer is for.

Four of the five open no socket, so they have no probe and no Service. They
report an unmet precondition by name and exit; the kubelet restarts them. A
process that is alive and making no progress is therefore invisible to
Kubernetes, and closing that needs a health listener in chuggy itself.

### The network boundary around them

`cluster/apps/chuggy-control-plane-network-policy.yaml` holds nine
NetworkPolicies: one that admits nothing to the five processes with no listener
or to the migration Job, one that admits the API from Traefik, the selector, a
session pod and Flux's notification-controller alone, and seven egress rules
that each state completely where one workload may go. The widest is the
scheduler's, which needs the Kubernetes API server at an address that is a DHCP
lease, so it permits everything but the pod and service networks; the file
argues why and what would narrow it.

**`chuggy-api` is bounded in both directions.** `chuggy-api-egress` admits the
resolver, PostgreSQL, Keto's read and write ports, Hydra's admin port and public
HTTPS on 443, and refuses the rest: every other pod on the cluster, the rig's
own git service, and the house LAN, which the public arm excepts along with the
pod and service networks. That 443 arm is three destinations no rule here can
name as hostnames — OIDC discovery and JWKS against `auth.vteng.io`, which
leaves the cluster and comes back through the tunnel, `api.github.com` for the
installation tokens the pod mints, and `github.com` for a bound repository's
`ls-remote` and `fetch`. It is the only one of these the internet reaches, so it
is the one whose rule fails as an outage rather than as a loop that stalls.

**`chuggy-ui` is selected by none of the nine, in either direction**, and that
is the state this PR leaves it in rather than a decision it argues. It is the
console: nginx serving static files, reached from Traefik, with no `proxy_pass`
in it — the browser reaches the API through Traefik and this pod opens no
connection to it. Nothing here restricts what may reach it or where it may go.
Bounding it is worth doing and is not this change.

**No probe has been run through any of these.** They were built against the API
server and their selectors checked against the labels the cluster carries, but
none has been applied to the running rig. Three are worth watching on the first
reconcile: both rules on `chuggy-api`, the ones standing in front of something
that already works, and the egress rule on `chuggy-migrate`, standing in front
of the one thing that has to work before anything else does.

### Before any of it runs

What a person does before a box's first release, each step argued in the file
that needs it. **Steps 1 and 4 finish before 2, and nothing here can enforce
that**: the trigger starts a box's first release without being asked and Flux
applies it as soon as it is published, so the two release layers are suspended
before anything else, and what a human must do to the database is done before
they are resumed.

    flux suspend kustomization chuggy-migrate chuggy

1. **Run kasofsk/chuggy's roles file, from the commit about to be released.**
   [Generated credentials](#generated-credentials) gives the command and what
   precedes it, `systemctl is-active chuggy-secrets-sync` saying `active`.
   `chuggy-pg-role-env` hands the file one variable for each key of
   `chuggy-postgres-credentials`, `CHUG_PG_CONFIGURATION_IMPORTER_PASSWORD`
   among them, and the file re-issues every password it reads.

   It is first because of three memberships no migration can grant itself.
   `chuggy_owner` in `chuggy_boundary_owner` is what makes migration 17's
   `GRANT EXECUTE` land: without it 17 commits while granting nothing, and no
   re-run of the Job repairs that. `chuggy_api_login` in
   `chuggy_selector_review` is what the API's second pool connects as, and
   without it the API refuses to listen. `chuggy_configuration_importer_login`
   in `chuggy_configuration_importer` is everything the importer may do,
   because it connects as the login and sets no role. Read that they landed:

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

   The first prints a row for each of the three roles, and a missing row is a
   name this database does not have: `-Atc` prints nothing and exits 0 for an
   empty result, so without it a mistyped name and an absent grant look the
   same. The second lists `chuggy_boundary_owner|chuggy_owner`,
   `chuggy_selector_review|chuggy_api_login` and
   `chuggy_configuration_importer|chuggy_configuration_importer_login` among
   its rows.
2. **Resume the two layers**, as [Operating a release](#operating-a-release)
   does. The trigger has published the first release by then or publishes it
   unasked, and its Job migrates the database as soon as the layers read it.
3. **The artifact directory is the host's.** `chuggy.state.artifacts.path`
   names it and the state module creates it, with the owner and mode its
   options state. `cluster/apps/chuggy-artifacts.yaml` binds
   `/var/lib/chuggy/artifacts`, which is what both hosts here set. The claim
   going `Bound` says nothing of the directory, because binding is two API
   objects agreeing; `test -d` on the node does.
4. **See that PostgreSQL accepts what the Secret holds.** A green
   `chuggy-secrets-sync` proves the host and the cluster hold one value and
   nothing about the server. The roles file re-issues every password it names,
   so a run of it with values other than `chuggy-postgres-credentials` holds
   leaves each pod refused at its next start. Authenticate as each login that
   Secret has a key for before step 2.
5. **Make the control plane's Secrets that no unit generates**, by hand. A
   value never goes in this repository, which is public. The manifest named
   carries the command and argues it: `chuggy-selector` in
   `chuggy-selector.yaml`, `chuggy-finalizer-credentials` in
   `chuggy-finalizer.yaml`, `chuggy-github-app-portal` and
   `chuggy-github-app-portal-client` in `chuggy-api.yaml`, and
   `chuggy-github-app-worker` in `chuggy-worker-plane.yaml`. The two Apps' keys
   are the host's own key files, copied: `keySecret` beside each App's
   `privateKeyFile` on the host is the name, and `tests/forge-app-key.py`
   holds the manifests to it. A pod whose Secret is missing is never built,
   under one of two names: a `secretKeyRef` env gives
   `CreateContainerConfigError`, a mounted Secret gives `ContainerCreating` on
   a `FailedMount`.
6. **Establish the first recovery epoch**, as a Secret and a row that carry the
   same value. `chuggy-recovery-epoch` is read by both the scheduler and the
   finalizer, and the row is what they fence against; no migration writes it,
   because the table is created empty. `chuggy-finalizer.yaml` carries the two
   commands. The value is generated, never written down here.

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

**Database dumps have a volume, and the migration Job writes to it.**
`cluster/apps/chuggy-dumps.yaml` declares a volume in the same class over
`chuggy.state.dumps.path` and a claim in `chuggy`, and the migration Job's
`dump` container mounts that claim. Before it migrates, the Job writes an
archive of the `chuggy` database and the server's roles there, and keeps as
many as `CHUG_DUMP_KEEP` in its manifest says; the server's other databases,
Ory's among them, are not in it. It is on the same disk as the database: a dump
kept there protects against a migration that damages the data, not against
losing the disk, and it is not the off-installation backup
`docs/bootstrap-and-recovery.md` calls for. Nothing restores from it
automatically.

## Giving someone else access

Two separable questions, and conflating them is the trap: *what may they do*
(authorization) and *how do they reach the API* (transport).

### Deploying is a git question, not a cluster question

Cluster state comes from `cluster/`, so the way to let someone ship
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
