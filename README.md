# nixconfigs — durable NixOS config for the GTR

The authoritative copy of the configuration for **`nixos` / 192.168.0.114**
(Beelink GTR, Ryzen 9 7940HS). Lives here on the workstation so the box itself
stays disposable.

Previously the config was a root-owned, unversioned `/etc/nixos/configuration.nix`
that imported three paths out of `/home/geoff/nixconfig/` — a directory scheduled
for deletion. That coupling is gone.

## Layout

    flake.nix                            pins nixpkgs + nixos-hardware
    flake.lock                           the actual pin — commit every change to it
    hosts/nixos/default.nix              host config: identity, access, packages
    hosts/nixos/hardware-configuration.nix   generated, do not hand-edit
    modules/node-prep.nix                k8s prerequisites + desktop teardown
    nixos-live/                          the original /etc/nixos, captured verbatim

`nixos-live/` is history, not input. Nothing imports it. It is the record of what
built generation 171, kept so the rewrite can be checked against it.

## Workflow

The box does not hold the source of truth. Push it there and build:

    rsync -a --delete --exclude nixos-live --exclude .git \
      ~/claude/nixconfigs/ geoff@192.168.0.114:/home/geoff/nixconfigs-test/

    ssh geoff@192.168.0.114 \
      'cd nixconfigs-test && nixos-rebuild build --flake .#nixos'

`build` compiles without touching the running system. Escalate deliberately:

| Command | Effect |
|---|---|
| `nixos-rebuild build` | builds only, no activation |
| `nixos-rebuild test` | activates now, **not** the boot default — reboot undoes it |
| `nixos-rebuild switch` | activates and makes it the boot default |

`test` before `switch`. If a change breaks the network, a power cycle recovers it.

## State

Test-built clean against generation 171 on 2026-08-19.

    closure    11.5 GB → 4.9 GB
    packages   395 removed, 21 added
    kernel     6.6.59 → 6.6.94  (needs a reboot to take effect)

**Not yet applied.** The box is still running the old generation.

## What changed from the original

### Removed the `/home` dependency

The three `/home/geoff/nixconfig/nixos-hardware/...` imports are now the
`nixos-hardware` flake input, pinned in `flake.lock`. Same upstream repo the
local clone tracked.

### Stripped the desktop

X11, xmonad, lightdm + the enso greeter, DisplayLink, PipeWire, PulseAudio,
Bluetooth, CUPS, Noisetorch, Alacritty, the font set, and the GDK scaling vars.
This is where most of the 6.6 GB went. Disabled explicitly rather than merely
omitted, so a later import cannot silently switch them back on.

### Closed the firewall down to SSH

Was `[ 2375 22 80 443 ]`, plus TCP range 4000–5550 and UDP 24800.

- **2375** — the unauthenticated, unencrypted Docker daemon API. Nothing was bound
  to it, so this was not a live breach, but the port was open to the LAN and
  anything binding it would have had root-equivalent access.
- **80/443** — no web server on this host.
- **4000–5550** — 1,551 ports for dev servers that stopped existing in 2024.
- **24800/udp** — Synergy, which went with the desktop.

k8s ports get added when the distro is picked.

### Dropped broken and dead config

- `programs.ssh.extraConfig` set a system-wide `IdentityFile` of
  `/home/geoff/.ssh/id_rsa_github`, **a file that does not exist**. Likely a
  contributor to the GitHub auth failure.
- `cachix.nix` was never in `imports` — the `nix-node.cachix.org` substituter had
  been dead config. Dropped rather than silently carried forward. Re-add
  deliberately if that cache is wanted.
- `networking.extraHosts` mapped `192.168.0.107 nixos` — the box's own hostname
  pointed at an IP it no longer holds.
- `i18n.consoleFont` and `sound.enable` are both gone from 24.11.

### Added

- `boot.loader.systemd-boot.configurationLimit = 10` — /boot hit 96% because
  nothing capped generations. At ~37 MB of initrd each, 10 fits comfortably.
- `nix.gc` weekly, 30-day retention, plus `nix.optimise` — the store had reached
  217 GB.
- k8s prerequisites in `modules/node-prep.nix`: `overlay` and `br_netfilter`
  modules, bridge-netfilter and `ip_forward` sysctls, `rp_filter` off for CNIs
  with asymmetric return paths, raised inotify limits for kubelet, swap forced
  off, CPU governor `performance` (was `powersave`).
- `nvme-cli` and `smartmontools` — both were missing when the SSD health check
  was needed.

### Deliberately kept

- **The `geoff` user.** It is the SSH access path; removing it removes the way in.
  Also `programs.zsh.enable`, without which that user's login shell breaks.
- **NetworkManager.** Heavier than a server needs, but it holds the current DHCP
  lease. Switching to systemd-networkd is a console job, not something to do over
  the SSH session it would drop.
- **`PasswordAuthentication`** at its default. Key auth works, so disabling it is
  good hygiene — but do that from the console so a mistake is recoverable.
- **Docker.** Still has containers on it and does not conflict with k3s. Revisit
  when the distro lands; k3s ships its own containerd.
- **`system.stateVersion = "23.05"`.** Frozen at install value by design. This is
  not a "current version" field and must never be bumped to match the release.

## Not done yet

No Kubernetes distribution is configured — that decision is still open, and
nothing here forecloses k3s, kubeadm, or anything else.

nixpkgs is pinned to `nixos-24.11`, matching what the box already ran. Moving to a
newer release is a separate change and belongs on its own commit, so a failed
rebuild has one obvious cause.
