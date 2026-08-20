{ config, pkgs, lib, ... }:

# Cloudflare Tunnel as the cluster's ingress.
#
# Why this and not a port-forward: the tunnel is an *outbound* connection from
# this box to Cloudflare's edge. Nothing needs opening on the router, and the
# residential IP can change without breaking anything -- which is precisely the
# NAT problem that dropping Tailscale left behind for inbound HTTP.
#
# It solves ingress only. Node-to-node traffic (a cloud agent dialling 6443)
# still goes over the WireGuard mesh in modules/wireguard.nix, and still needs
# that UDP port-forward.
#
# Traffic path:
#   internet -> Cloudflare edge -> tunnel -> cloudflared -> Traefik :80
#            -> Ingress -> Service -> Pod
#
# cloudflared points at Traefik rather than at individual services, so Traefik
# owns per-app routing. Adding an app is: a hostname in chuggy.tunnel.hostnames,
# a DNS route, and a k8s Ingress.
#
# Only HTTP reaches the tunnel. The Kubernetes API is never an ingress rule --
# 6443 is reachable over the LAN and the WireGuard mesh, never from the edge.
#
# This is a *locally managed* tunnel: ingress rules live here, in git. Cloudflare
# recommends token-based remotely managed tunnels for new deployments, where the
# config lives in the dashboard instead. Deliberate deviation -- this repo is the
# source of truth and a second dev reuses it, so config split across a dashboard
# would defeat the point.

let
  cfg = config.chuggy.tunnel;
in
{
  options.chuggy.tunnel = {
    enable = lib.mkEnableOption "Cloudflare Tunnel ingress";

    tunnelId = lib.mkOption {
      type = lib.types.str;
      example = "1c3ce2f6-f102-4d5d-b105-8d3e11679ec2";
      description = "Tunnel UUID, from `cloudflared tunnel list`.";
    };

    credentialsFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/cloudflared/${cfg.tunnelId}.json";
      description = ''
        Tunnel credentials on the host. A path, never a value -- the file
        contains the tunnel secret and this repository is public.

        Copy it out of band: `scp ~/.cloudflared/<id>.json` then chown to the
        cloudflared user, 0400.
      '';
    };

    hostnames = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "whoami.vteng.io" ];
      description = ''
        Public hostnames routed through the tunnel, each forwarded to Traefik.
        Every one needs a CNAME to <tunnelId>.cfargotunnel.com, which
        `cloudflared tunnel route dns` creates.

        Enumerated rather than wildcarded on purpose: this list is the record of
        what is publicly reachable, and it lives in git. A `*.zone` rule would
        work and would save a rebuild per app, but then nothing in the repo says
        what is exposed.

        Traefik routes on the Host header, so each k8s Ingress must carry the
        matching name. cloudflared preserves the original Host by default.
      '';
    };

    originService = lib.mkOption {
      type = lib.types.str;
      default = "http://localhost:80";
      description = "Where cloudflared forwards to. Traefik's LoadBalancer.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.cloudflared = {
      enable = true;
      tunnels.${cfg.tunnelId} = {
        credentialsFile = cfg.credentialsFile;
        ingress = lib.genAttrs cfg.hostnames (_: cfg.originService);
        # Anything arriving for another hostname is not ours to serve.
        default = "http_status:404";
      };
    };

    # No firewall rules: the tunnel dials out. That is the whole point.
  };
}
