{ pkgs, host, expectSecretRef ? null }:

let
  manifest = host.config.services.k3s.manifests.flux-sync.source;
  assertion = if expectSecretRef == null then ''
    if grep -q 'secretRef:' "$manifest"; then
      echo "public Flux source unexpectedly carries a secretRef" >&2
      exit 1
    fi
  '' else ''
    grep -F '      secretRef:' "$manifest"
    grep -F '        name: ${expectSecretRef}' "$manifest"
  '';
in
pkgs.runCommand "chuggy-flux-wiring" { } ''
  manifest=${manifest}
  grep -F 'url: ${host.config.chuggy.flux.repositoryUrl}' "$manifest"
  grep -F 'branch: ${host.config.chuggy.flux.branch}' "$manifest"
  # `results/` is provenance the host publishes into this repository, and the
  # README says Flux applies none of it. A Kustomization pointed there would
  # hand kustomize-controller a directory of JSON records carrying no
  # kustomization, and `prune` would then own whatever it decided it applied.
  if grep -E '^ *path: \./results(/|$)' "$manifest"; then
    echo "a Kustomization applies ./results, where nothing is a manifest" >&2
    exit 1
  fi
  ${assertion}
  touch "$out"
''
