{ pkgs, lib, host }:

# What a host's firewall actually does with the Kubernetes API port and the
# flannel VXLAN port.
#
# Those two rules are the only ones in this repository that are not options.
# They are strings concatenated into networking.firewall.extraCommands, so
# nothing about them is typed and nothing about where they land in the chain is
# declared: an evaluation is equally happy with the right port, the wrong port,
# an empty source list, and a rule appended behind the final refuse. The only
# artefact that says which of those was built is the firewall script itself, so
# that is what this reads.
#
# A runCommand and not a VM, because the question is what the script contains
# and booting a machine to answer it would cost minutes and answer no more.
# What it therefore does not say is that iptables accepts the rules -- the
# `cidr` type in modules/k3s-server.nix is what guards the argument that would
# abort firewall-start, and a live `iptables -S` on the box is still the only
# thing that has seen the kernel take them.
#
# THE EXPECTED SOURCES ARE BUILT FROM THE HOST'S OPTIONS, never from the
# module's own list. A check that asked modules/k3s-server.nix which sources it
# emits would agree with it however it changed -- including when the pod range
# stopped being one of them, which is the case that module's own option
# description calls a broken cluster rather than a firewall rule.

let
  k3s = host.config.chuggy.k3s;

  # "@/nix/store/...-firewall-start/bin/firewall-start firewall-start". Read as
  # a string so that interpolating it below carries its context and the script
  # is an input of this derivation rather than a path that happens to exist.
  firewallExecStart = host.config.systemd.services.firewall.serviceConfig.ExecStart;

  # Every source the API has to be reachable from: what this host declared, and
  # the pod range, which is not the host's to declare and is why a pod reaching
  # the `kubernetes` service is not refused by its own node.
  sources = k3s.apiAllowedSources ++ [ k3s.clusterCidr ];

  apiRules = lib.concatMap
    (src: [
      "iptables -w -A nixos-fw -s ${src} -p tcp --dport 6443 -j nixos-fw-accept"
      "iptables -w -A nixos-fw -s ${src} -p udp --dport 8472 -j nixos-fw-accept"
    ])
    sources;

  # Open to every network the box can see, and meant to be: ssh is how the box
  # is administered, and a mesh port a peer cannot reach is not a mesh. They are
  # asserted here so that moving either onto the source-restricted list, or
  # moving 6443 off it, is a change this reports rather than one a reader has to
  # notice.
  globalRules = [
    "ip46tables -A nixos-fw -p tcp --dport 22 -j nixos-fw-accept"
    "ip46tables -A nixos-fw -p udp --dport ${toString host.config.chuggy.wireguard.listenPort} -j nixos-fw-accept"
  ];

  refuseRule = "ip46tables -A nixos-fw -j nixos-fw-log-refuse";

  # Every port an accept in this chain may name: the two global ones and the two
  # the module restricts by source. Anything else is a port opened to every
  # network the box can see, which is what `networking.firewall.allowedTCPPorts`
  # emits and what the whitelist above cannot see.
  acceptedPorts = [
    "22"
    (toString host.config.chuggy.wireguard.listenPort)
    "6443"
    "8472"
  ];

  # The only accepts NixOS emits into ip6tables alone: ICMPv6 and the DHCPv6
  # client. They are named line by line so that the rest of that table is read
  # like any other -- excluding the whole table is broader than the reason for
  # it, and lets a hand-written `ip6tables -A nixos-fw -i wg0 -j
  # nixos-fw-accept` in extraCommands past both checks below.
  ipv6Accepts = [
    "ip6tables -A nixos-fw -p icmpv6 -j nixos-fw-accept"
    "ip6tables -A nixos-fw -d fe80::/64 -p udp --dport 546 -j nixos-fw-accept"
  ];

  checkOnce = rule: "present_once ${lib.escapeShellArg rule}\n";
