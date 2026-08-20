{ config, pkgs, lib, ... }:

# k3s as the chuggy fabric's control plane.
#
# The durable box is both server and worker: k3s servers run workloads by default
# (no --disable-agent), which is exactly the "sole worker most of the time" shape.
# Cloud spot agents join later over Tailscale; see the tailscaleName option and
# the README section on scaling out.

let
  cfg = config.chuggy.k3s;
in
{
  options.chuggy.k3s = {
    enable = lib.mkEnableOption "k3s server for the chuggy fabric";

    tailscaleName = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "gtr.tail1234.ts.net";
      description = ''
        Tailnet DNS name for this node, added to the API server certificate's
        SANs. Remote agents connect to the API server by this name, and TLS
        verification fails unless the cert carries it.

        Left null until tailscaled is actually logged in. k3s regenerates its
        serving certificate when the SAN list changes, so setting this later is
        a rebuild and a restart -- not a cluster rebuild.
      '';
    };

    durableLabel = lib.mkOption {
      type = lib.types.str;
      default = "chuggy.dev/durable=true";
      description = ''
        Node label marking this box as the one that does not disappear. Spot
        agents will not carry it, so chuggy can pin its journal and any other
        stateful work here with a nodeSelector.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    services.k3s = {
      enable = true;
      role = "server";

      extraFlags = toString ([
        "--node-label=${cfg.durableLabel}"

        # k3s writes /etc/rancher/k3s/k3s.yaml as root:root 0600 by default.
        # 0644 grants nothing new here: geoff already has passwordless sudo, so
        # the admin credential is reachable regardless. Revisit if these boxes
        # ever get a second human user.
        "--write-kubeconfig-mode=0644"
      ]
      ++ lib.optional (cfg.tailscaleName != null) "--tls-san=${cfg.tailscaleName}");
    };

    # Bundled components are left on deliberately: traefik (ingress), servicelb
    # (LoadBalancer services), local-path (default StorageClass), coredns,
    # metrics-server. Fastest path to a usable target, each removable with one
    # flag later.
    #
    # Know the sharp edge: local-path PVCs are directories on the node that
    # created them, so a pod with a PVC is pinned to that node. Correct for the
    # durable box, wrong for spot agents -- keep stateful work on the durable
    # node via the label above.

    networking.firewall = {
      # Agent traffic arrives over the tailnet, not the LAN. Trusting the
      # interface avoids poking cluster ports at the public-facing firewall.
      trustedInterfaces = [ "tailscale0" ];

      allowedTCPPorts = [
        6443   # kubernetes API -- agents and kubectl
      ];
      allowedUDPPorts = [
        8472   # flannel VXLAN between nodes
      ];
    };

    environment.systemPackages = with pkgs; [
      k9s
      kubectl
      kubernetes-helm
    ];

    # k3s ships the admin kubeconfig here; point kubectl at it by default rather
    # than making everyone remember the path.
    environment.variables.KUBECONFIG = "/etc/rancher/k3s/k3s.yaml";
  };
}
