# nixconfigs — k3s nodes for the chuggy fabric

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
    modules/k3s-server.nix          the cluster role, with chuggy.k3s.* options

    hosts/gtr/default.nix           geoff's Beelink GTR: hostname, radios, k3s
    hosts/gtr/hardware-configuration.nix

    nixos-live/                     the original /etc/nixos, captured verbatim

Anything in `modules/` must be true of every node. Anything hardware-specific —
disks, radios, hostname — belongs in `hosts/<name>/`. The Wi-Fi blacklist is the
worked example: `iwlwifi` is correct for the GTR's AX200 and wrong for any box
with a different card, so it lives in the host file.

`nixos-live/` is history, not input. Nothing imports it.

## Workflow

The box is not the source of truth. Push and build:

    rsync -a --delete --exclude nixos-live --exclude .git \
      ~/claude/nixconfigs/ geoff@192.168.0.114:/home/geoff/nixconfigs-test/

    ssh geoff@192.168.0.114 \
      'cd nixconfigs-test && nixos-rebuild build --flake .#gtr'

| Command | Effect |
|---|---|
| `nixos-rebuild build` | builds only, no activation |
| `nixos-rebuild test` | activates now, **not** the boot default — reboot undoes it |
| `nixos-rebuild switch` | activates and makes it the boot default |

`test` before `switch`. If a change breaks the network, a power cycle recovers it.

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

kubeconfig is written world-readable (`--write-kubeconfig-mode=0644`). That grants
nothing new: `geoff` already has passwordless sudo, so the admin credential is
reachable regardless. Revisit if these boxes ever get a second human user.

## Scaling out to spot workers

Not built. What is already in place, and what remains:

**In place.** Firewall opens 6443 (API) and 8472/udp (flannel VXLAN), and trusts
`tailscale0` outright so cluster traffic over the tailnet is not filtered at the
LAN-facing firewall. The durable node is labelled.

**Remaining, roughly in order:**

1. **Log tailscaled in.** It is installed and running but reports `NeedsLogin`.
   Nothing remote can reach the API server until this is done — port-forwarding
   6443 from a home connection is not an acceptable substitute.
2. **Set `chuggy.k3s.tailscaleName`** to this node's tailnet DNS name. It becomes
   a `--tls-san` on the API server certificate; without it, agents connecting by
   that name fail TLS verification. k3s regenerates the serving cert when the SAN
   list changes, so this is a rebuild and a restart, not a cluster rebuild.
3. **Get the node token** from `/var/lib/rancher/k3s/server/node-token` to the
   cloud side. It is a joining credential — it does not belong in this repo. Use
   the cloud provider's secret store, or sops-nix/agenix if it must be declared.
4. **Taint the spot agents** so only work that tolerates eviction lands there.
   Spot instances are reclaimed with about two minutes' notice; anything holding
   a PVC or unreplicated state must not be schedulable onto them.

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
