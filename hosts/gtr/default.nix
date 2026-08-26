{ config, pkgs, lib, ... }:

# Beelink GTR (AZW GTR V11) -- Ryzen 9 7940HS, 32 GB, 1 TB NVMe, 2x 1GbE.
# Everything here is true of this machine specifically. Shared behaviour lives in
# modules/.

{
  # GTR is the reference self-contained installation: control plane, durable
  # workloads, worker execution, registry, and image builds share this node.
  chuggy.mini.enable = true;

  networking.hostName = "gtr";

  # ---------------------------------------------------------------- radios ----

  # This box has an Intel Wi-Fi 6 AX200 -- a combo Wi-Fi/Bluetooth card -- and is
  # wired-only on enp2s0. modules/node-prep.nix disables the userspace stacks;
  # blacklisting the drivers means the devices never enumerate, so NetworkManager
  # has no wireless device to manage and no reason to spawn wpa_supplicant.
  #
  # Gives up wireless as a fallback if the ethernet link dies -- acceptable on a
  # box with a second unused NIC and physical access.
  #
  # Card-specific: another host with a different radio needs its own module names.
  # Check `lspci -k` before copying this to a different machine.
  boot.blacklistedKernelModules = [
    "iwlwifi"  # Intel Wi-Fi 6 AX200
    "btusb"    # Bluetooth radio on the same card
  ];
  systemd.services.wpa_supplicant.enable = false;

  # ------------------------------------------------------------ wireguard ----

  chuggy.wireguard = {
    enable = true;
    # Server end of the mesh.
    #
    # Address plan: .1 is the server, .2-.9 are humans, .10 upward are spot
    # agents. Splitting the ranges keeps a person from being handed an address
    # the pre-allocated agent key pool later expects to own.
    address = "10.100.0.1/24";

    # Public keys only -- a private key here would hand over the mesh, and this
    # repository is public. A peer generates its own with `wg genkey | tee
    # private.key | wg pubkey` and sends only the second value.
    #
    # A human peer looks like this:
    #
    #   { name = "dev2";
    #     publicKey = "<their base64 public key>";
    #     allowedIPs = [ "10.100.0.2/32" ];
    #   }
    #
    # A /32 is the point: allowedIPs is a routing and cryptographic filter, so a
    # peer can only source traffic from the address listed here. Widening it to
    # the /24 would let any one peer impersonate any other.
    #
    # Spot agents get added the same way from .10 up -- see the README on the
    # pre-allocated key pool, which avoids a rebuild per instance.
    peers = [
      { name = "dev2";
        publicKey = "cMer3teG3LOE6J5J2yXCREHFYpfjpkZYodIP2Uk8jAY=";
        allowedIPs = [ "10.100.0.2/32" ];
      }
    ];
  };

  # ------------------------------------------------------------------ k3s ----

  chuggy.k3s = {
    # The mesh address must be on the API certificate before any remote agent
    # dials in, or its TLS verification fails. Cheap to include now; a rebuild
    # and restart to add later.
    apiSans = [ "10.100.0.1" ];

    # The house LAN and the mesh, and deliberately nothing else. The first is
    # how kubectl reaches this box from the workstation; the second is how a
    # peer does. The pod range the cluster's own clients arrive from is added by
    # the module, because leaving it out costs the cluster its API server and no
    # host should have to remember that.
    apiAllowedSources = [ "192.168.0.0/24" "10.100.0.0/24" ];

    # `pool=work` was set on this node by hand and was declared nowhere. Here it
    # is what a fresh box registers with; this one already carries it, and
    # kubelet does not reapply a label to a node that already exists.
    nodeLabels = [ "chuggy.dev/durable=true" "chuggy.dev/pool=work" ];
  };

  # --------------------------------------------------------------- chuggy ----

  # Retained data, generated credentials, and the images this node runs without
  # a registry. All three are host state: each outlives every Kubernetes object
  # that mounts, reads or references it.
  chuggy.state = {
    # Under the state root, so one directory is the whole of what this box keeps
    # for chuggy. That root is 0700 root, which does not obstruct the kubelet --
    # it bind-mounts this directory into the pod rather than walking to it --
    # but does mean reading an artifact from a shell here needs sudo.
    artifacts.path = "/var/lib/chuggy/artifacts";
    registry.path = "/var/lib/chuggy/registry";
    buildResults.path = "/var/lib/chuggy/build-results";
  };

  # One task at a time, sized against the box in the header above and against
  # what already runs on it: the control plane, PostgreSQL, Ory and the
  # monitoring stack. These say what a single work pod may take, not what the
  # machine has.
  chuggy.work = {
    worker = {
      cpu = "2";
      memory = "4Gi";
      ephemeralStorage = "20Gi";
    };
  };

  # -------------------------------------------------------------- ingress ----

  # Cloudflare Tunnel. Outbound-only, so no router port-forward and no dynamic
  # DNS -- unlike the WireGuard mesh above, which still needs both.
  chuggy.tunnel = {
    enable = true;
    tunnelId = "84115dde-a1d0-4e8a-832a-e4da2cf98180";  # tunnel "gtr"
    # Single-label subdomains only. Universal SSL covers vteng.io and one level
    # of *.vteng.io, so `auth.chuggy.vteng.io` would need a certificate this
    # zone does not have.
    #
    # auth is Ory Hydra's public port and nothing else -- it is the OIDC issuer
    # string, so the name is load-bearing and cannot be changed without
    # invalidating every token and every client registration. id is Kratos and
    # the self-service UI. Neither admin port appears here, and cluster/apps/
    # ory-hydra.yaml says why that matters.
    #
    # chuggy is one name for two backends: the operations console at / and the
    # web API at /api/v1. They share it because the API answers no cross-origin
    # preflight, so a console on a second name could not read it -- the split is
    # Traefik's, in cluster/apps/chuggy-web.yaml, and this list cannot express it
    # either way.
    hostnames = [
      "whoami.vteng.io"
      "grafana.vteng.io"
      "sirdocalot.vteng.io"
      "auth.vteng.io"
      "id.vteng.io"
      "chuggy.vteng.io"
    ];
  };

  # ----------------------------------------------------------------- ddns ----

  # A plain A record holding this box's real public address, so mesh peers have
  # a name that keeps resolving after the ISP rotates it. Unproxied by
  # necessity -- see modules/ddns.nix for why the tunnel cannot do this job.
  chuggy.ddns = {
    enable = true;
    domains = [ "gtr-ip.vteng.io" ];
  };

  # -------------------------------------------------------------- gitops ----

  # k3s applies Flux at startup; Flux reconciles cluster/apps from this repo.
  # Nothing in the cluster is applied by hand.
  #
  # `main` is the live branch: a push to it changes this cluster inside the
  # source interval. That is the whole reason the branch is stated per host
  # rather than compiled in.
  chuggy.flux = {
    repositoryUrl = "https://github.com/gdoteof/chuggy-fabric.git";
    branch = "main";
  };

  chuggy.githubAppToken = {
    enable = true;
    appId = "4708055";
    installationId = "156333284";
    repository = "chuggy";
    privateKeyFile = "/var/lib/chuggy/secrets/github-app/chuggy-portal.pem";
    namespaces = [ "chuggy" "chuggy-work" ];
  };
}
