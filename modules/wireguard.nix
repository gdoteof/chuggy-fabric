{ config, pkgs, lib, ... }:

# WireGuard mesh for the chuggy fabric.
#
# Replaces Tailscale. What that costs us, stated plainly so nobody rediscovers it
# at 2am: Tailscale did NAT traversal -- STUN hole-punching with DERP relays as a
# fallback -- and raw WireGuard does not. k3s agents dial the server, so the
# server needs a reachable endpoint. Behind a home router that means a UDP
# port-forward and, on a residential connection, dynamic DNS. See the README.
#
# No key material belongs in this repo. The private key is generated on the host
# at first activation and never leaves it; peers carry only public keys, which are
# not secret.

let
  cfg = config.chuggy.wireguard;
in
{
  options.chuggy.wireguard = {
    enable = lib.mkEnableOption "WireGuard mesh for the chuggy fabric";

    interface = lib.mkOption {
      type = lib.types.str;
      default = "wg0";
      description = "Interface name. Also the interface k3s traffic is trusted on.";
    };

    address = lib.mkOption {
      type = lib.types.str;
      example = "10.100.0.1/24";
      description = ''
        This node's address on the mesh, with prefix. Servers take .1 in their
        own /24 by convention here; agents count up from .10.

        Pick a range that cannot collide with a cloud VPC or a home LAN you might
        later need to reach. 10.100.0.0/24 is chosen because 192.168.0.0/24 is
        already the house and 10.0.0.0/16 is a common VPC default.
      '';
    };

    listenPort = lib.mkOption {
      type = lib.types.port;
      default = 51820;
      description = "UDP port. Must be forwarded to this host for agents to connect.";
    };

    privateKeyFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/wireguard/${cfg.interface}.key";
      description = ''
        Path to the private key on the host. Generated automatically on first
        activation if absent. Deliberately a path and not a value -- putting a
        WireGuard private key in a public git repository would hand over the mesh.
      '';
    };

    peers = lib.mkOption {
      type = lib.types.listOf (lib.types.attrsOf lib.types.anything);
      default = [ ];
      example = lib.literalExpression ''
        [ { name = "spot-01";
            publicKey = "....=";
            allowedIPs = [ "10.100.0.10/32" ];
          } ]
      '';
      description = ''
        Mesh peers. Public keys only.

        Note the shape this implies for autoscaling: peers are declarative, so
        adding one is a rebuild. Ephemeral spot instances that generate their own
        keys at boot do not fit that. The README describes the pre-allocated key
        pool that does.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    networking.wireguard.interfaces.${cfg.interface} = {
      ips = [ cfg.address ];
      listenPort = cfg.listenPort;
      privateKeyFile = cfg.privateKeyFile;
      generatePrivateKeyFile = true;
      peers = map (lib.filterAttrs (n: _: n != "name")) cfg.peers;
    };

    networking.firewall = {
      allowedUDPPorts = [ cfg.listenPort ];

      # Deliberately NOT `trustedInterfaces = [ cfg.interface ]`, which is what
      # used to be here. The stated reason was that trusting the mesh kept
      # 6443/8472 off the LAN-facing rules -- but modules/k3s-server.nix opens
      # both globally anyway, so the trust bought nothing and cost a lot: it
      # handed every peer the whole box, kubelet on 10250 included, plus
      # whatever a future module happens to bind.
      #
      # A peer now reaches exactly what the global rules allow -- 22, 6443,
      # 8472/udp -- which is enough for an agent to join the cluster and for a
      # human to run kubectl, and nothing more.
      #
      # Note this widens who can *reach* sshd from LAN-only to LAN-plus-mesh.
      # Reaching it is not entering it; it still wants a key. But it moves
      # `PasswordAuthentication` from "should fix eventually" to "fix before
      # adding a human peer" -- see modules/common.nix.
    };

    environment.systemPackages = [ pkgs.wireguard-tools ];
  };
}
