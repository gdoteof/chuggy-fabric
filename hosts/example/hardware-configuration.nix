{ lib, ... }:

# NOT a real machine's hardware, and not the output of nixos-generate-config.
#
# It exists so `hosts/example` evaluates and builds a system closure without
# borrowing gtr's disks, and it names filesystems by label rather than by UUID
# for the same reason a UUID would be wrong here: a UUID identifies one
# partition on one box, and copying one into a second host's file is how two
# machines end up claiming the same disk in git.
#
# AN ADOPTER REPLACES THIS FILE. Run nixos-generate-config on the target and
# copy its hardware-configuration.nix over this one. What is here will build and
# will not boot: nothing on your machine is labelled `nixos` unless you labelled
# it, and the initrd module list below is a guess at a generic UEFI box rather
# than a scan of yours.

{
  boot.initrd.availableKernelModules = [ "xhci_pci" "ahci" "nvme" "usbhid" "sd_mod" ];
  boot.initrd.kernelModules = [ ];
  boot.kernelModules = [ ];
  boot.extraModulePackages = [ ];

  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };

  fileSystems."/boot" = {
    device = "/dev/disk/by-label/ESP";
    fsType = "vfat";
  };

  swapDevices = [ ];

  networking.useDHCP = lib.mkDefault true;

  nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
}
