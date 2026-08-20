{
  description = "NixOS configuration for the Beelink GTR node (host: nixos, 192.168.0.114)";

  inputs = {
    # Pinned to the release the box already runs. Bumping to a newer release is a
    # deliberate, separate change -- do it on its own commit so a failed rebuild
    # has one obvious cause.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";

    # Replaces the three /home/geoff/nixconfig/nixos-hardware/... imports the old
    # config used. Same upstream repo, pinned in flake.lock instead of depending on
    # a directory that is scheduled for deletion.
    nixos-hardware.url = "github:NixOS/nixos-hardware";
    # Without this, nixos-hardware drags in its own (unstable) nixpkgs purely to
    # satisfy its checks -- a second full tarball fetched for nothing.
    nixos-hardware.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }: {
    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        nixos-hardware.nixosModules.common-cpu-amd
        nixos-hardware.nixosModules.common-cpu-amd-pstate
        nixos-hardware.nixosModules.common-gpu-amd

        ./hosts/nixos/hardware-configuration.nix
        ./hosts/nixos/default.nix
        ./modules/node-prep.nix
      ];
    };
  };
}
