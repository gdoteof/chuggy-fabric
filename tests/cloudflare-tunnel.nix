{ pkgs, host }:

# The tunnel unit a host builds restarts after a pause and has no start limit.
#
# Without both, a boot whose DNS is late spends systemd's default burst of five
# immediate restarts inside a second and leaves the unit failed, with every
# public hostname down until someone starts it by hand. The unit is generated
# by the nixpkgs cloudflared module and amended by modules/cloudflare-tunnel.nix,
# so what is read here is the unit file systemd is given, not either module.

let
  name = "cloudflared-tunnel-${host.config.chuggy.tunnel.tunnelId}.service";
  unit = "${host.config.systemd.units.${name}.unit}/${name}";
in
pkgs.runCommand "chuggy-cloudflare-tunnel" { } ''
  for line in 'Restart=on-failure' 'RestartSec=5' 'StartLimitIntervalSec=0'; do
    grep -qx "$line" ${unit} || {
      echo "${name} does not carry $line" >&2
      cat ${unit} >&2
      exit 1
    }
  done
  touch $out
''