in
pkgs.runCommand "chuggy-firewall-rules-${host.config.networking.hostName}" { } ''
  exec_start='${firewallExecStart}'
  script="''${exec_start#@}"
  script="''${script%% *}"

  # The firewall module pads some of its generated lines with trailing
  # whitespace, which is not a property of the rule. Everything below matches
  # whole lines against this copy, so a rule that grew an argument is a
  # difference rather than a substring that still matches.
  sed 's/[[:space:]]*$//' "$script" > rules

  failed=0
  fail() { echo "$@" >&2; failed=1; }

  present_once() {
    n=$(grep -cxF "$1" rules || true)
    [ "$n" = 1 ] || fail "expected exactly one occurrence of: $1 (found $n)"
  }

  ${lib.concatMapStrings checkOnce (apiRules ++ globalRules ++ [ refuseRule ])}

  # Nothing else may open either port. Without this a rule added to
  # allowedTCPPorts -- which is open to every network the box can see -- would
  # sit beside the source-restricted ones and the checks above would all pass.
  n=$(grep -cE -e '--dport (6443|8472)' rules || true)
  [ "$n" = ${toString (builtins.length apiRules)} ] \
    || fail "expected ${toString (builtins.length apiRules)} rules naming 6443 or 8472, found $n"

  # EVERYTHING ABOVE IS A WHITELIST, and a rule *added* to the chain passes all
  # of it: `networking.firewall.trustedInterfaces = [ "wg0" ]` and an extra
  # entry in `allowedTCPPorts` each emit an accept that is present, is not a
  # duplicate, names neither 6443 nor 8472, and lands ahead of the refuse. The
  # two checks below are what make this a specification rather than a list, and
  # what reaches them is decided by the shape matched here:
  #
  #   * `-I` as well as `-A`, because an insert lands ahead of everything and is
  #     therefore more of an addition than an append, not less.
  #   * an interface AFTER the jump target. The per-interface forms of
  #     allowedTCPPorts, allowedUDPPorts and both port-range options append
  #     `-i <iface>` there, so a pattern anchored on `-j nixos-fw-accept` sees
  #     neither the interface nor the port of the narrowest -- and most natural
  #     -- way to open kubelet's 10250 on the house LAN.
  grep -E -e '^(ip46tables|ip6tables|iptables) .*-[AI] nixos-fw .*-j nixos-fw-accept( -i [^ ]+)?$' rules \
    | grep -vxF ${lib.concatMapStringsSep " " (r: "-e ${lib.escapeShellArg r}") ipv6Accepts} \
    > accepts || true
  [ -s accepts ] || fail "no accept was emitted into nixos-fw at all"

  # modules/wireguard.nix decides, as this repository's own decision, that the
  # mesh is not a trusted interface, and modules/k3s-server.nix repeats it. That
  # decision was checked by nothing: trusting wg0 makes every listening port on
  # the box reachable by any peer, which is the exposure wireguard.nix removed.
  # An accept naming an interface and no port is that blanket trust, and lo is
  # the only interface it may name. An accept naming an interface AND a port is
  # a different rule -- one port on one interface -- so it is the check below
  # that decides whether it may stand, not this one.
  bad=$(grep -vE -e '--dports? ' accepts | grep -E -e ' -i ' \
    | grep -vE -e ' -i lo( |$)' || true)
  [ -z "$bad" ] || fail "an accept trusts a whole interface other than lo: $bad"

  # And the same for a port. The count above bounds 6443 and 8472; this bounds
  # every other port, on every interface and on one, so kubelet's 10250 or an
  # exporter's 9100 arriving on allowedTCPPorts is a difference this reports.
  bad=$(grep -oE -e '--dports? [0-9,:]+' accepts | sort -u \
    | grep -vxE -e '--dport (${lib.concatStringsSep "|" acceptedPorts})' || true)
  [ -z "$bad" ] || fail "an accept opens a port this host does not declare: $bad"

  # Position, which is the half no amount of reading the rule text can settle:
  # nixos-fw-log-refuse ends the chain, so an accept appended after it is an
  # accept that is never reached.
  refuse=$(grep -nxF ${lib.escapeShellArg refuseRule} rules | cut -d: -f1)
  last=$(grep -nE '^iptables -w -A nixos-fw -s ' rules | tail -1 | cut -d: -f1)
  if [ -z "$last" ]; then
    fail "no source-restricted accept was emitted at all"
  elif [ "$last" -ge "$refuse" ]; then
    fail "a source-restricted accept at line $last lands at or after the refuse at line $refuse"
  fi

  if [ "$failed" != 0 ]; then
    echo "--- what the firewall script does to the nixos-fw chain ---" >&2
    grep -n 'nixos-fw' rules >&2
    exit 1
  fi
  touch $out
''
