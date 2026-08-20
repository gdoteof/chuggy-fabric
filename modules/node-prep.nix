{ config, pkgs, lib, ... }:

# Everything a Kubernetes node needs that is independent of which distribution
# ends up running. Nothing here commits to k3s, kubeadm, or anything else.

{
  # --------------------------------------------------------------- kernel ----

  # br_netfilter must be loaded before systemd-sysctl applies the bridge
  # sysctls below, or those keys do not exist yet and the unit fails. Declaring
  # them here loads them at boot, ahead of sysctl.
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

    # More room for the connection tracking and inotify pressure a busy node
    # generates -- kubelet watches a lot of files.
    "fs.inotify.max_user_watches" = 524288;
    "fs.inotify.max_user_instances" = 512;
  };

  # ----------------------------------------------------------------- swap ----

  # kubelet refuses to start with swap enabled unless explicitly told otherwise.
  # The box has none today; this makes that a property of the config rather than
  # an accident of how it was installed.
  swapDevices = lib.mkForce [ ];
  zramSwap.enable = false;

  # -------------------------------------------------------- wait-online ----

  # NetworkManager-wait-online fails on every rebuild but has never failed at
  # boot -- the journal shows "Finished" at each real boot and "Failed" only when
  # the unit is restarted on a live system.
  #
  # Cause: after a live restart NetworkManager never re-signals startup
  # completion. nmcli reports STARTUP=starting indefinitely while STATE=connected,
  # so `nm-online -s` waits out its timeout and exits 1. It is NM's own startup
  # flag, not a stuck device -- unmanaging the idle wifi and the cable-less second
  # NIC changes nothing. This NetworkManager (1.48) has no `--any` to relax it.
  #
  # network-online.target buys little on a headless node with one wired NIC, so
  # the unit goes rather than being papered over with a longer timeout.
  # Revisit if k3s turns out to genuinely need that barrier -- with this disabled
  # the target activates immediately rather than waiting for a real link.
  systemd.services.NetworkManager-wait-online.enable = false;

  # ------------------------------------------------------------------ cpu ----

  # Was "powersave". A node that sits idle then bursts wants the scheduler
  # ramping quickly.
  powerManagement.cpuFreqGovernor = lib.mkDefault "performance";

  # --------------------------------------------------------------- desktop ----

  # The GTR was a workstation: X11, xmonad, lightdm + the enso greeter,
  # DisplayLink, PipeWire, Bluetooth, CUPS, Synergy. None of it belongs on a
  # node. These are explicit rather than merely absent so that the intent
  # survives someone later importing a module that turns them back on.
  services.xserver.enable = false;
  services.printing.enable = false;
  hardware.bluetooth.enable = false;
  services.pipewire.enable = false;

  # ---------------------------------------------------------------- radios ----

  # The AX200 is a combo Wi-Fi/Bluetooth card and this node is wired-only on
  # enp2s0. Disabling the stacks above removes the userspace daemons; blacklisting
  # the drivers means the devices never appear at all, so NetworkManager has no
  # wireless device to manage and no reason to spawn wpa_supplicant.
  #
  # This gives up wireless as a fallback if the ethernet link dies -- acceptable
  # on a box that also has a second unused NIC and physical access.
  boot.blacklistedKernelModules = [
    "iwlwifi"  # Intel Wi-Fi 6 AX200
    "btusb"    # Bluetooth radio on the same card
  ];
  systemd.services.wpa_supplicant.enable = false;
  # NOTE: `sound.enable` was removed in NixOS 24.11 -- disabling PipeWire and
  # PulseAudio is the whole of it now.
  hardware.pulseaudio.enable = false;

  # Trim the docs the desktop pulled in. Man pages stay -- they cost little and
  # you will want them at 2am.
  documentation.doc.enable = false;
  documentation.info.enable = false;
}
