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
    # Server end of the mesh. Agents count up from .10.
    address = "10.100.0.1/24";
    # peers are added as spot workers get provisioned -- see the README on the
    # pre-allocated key pool, which avoids a rebuild per instance.
    peers = [ ];
  };

  # ------------------------------------------------------------------ k3s ----

  chuggy.k3s = {
    enable = true;
    # The mesh address must be on the API certificate before any remote agent
    # dials in, or its TLS verification fails. Cheap to include now; a rebuild
    # and restart to add later.
    apiSans = [ "10.100.0.1" ];
  };
}
