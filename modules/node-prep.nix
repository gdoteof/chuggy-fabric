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

  # Headless: no framebuffer console fonts, no scanner, no audio stack.
  sound.enable = false;

  # Trim the docs the desktop pulled in. Man pages stay -- they cost little and
  # you will want them at 2am.
  documentation.doc.enable = false;
  documentation.info.enable = false;
}
