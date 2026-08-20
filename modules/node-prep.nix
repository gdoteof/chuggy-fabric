{ config, pkgs, lib, ... }:

# Kubernetes prerequisites and workstation teardown, for any host in this repo.
# Nothing here is specific to one machine's hardware -- per-host quirks (radios,
# disks, hostname) live in hosts/<name>/default.nix.
#
# Nothing here commits to a k8s distribution either; see modules/k3s-server.nix.

{
  # --------------------------------------------------------------- kernel ----

  # br_netfilter must be loaded before systemd-sysctl applies the bridge sysctls
  # below, or those keys do not exist yet and the unit fails. Declaring them here
  # loads them at boot, ahead of sysctl.
  boot.kernelModules = [
    "overlay"       # container storage driver
    "br_netfilter"  # lets iptables see bridged traffic
  ];

  boot.kernel.sysctl = {
    # Pod traffic is routed, not bridged, between nodes.
    "net.ipv4.ip_forward" = 1;

    # Service and NetworkPolicy rules are enforced by iptables/nftables, which
    # only sees bridged packets when these are set.
    "net.bridge.bridge-nf-call-iptables" = 1;
    "net.bridge.bridge-nf-call-ip6tables" = 1;

    # Several CNIs (Calico, Cilium) use asymmetric return paths that strict
    # reverse-path filtering drops.
    "net.ipv4.conf.all.rp_filter" = 0;

    # kubelet watches a lot of files.
    "fs.inotify.max_user_watches" = 524288;
    "fs.inotify.max_user_instances" = 512;
  };

  # ----------------------------------------------------------------- swap ----

  # kubelet refuses to start with swap enabled unless explicitly told otherwise.
  # Making this declarative means a future host cannot inherit swap by accident.
  swapDevices = lib.mkForce [ ];
  zramSwap.enable = false;

  # ------------------------------------------------------------------ cpu ----

  # A node that idles then bursts wants the scheduler ramping quickly.
  powerManagement.cpuFreqGovernor = lib.mkDefault "performance";

  # ---------------------------------------------------------- wait-online ----

  # NetworkManager-wait-online fails on every rebuild but has never failed at
  # boot -- the journal shows "Finished" at each real boot and "Failed" only when
  # the unit is restarted on a live system.
  #
  # Cause: after a live restart NetworkManager never re-signals startup
  # completion. nmcli reports STARTUP=starting indefinitely while STATE=connected,
  # so `nm-online -s` waits out its timeout and exits 1. It is NM's own startup
  # flag, not a stuck device -- unmanaging the idle wifi and the cable-less second
  # NIC changed nothing. NetworkManager 1.48 has no `--any` to relax the check.
  #
  # network-online.target buys little on a headless node with one wired NIC.
  # Note that with this masked the target activates immediately rather than
  # waiting for a real link -- revisit if something downstream needs that barrier.
  systemd.services.NetworkManager-wait-online.enable = false;

  # -------------------------------------------------------------- desktop ----

  # These boxes were workstations. None of this belongs on a node. Disabled
  # explicitly rather than merely omitted, so a later import cannot silently
  # switch them back on.
  services.xserver.enable = false;
  services.printing.enable = false;
  hardware.bluetooth.enable = false;
  services.pipewire.enable = false;
  # `sound.enable` was removed in NixOS 24.11; disabling PipeWire and PulseAudio
  # is the whole of it now.
  hardware.pulseaudio.enable = false;

  documentation.doc.enable = false;
  documentation.info.enable = false;
}
