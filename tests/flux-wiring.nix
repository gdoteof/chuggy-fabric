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
  ${assertion}
  touch "$out"
''
