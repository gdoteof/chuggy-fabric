{
  description = "NixOS config for chuggy fabric nodes -- k3s on repurposed mini PCs";

  inputs = {
    # Pinned to the release the boxes already run. Bumping is a deliberate,
    # separate change -- do it on its own commit so a failed rebuild has one
    # obvious cause.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";

    nixos-hardware.url = "github:NixOS/nixos-hardware";
    # Without this, nixos-hardware drags in its own unstable nixpkgs purely to
    # satisfy its checks -- a second full tarball fetched for nothing.
    nixos-hardware.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, nixos-hardware, ... }:
    let
      # Every node gets the same behaviour; hosts differ only in their own
      # directory. Add a host by dropping in hosts/<name>/{default,hardware-
      # configuration}.nix and one line below.
      mkNode = { hostPath, extraModules ? [ ] }:
        nixpkgs.lib.nixosSystem {
          system = "x86_64-linux";
          modules = [
            ./modules/common.nix
            ./modules/node-prep.nix
            ./modules/wireguard.nix
            ./modules/k3s-server.nix
            ./modules/cloudflare-tunnel.nix
            ./modules/ddns.nix
            ./modules/flux.nix
            (hostPath + "/hardware-configuration.nix")
            (hostPath + "/default.nix")
          ] ++ extraModules;
        };
    in
    {
      nixosConfigurations = {
        # geoff's Beelink GTR -- AMD Ryzen 9 7940HS.
        gtr = mkNode {
          hostPath = ./hosts/gtr;
          extraModules = [
            nixos-hardware.nixosModules.common-cpu-amd
            nixos-hardware.nixosModules.common-cpu-amd-pstate
            nixos-hardware.nixosModules.common-gpu-amd
          ];
        };

        # Second dev's box: copy hosts/gtr, replace hardware-configuration.nix
        # with the output of `nixos-generate-config`, adjust the radio blacklist
        # for whatever card it has, and pick the right nixos-hardware modules.
        # Runs its own independent cluster -- same config, separate control plane.
        #
        # dev2 = mkNode {
        #   hostPath = ./hosts/dev2;
        #   extraModules = [ nixos-hardware.nixosModules.common-cpu-amd ];
        # };
      };
    };
}
