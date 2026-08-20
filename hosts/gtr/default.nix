{ config, pkgs, lib, ... }:

# Beelink GTR (AZW GTR V11) -- Ryzen 9 7940HS, 32 GB, 1 TB NVMe, 2x 1GbE.
# Everything here is true of this machine specifically. Shared behaviour lives in
# modules/.

{
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
    enable = true;
    # The mesh address must be on the API certificate before any remote agent
    # dials in, or its TLS verification fails. Cheap to include now; a rebuild
    # and restart to add later.
    apiSans = [ "10.100.0.1" ];
  };

  # -------------------------------------------------------------- ingress ----

  # Cloudflare Tunnel. Outbound-only, so no router port-forward and no dynamic
  # DNS -- unlike the WireGuard mesh above, which still needs both.
  chuggy.tunnel = {
    enable = true;
    tunnelId = "84115dde-a1d0-4e8a-832a-e4da2cf98180";  # tunnel "gtr"
    hostnames = [ "whoami.vteng.io" "grafana.vteng.io" ];
  };

  # -------------------------------------------------------------- gitops ----

  # k3s applies Flux at startup; Flux reconciles cluster/apps from this repo.
  # Nothing in the cluster is applied by hand.
  chuggy.flux.enable = true;
}
