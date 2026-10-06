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
        ./modules/github-app-token.nix
        ./modules/chuggy-images.nix
        ./modules/chuggy-work.nix
        ./modules/mini-chuggy.nix
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

      accepts = name: overrides:
        let
          messages = refusalsOf overrides;
        in
        pkgs.runCommand "chuggy-accepts-${name}" { } (
          if messages == [ ]
          then "touch $out"
          else ''
            echo "unexpected refusal: ${lib.escapeShellArg (lib.concatStringsSep " || " messages)}" >&2
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
      dumpsWiring = host: import ./tests/dumps-wiring.nix { inherit pkgs host; };
      rolloutOrder = host: import ./tests/rollout-order.nix { inherit pkgs host; };
      dumpScript = import ./tests/dump-script.nix { inherit pkgs; };
      chugCi = import ./tests/chug-ci.nix { inherit pkgs; };
      fluxWiring = host: expectSecretRef:
        import ./tests/flux-wiring.nix { inherit pkgs host expectSecretRef; };
      fluxLayers = host: import ./tests/flux-layers.nix { inherit pkgs host; };
      fluxReleaseSource = host:
        import ./tests/flux-release-source.nix { inherit pkgs host; };
      fluxComponents = host:
        import ./tests/flux-components.nix { inherit pkgs host; };
      buildPlatform = import ./tests/build-platform.nix { inherit pkgs; };
      releasePipeline = import ./tests/release-pipeline.nix { inherit pkgs; };
      releaseTrigger = import ./tests/release-trigger.nix { inherit pkgs; };
      releasePublish = import ./tests/release-publish.nix { inherit pkgs; };
      releaseBuild = import ./tests/release-build.nix { inherit pkgs; };
      releaseReport = import ./tests/release-report.nix { inherit pkgs; };
      releaseAlert = import ./tests/release-alert.nix { inherit pkgs; };
      configurationImporter = import ./tests/configuration-importer.nix { inherit pkgs; };
      developmentWorker = import ./tests/development-worker.nix { inherit pkgs; };
      sessionPlacement = import ./tests/session-placement.nix { inherit pkgs; };
      selectorReach = import ./tests/selector-reach.nix { inherit pkgs; };
      githubRepositoryTransition = import ./tests/github-repository-transition.nix { inherit pkgs; };
      githubAppToken = import ./tests/github-app-token.nix { inherit pkgs; };
      forgeAppKey = import ./tests/forge-app-key.nix {
        inherit pkgs;
        apps = self.nixosConfigurations.gtr.config.chuggy.githubAppTokens.apps;
      };
      actionReporters = import ./tests/action-reporters.nix {
        inherit pkgs;
        host = self.nixosConfigurations.gtr;
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

        # The second supported host: a machine that is not gtr, stating its own
        # inputs. It is a real nixosConfiguration rather than a fixture tucked
        # into a test, because what is worth checking is that it builds the same
        # way gtr does -- see hosts/example/default.nix. Its hardware
        # configuration is a placeholder and will not boot on your machine until
        # you replace it.
        example = mkNode { hostPath = ./hosts/example; };

        # The portable one-node role uses the same deliberately inert host
        # inputs as example while proving that every Chuggy responsibility can
        # coexist on one machine.
        mini-example = mkNode {
          hostPath = ./hosts/example;
          extraModules = [ ./examples/mini-chuggy-node.nix ];
        };
      };

      checks.${system} = {
        # Both hosts build. gtr is the running box; example is the claim that
        # nothing of gtr's has become load-bearing in modules/.
        gtr = self.nixosConfigurations.gtr.config.system.build.toplevel;
        example = self.nixosConfigurations.example.config.system.build.toplevel;
        mini-example = self.nixosConfigurations.mini-example.config.system.build.toplevel;
        development-worker = developmentWorker;

        # The session pod's labels and the four objects that select them, held
        # against the rendered cluster rather than against the files: the way
        # this goes wrong is a pod no policy selects, which is unisolated in
        # both directions and looks correct in every file separately.
        session-placement = sessionPlacement;

        # Where the selector is configured to go against where it is permitted
        # to go: two halves of one reach, in a JSON string and in a policy, each
        # of which reads correctly while the other is wrong.
        selector-reach = selectorReach;

        # Which of Keto's two ports is reachable from where. The write port
        # grants permission and authenticates nobody, and the way it comes open
        # is a pod that no policy in `ory` selects -- which denies nothing and
        # looks correct in every file separately.
        keto = import ./tests/keto.nix { inherit pkgs; };

        # Who may reach Hydra's and Kratos's admin ports, which register any
        # client and create any identity: `ory`, and the API on Hydra's alone.
        ory-admin = import ./tests/ory-admin.nix { inherit pkgs; };

        # The rendered cluster, which must carry no per-repository token at
        # all now that every pod mints its own.
        github-repository-transition = githubRepositoryTransition;
        github-app-token = githubAppToken;

        # An App id, a file a process opens and a projection that puts a key
        # there. The host mints from the same Apps, so the id in a manifest is a
        # copy of the host's, and a key file nothing projects is an error at the
        # first mint rather than at start-up.
        forge-app-key = forgeAppKey;

        # A roster the API reads, a file each reporter is verified by, the
        # Secret the host makes for it, the release run that presents one and
        # the Provider Flux signs a rollout's events with another: each a name
        # written in two places, and a report answered 404 when they differ.
        action-reporters = actionReporters;

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

        refuses-without-dumps-path =
          refuses "without-dumps-path"
            { chuggy.state.dumps.path = lib.mkForce null; }
            "chuggy.state.dumps.path is unset";

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

        # The dumps directory is one path written twice, as a host option and
        # as a PersistentVolume's. gtr alone, because `cluster/apps` is the
        # cluster gtr follows and the example follows a repository of its own.
        dumps-wiring-gtr = dumpsWiring self.nixosConfigurations.gtr;

        # What makes a release roll out in order that the layer declarations
        # do not say: which rendered directory each object is in, and the
        # order inside the pod that dumps and then migrates. gtr, for the
        # reason above and because the uid that pod writes the dump as is held
        # to the owner gtr gives the directory.
        rollout-order-gtr = rolloutOrder self.nixosConfigurations.gtr;

        # And the dump itself: the script that pod mounts, run by the command
        # the pod gives it, against a PostgreSQL started for the purpose.
        dump-script = dumpScript;

        # The registry's public front: an Ingress into its namespace puts every
        # request to the pool plane first and reaches nothing that can write.
        registry-public = import ./tests/registry-public.nix { inherit pkgs; };

        # The release dashboard: a link from it to its data breaks silently, so
        # the ones release-dashboard.py's header lists are held on what the tree
        # declares.
        release-dashboard = import ./tests/release-dashboard.nix { inherit pkgs; };

        # The evaluator command a Chuggy ticket runs, and the only check that
        # reads .chug/tasks/ci.sh.
        chug-ci = chugCi;

        # The bootstrap check proves no in-cluster credential is required before
        # Kubernetes exists. The cutover check changes URL, branch, and Secret
        # reference together, which is the two-stage transition in the runbook.
        flux-wiring-bootstrap = fluxWiring self.nixosConfigurations.gtr null;
        flux-wiring-private-cutover = fluxWiring
          (mkNode {
            hostPath = ./hosts/example;
            extraModules = [{
              chuggy.flux.repositoryUrl = lib.mkForce "ssh://git@git.internal/fabric.git";
              chuggy.flux.secretRef = "fabric-source-auth";
              chuggy.flux.branch = lib.mkForce "mini-release";
            }];
          })
          "fabric-source-auth";

        # The layers gtr's root Kustomization applies, rendered from the
        # directory it names, against the spec each is held to.
        flux-layers = fluxLayers self.nixosConfigurations.gtr;

        # The files gtr's narrowed source keeps of this repository. The lines
        # that narrow it are the module's and no host's, so one host reads
        # them for all.
        flux-release-source = fluxReleaseSource self.nixosConfigurations.gtr;

        # The Flux install gtr hands k3s, on who its NetworkPolicies let post
        # to notification-controller. The file is the module's and no host's,
        # so one host reads it for all.
        flux-components = fluxComponents self.nixosConfigurations.gtr;

        # What a build stands on and no render shows; the file says which.
        build-platform = buildPlatform;

        # The release pipeline, which only a person starts while its trigger
        # is suspended: what its manifests give a pod and what they keep from
        # one, and everything a first run would otherwise be the one to find.
        release-pipeline = releasePipeline;

        # The trigger's decision, every line of it, by the script its pod
        # mounts against an API server that is a file.
        release-trigger = releaseTrigger;

        # And what a run publishes: the overlay over this repository's own two
        # release directories, what it may change and must, and the version
        # it may be pushed under.
        release-publish = releasePublish;

        # And the two steps before it: one commit fetched by its hash, and
        # whether its image is the registry's or is built, against a
        # repository and a registry that are this build's own.
        release-build = releaseBuild;

        # And the one after it: what a run tells chuggy of each task that
        # ended, against an API that is this build's own, whatever that API
        # answers and when it answers nothing.
        release-report = releaseReport;

        # And what says so when the trigger stops: the alert, evaluated over
        # what a CronJob is exported as, suspended and not.
        release-alert = releaseAlert;

        configuration-importer = configurationImporter;
      };
    };
}
