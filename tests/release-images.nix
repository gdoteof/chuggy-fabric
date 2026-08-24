{ pkgs }:

let
  apiManifests = [
    ../cluster/apps/chuggy-api.yaml
    ../cluster/apps/chuggy-finalizer.yaml
    ../cluster/apps/chuggy-migrate.yaml
    ../cluster/apps/chuggy-scheduler.yaml
    ../cluster/apps/chuggy-selector.yaml
    ../cluster/apps/chuggy-ticket-service.yaml
  ];
  apiManifestDirectory = pkgs.linkFarm "chuggy-api-manifests" (
    map (path: {
      name = builtins.baseNameOf path;
      inherit path;
    }) apiManifests
  );
in
pkgs.runCommand "chuggy-release-images" { } ''
  references="$(${pkgs.gnugrep}/bin/grep -h \
    'image: registry\.chuggy\.internal/chuggy/api@sha256:' \
    ${apiManifestDirectory}/*)"
  test "$(printf '%s\n' "$references" | ${pkgs.coreutils}/bin/wc -l)" -eq 6
  test "$(printf '%s\n' "$references" | ${pkgs.coreutils}/bin/sort -u | ${pkgs.coreutils}/bin/wc -l)" -eq 1
  ${pkgs.gnugrep}/bin/grep -F \
    'image: registry.chuggy.internal/chuggy/web@sha256:' \
    ${../cluster/apps/chuggy-web.yaml} >/dev/null
  touch $out
''
