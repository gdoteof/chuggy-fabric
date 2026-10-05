{ pkgs, host, expectSecretRef ? null }:

let
  manifest = host.config.services.k3s.manifests.flux-sync.source;
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
  # What the manifest is held to: the host's own options, and the credential
  # reference the caller states apart from them.
  expected = pkgs.writeText "flux-wiring-expected.json" (builtins.toJSON {
    inherit (host.config.chuggy.flux)
      repositoryUrl branch sourceInterval;
    secretRef = expectSecretRef;
  });
in
pkgs.runCommand "chuggy-flux-wiring" { nativeBuildInputs = [ python ]; } ''
  manifest=${manifest}
  # `results/` is provenance the host publishes into this repository, and the
  # README says Flux applies none of it. A Kustomization pointed there would
  # hand kustomize-controller a directory of JSON records carrying no
  # kustomization, and `prune` would then own whatever it decided it applied.
  if grep -E '^ *path: \./results(/|$)' "$manifest"; then
    echo "a Kustomization applies ./results, where nothing is a manifest" >&2
    exit 1
  fi
  # The argument for each assertion is in flux-wiring.py's own header.
  python3 ${./flux-wiring.py} "$manifest" ${expected}
  touch "$out"
''
