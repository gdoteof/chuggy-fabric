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
  boot.blacklistedKernelModules = [
    "iwlwifi"  # Intel Wi-Fi 6 AX200
    "btusb"    # Bluetooth radio on the same card
  ];
  systemd.services.wpa_supplicant.enable = false;

  # ------------------------------------------------------------------ k3s ----

  chuggy.k3s.enable = true;

  # tailscaleName stays null until tailscaled is logged in on this box -- it
  # currently reports NeedsLogin. Set it to the tailnet DNS name before any
  # cloud agent tries to join, or their TLS verification will fail.
  # chuggy.k3s.tailscaleName = "gtr.<tailnet>.ts.net";
}
