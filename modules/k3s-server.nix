{ config, pkgs, lib, ... }:

# k3s as the chuggy fabric's control plane.
#
# The durable box is both server and worker: k3s servers run workloads by default
# (no --disable-agent), which is exactly the "sole worker most of the time" shape.
# Cloud spot agents join later over the WireGuard mesh; see modules/wireguard.nix
# and the README section on scaling out.

let
  cfg = config.chuggy.k3s;

  # An IPv4 address or CIDR block, and nothing else -- the type is the guard,
  # not a nicety. These strings become `iptables -s` arguments in
  # networking.firewall.extraCommands, which runs under `bash -e`: one entry
  # iptables will not parse aborts firewall-start after it has flushed the
  # chain and before it has refilled it, and the box is left with an empty
  # INPUT policy ACCEPT and a failed unit as the only sign. A string option
  # cannot say that; this one refuses it at evaluation.
  #
  # IPv4 only, which is a statement about the rules below rather than about
  # networks: they are `iptables`, so an IPv6 source could not be applied by
  # them and would silently name a range the firewall never sees.
  cidr =
    let
      octet = "(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])";
      prefix = "(3[0-2]|[12]?[0-9])";
    in
    lib.types.strMatching "^${octet}(\\.${octet}){3}(/${prefix})?$";

  # Where API traffic actually comes from, which is not the same list an adopter
  # supplies. See apiAllowedSources for why the cluster's own pod range is on it.
  apiSources = (if cfg.apiAllowedSources == null then [ ] else cfg.apiAllowedSources)
    ++ [ cfg.clusterCidr ];
