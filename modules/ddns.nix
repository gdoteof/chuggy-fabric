{ config, pkgs, lib, ... }:

# Dynamic DNS, so the mesh endpoint survives the ISP changing our address.
#
# This is the other half of the NAT problem that dropping Tailscale left behind.
# The Cloudflare Tunnel solved inbound HTTP; it cannot solve this, because
# `cloudflared tunnel route dns` only ever writes a *proxied CNAME* pointing at
# the tunnel, and WireGuard is UDP -- it does not go through the tunnel at all.
# What a peer needs is a plain A record holding the real address.
#
# Hence a record that is deliberately NOT proxied. Grey cloud, real IP, publicly
# visible. That is the trade: the house address becomes a matter of public
# record. It is defensible because WireGuard does not answer unauthenticated
# packets at all -- no handshake, no error, nothing -- so a scan of the port
# finds a closed one. Do not put anything on this name that does answer.
#
# Client-side gotcha, and it is the reason people think DDNS "did not work":
# WireGuard resolves a peer's Endpoint *once*, when the interface comes up, and
# never again. Updating the record does not move an established client. The peer
# has to re-resolve -- wireguard-tools ships `reresolve-dns.sh` for exactly this,
# usually on a timer. Nothing on this box needs it, since peers dial us.

let
  cfg = config.chuggy.ddns;
in
{
  options.chuggy.ddns = {
    enable = lib.mkEnableOption "Cloudflare dynamic DNS for this host's public IP";

    domains = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "gtr-ip.vteng.io" ];
      description = ''
        Names to point at this host's current public address.

        Name them per host rather than per service. `gtr-ip` says whose address
        it is, which matters once a second box has one too -- and it reads
        differently from the tunnel's CNAMEs in the same zone, which is the
        point. Anything on those goes through Cloudflare; this one does not.
      '';
    };

    apiTokenFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/cloudflare-dyndns/token";
      description = ''
        Path to the Cloudflare API token, in the form:

          CLOUDFLARE_API_TOKEN=...

        A path, never a value -- this repository is public. Same rule as the
        tunnel credential and the Grafana admin secret.

        Scope it to Zone:DNS:Edit on the one zone. An account-wide token in a
        file on a box that is reachable from the internet is a bad trade for the
        thirty seconds it saves.
      '';
    };

    frequency = lib.mkOption {
      type = lib.types.str;
      default = "*:0/5";
      description = ''
        systemd calendar spec. Every five minutes by default: an ISP address
        change is rare, and the window of a stale record is what a peer
        experiences as an outage.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [{
      assertion = cfg.domains != [ ];
      message = "chuggy.ddns.enable is on but chuggy.ddns.domains is empty; nothing would be updated.";
    }];

    # The upstream module hands the token to systemd as an EnvironmentFile, which
    # means the file must be a `KEY=value` line and not a bare token. Get that
    # wrong and systemd silently sets nothing; the failure surfaces later, from a
    # different process, as `Missing option '--api-token'` -- which points at the
    # command line rather than at the file that is actually wrong.
    #
    # So check it up front and say what is wrong. `-` on EnvironmentFile makes a
    # missing file non-fatal to systemd, which lets this run and produce a better
    # message than "Failed with result 'resources'".
    systemd.services.cloudflare-dyndns.serviceConfig = {
      EnvironmentFile = lib.mkForce "-${cfg.apiTokenFile}";
      ExecStartPre = [
        ("+" + pkgs.writeShellScript "chuggy-ddns-check-token" ''
          f=${cfg.apiTokenFile}
          if [ ! -e "$f" ]; then
            echo "chuggy.ddns: $f does not exist." >&2
            echo "Create it with a Cloudflare token scoped to Zone:DNS:Edit on your zone:" >&2
            echo "  CLOUDFLARE_API_TOKEN=<token>" >&2
            exit 1
          fi
          if ! ${pkgs.gnugrep}/bin/grep -q '^CLOUDFLARE_API_TOKEN=.' "$f"; then
            echo "chuggy.ddns: $f is not in systemd EnvironmentFile form." >&2
            echo "It needs the variable name, not just the token:" >&2
            echo "  CLOUDFLARE_API_TOKEN=<token>" >&2
            exit 1
          fi
        '')
      ];
    };

    services.cloudflare-dyndns = {
      enable = true;
      inherit (cfg) domains apiTokenFile frequency;
      # Must stay false. A proxied record resolves to Cloudflare's edge, which
      # does not forward UDP -- the peer would dial the wrong host entirely.
      proxied = false;
      ipv4 = true;
      # The mesh is v4-only; a AAAA record here would be a name that resolves to
      # an address nothing is listening on.
      ipv6 = false;
    };
  };
}
