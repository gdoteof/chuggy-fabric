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
      system = "x86_64-linux";
      lib = nixpkgs.lib;
      pkgs = nixpkgs.legacyPackages.${system};

      # Every node gets the same behaviour; hosts differ only in their own
      # directory. Add a host by dropping in hosts/<name>/{default,hardware-
      # configuration}.nix and one line below.
      substrate = [
        ./modules/common.nix
        ./modules/node-prep.nix
        ./modules/wireguard.nix
        ./modules/k3s-server.nix
        ./modules/chuggy-state.nix
        ./modules/chuggy-secrets.nix
        ./modules/chuggy-images.nix
        ./modules/chuggy-work.nix
        ./modules/cloudflare-tunnel.nix
        ./modules/ddns.nix
        ./modules/flux.nix
      ];

      mkNode = { hostPath, extraModules ? [ ] }:
        nixpkgs.lib.nixosSystem {
          inherit system;
          modules = substrate ++ [
            (hostPath + "/hardware-configuration.nix")
            (hostPath + "/default.nix")
          ] ++ extraModules;
        };

      # The messages an evaluation would refuse with. Reading config.assertions
      # rather than catching the throw is what lets a check name *which* refusal
      # it expected: builtins.tryEval reports that something failed and never
      # says what, so a check built on it passes when the wrong thing breaks.
      refusalsOf = overrides:
        map (a: a.message)
          (lib.filter (a: !a.assertion)
            (mkNode { hostPath = ./hosts/example; extraModules = [ overrides ]; }).config.assertions);

      # Fails the build unless one override of a required input produces a
      # refusal that names it. The interesting half is the negative: a module
      # that quietly grew a default, or an assertion that reads a value it does
      # not mean to accept, would still evaluate -- and this is what notices.
      refuses = name: overrides: expected:
        let
          messages = refusalsOf overrides;
        in
        pkgs.runCommand "chuggy-refuses-${name}" { } (
          if lib.any (m: lib.hasInfix expected m) messages
          then "touch $out"
          else ''
            echo "hosts/example evaluated with the ${name} override, or refused for another reason." >&2
            echo "expected a refusal mentioning: ${expected}" >&2
            echo "got: ${lib.escapeShellArg (lib.concatStringsSep " || " messages)}" >&2
            exit 1
          ''
        );

      # The same for what hosts/example says rather than refuses. An example has
      # to keep evaluating -- it is the host `nix flake check` builds -- so where
      # a real host would assert, it warns, and these are what hold the warning
      # in place: an example edited into something plausible stops saying it and
      # this is what notices.
      warns = name: expected:
        let
          messages = (mkNode { hostPath = ./hosts/example; }).config.warnings;
        in
        pkgs.runCommand "chuggy-warns-${name}" { } (
          if lib.any (m: lib.hasInfix expected m) messages
          then "touch $out"
          else ''
            echo "hosts/example no longer warns about ${name}." >&2
            echo "expected a warning mentioning: ${expected}" >&2
            echo "got: ${lib.escapeShellArg (lib.concatStringsSep " || " messages)}" >&2
            exit 1
          ''
        );

      firewallRules = host: import ./tests/firewall-rules.nix { inherit pkgs lib host; };
      registryWiring = host: import ./tests/registry-wiring.nix { inherit pkgs host; };
      releaseImages = import ./tests/release-images.nix { inherit pkgs; };
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

        # The second supported host: a machine that is not gtr, stating its own
        # inputs. It is a real nixosConfiguration rather than a fixture tucked
        # into a test, because what is worth checking is that it builds the same
        # way gtr does -- see hosts/example/default.nix. Its hardware
        # configuration is a placeholder and will not boot on your machine until
        # you replace it.
        example = mkNode { hostPath = ./hosts/example; };
      };

      checks.${system} = {
        # Both hosts build. gtr is the running box; example is the claim that
        # nothing of gtr's has become load-bearing in modules/.
        gtr = self.nixosConfigurations.gtr.config.system.build.toplevel;
        example = self.nixosConfigurations.example.config.system.build.toplevel;

        # D30 and D14 in a form a check can hold: an enabled host that has not
        # said what a task may cost, or who may reach its API, is refused rather
        # than built against a guess.
        refuses-without-worker-cpu =
          refuses "without-worker-cpu"
            { chuggy.work.worker.cpu = lib.mkForce null; }
            "chuggy.work.worker.cpu is unset";

        refuses-without-worker-memory =
          refuses "without-worker-memory"
            { chuggy.work.worker.memory = lib.mkForce null; }
            "chuggy.work.worker.memory is unset";

        refuses-without-worker-ephemeral-storage =
          refuses "without-worker-ephemeral-storage"
            { chuggy.work.worker.ephemeralStorage = lib.mkForce null; }
            "chuggy.work.worker.ephemeralStorage is unset";

        refuses-without-artifacts-path =
          refuses "without-artifacts-path"
            { chuggy.state.artifacts.path = lib.mkForce null; }
            "chuggy.state.artifacts.path is unset";

        refuses-without-registry-path =
          refuses "without-registry-path"
            { chuggy.state.registry.path = lib.mkForce null; }
            "chuggy.state.registry.path is unset";

        refuses-without-api-allowed-sources =
          refuses "without-api-allowed-sources"
            { chuggy.k3s.apiAllowedSources = lib.mkForce null; }
            "chuggy.k3s.apiAllowedSources is unset";

        refuses-without-flux-repository =
          refuses "without-flux-repository"
            { chuggy.flux.repositoryUrl = lib.mkForce null; }
            "chuggy.flux.repositoryUrl is unset";

        # An empty list is not the same omission and needs its own check: it
        # satisfies `!= null`, so the refusal above would have passed a host
        # whose firewall admits its own pods and nobody else.
        refuses-with-empty-api-allowed-sources =
          refuses "empty-api-allowed-sources"
            { chuggy.k3s.apiAllowedSources = lib.mkForce [ ]; }
            "chuggy.k3s.apiAllowedSources is empty";

        # The three things about the example that only a reader would otherwise
        # catch: that its addresses are still the ones nobody can be using, that
        # nothing on it terminates TLS, and that it follows no repository.
        warns-about-documentation-addresses =
          warns "documentation-addresses" "still carries the example's documentation";

        warns-about-plaintext-ingress =
          warns "plaintext-ingress" "nothing on this host terminates TLS";

        warns-about-documentation-repository =
          warns "documentation-repository" "repositoryUrl still names the documentation";

        # Named for the modules it boots -- chuggy-state, chuggy-secrets,
        # chuggy-images and chuggy-work -- rather than for the substrate: the
        # other seven in the list above are not imported there, and a name that
        # said substrate would be reporting on them without having built one.
        state-and-secrets-boot = import ./tests/state-and-secrets.nix { inherit pkgs; };

        # What the firewall a host builds does with 6443 and 8472, read off the
        # built script. Both hosts, because the rule is generated per host from
        # that host's own source list; a check that ran on one of them would be
        # silent about the shape of the other.
        firewall-rules-gtr = firewallRules self.nixosConfigurations.gtr;
        firewall-rules-example = firewallRules self.nixosConfigurations.example;

        # The node's containerd endpoint and the Service address are one
        # contract even though NixOS and Kubernetes consume different files.
        registry-wiring-gtr = registryWiring self.nixosConfigurations.gtr;
        registry-wiring-example = registryWiring self.nixosConfigurations.example;
        release-images = releaseImages;
      };
    };
}