in
{
  options.chuggy.k3s = {
    enable = lib.mkEnableOption "k3s server for the chuggy fabric";

    apiSans = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "10.100.0.1" "gtr.example.dev" ];
      description = ''
        Extra names and addresses added to the API server certificate's SANs.

        Agents connect to the API server by address and TLS verification fails
        unless the certificate carries it -- so this needs the node's WireGuard
        address before any remote agent joins.

        k3s regenerates its serving certificate when the SAN list changes, so
        adding one later is a rebuild and a restart, not a cluster rebuild.
      '';
    };

    apiAllowedSources = lib.mkOption {
      type = lib.types.nullOr (lib.types.listOf cidr);
      default = null;
      example = [ "192.168.0.0/24" "10.100.0.0/24" ];
      description = ''
        Source ranges permitted to reach the Kubernetes API and the flannel
        VXLAN port. Required: this is the boundary around a credential that can
        do anything on the cluster, and a shared module has no business
        embedding one site's subnet.

        The LAN the node sits on and the WireGuard range are the two normally
        wanted -- the first is how kubectl works from a workstation, the second
        is how it works from anywhere else. Neither is the internet.

        THE POD RANGE IS ADDED AUTOMATICALLY and the effective rule cannot do
        without it. A pod reaching the `kubernetes` service is DNAT'd to this
        node's own address on 6443, so its packets arrive at the host firewall
        carrying a pod source address -- DNAT rewrites the destination, not the
        source. Leave that range out and Flux, and every other in-cluster
        client, loses the API at the next activation. It presents as a broken
        cluster, not as a firewall rule.

        An empty list is refused for the same reason `null` is. It evaluates,
        and what it produces is a cluster that admits its own pods and no
        human -- a decision, if it is one, that has to be made somewhere other
        than by omission.
      '';
    };

    clusterCidr = lib.mkOption {
      type = cidr;
      default = "10.42.0.0/16";
      description = ''
        The range pods are addressed from. k3s's own default, restated here
        because the firewall rule needs it as a source and a value that does not
        match what k3s uses costs the cluster its API server. An adopter passing
        --cluster-cidr must change this to agree with it.
      '';
    };

    nodeLabels = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "chuggy.dev/durable=true" ];
      example = [ "chuggy.dev/durable=true" "chuggy.dev/pool=work" ];
      description = ''
        Labels this node registers with.

        `chuggy.dev/durable=true` marks the box that does not disappear: spot
        agents will not carry it, so chuggy pins its journal and any other
        stateful work here with a nodeSelector. `chuggy.dev/pool=work` says the
        node accepts work pods, which is a separate question from whether it
        keeps data.

        NOTE WHEN THESE TAKE EFFECT. kubelet applies --node-label at
        registration and does not reapply it to a node that already exists, so
        editing this list is what a fresh box reads and is inert on a running
        one. Fix a running node with `kubectl label node <name> <k>=<v>` and put
        the same value here, so the next box needs no fix.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.apiAllowedSources != null;
        message = ''
          chuggy.k3s.enable is on but chuggy.k3s.apiAllowedSources is unset.
          Name the source ranges allowed to reach the Kubernetes API on this
          host -- typically its LAN and the WireGuard range. There is no
          default: the safe one refuses the workstation this box is
          administered from, and the convenient one is every network it can see.
        '';
      }
      {
        assertion = cfg.apiAllowedSources != [ ];
        message = ''
          chuggy.k3s.apiAllowedSources is empty. The pod range is added to the
          rule regardless, so this builds and produces a cluster that reaches
          its own API and refuses every workstation -- a host that said nothing
          rather than a host that chose that.
        '';
      }
    ];

    services.k3s = {
      enable = true;
      role = "server";

      extraFlags = toString (
        map (label: "--node-label=${label}") cfg.nodeLabels
        ++ [
          # k3s writes /etc/rancher/k3s/k3s.yaml as root:root 0600 by default.
          # 0644 grants nothing new here: geoff already has passwordless sudo, so
          # the admin credential is reachable regardless. Revisit if these boxes
          # ever get a second human user.
          "--write-kubeconfig-mode=0644"
        ]
        ++ map (san: "--tls-san=${san}") cfg.apiSans
      );
    };

    # Bundled components are left on deliberately: traefik (ingress), servicelb
    # (LoadBalancer services), local-path (default StorageClass), coredns,
    # metrics-server. Fastest path to a usable target, each removable with one
    # flag later.
    #
    # Know the sharp edge: local-path PVCs are directories on the node that
    # created them, so a pod with a PVC is pinned to that node. Correct for the
    # durable box, wrong for spot agents -- keep stateful work on the durable
    # node via the labels above.

    # NEITHER PORT IS IN allowedTCPPorts OR allowedUDPPorts. A port in those
    # lists is open to every network the box can see; these two are open to the
    # ranges named above and refused everywhere else. It matters most for the
    # mesh: wg0 is deliberately not a trusted interface, so a peer reaches
    # exactly what these rules allow.
    #
    # AND THAT CLOSES BOTH PORTS OVER IPv6, which is a capability removed rather
    # than a scope narrowed. allowedTCPPorts emits ip46tables; these are
    # iptables, so an IPv6 client reaches neither port at all and no source list
    # can readmit it. It costs nothing here -- the mesh is IPv4, the pod range
    # is IPv4, and the `cidr` type above refuses anything else -- but a site
    # whose kubectl arrives over IPv6 needs an ip6tables arm and an address type
    # to go with it, not an entry in apiAllowedSources.
    #
    # extraCommands rather than a NixOS option because there is no option -- the
    # firewall module has no per-source form of allowedTCPPorts. These run after
    # the port rules and before the final refuse, so `-A` appends into the
    # accepting part of the chain rather than behind the reject; `-I` would work
    # too and would jump the conntrack and loopback rules for no gain.
    # tests/firewall-rules.nix is what holds that shape in place, over the
    # script this actually builds. nixpkgs refuses this configuration outright
    # under the nftables backend, which is the right failure: a rule that
    # silently did not apply would leave both ports closed and the cluster
    # unreachable.
    networking.firewall.extraCommands = lib.concatMapStrings
      (src: ''
        iptables -w -A nixos-fw -s ${lib.escapeShellArg src} -p tcp --dport 6443 -j nixos-fw-accept
        iptables -w -A nixos-fw -s ${lib.escapeShellArg src} -p udp --dport 8472 -j nixos-fw-accept
      '')
      apiSources;

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
