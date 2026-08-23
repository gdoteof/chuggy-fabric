{ config, pkgs, lib, ... }:

# A second supported host, holding nothing of gtr's.
#
# This is the fixture that answers the only question the shared modules cannot
# answer about themselves: whether a machine that is not gtr can state its own
# inputs and get a working substrate, or whether something of gtr's has quietly
# become load-bearing. It is in nixosConfigurations rather than in a test
# directory so that `nix flake check` builds it, which is what keeps the answer
# current.
#
# WHAT IT DELIBERATELY DOES NOT HAVE: gtr's disks, its LAN, its mesh range, its
# peers, its Cloudflare tunnel, its DNS names, and any file it keeps a secret
# in. Adding one back here is the failure this file is watching for.
#
# EVERY ADDRESS BELOW IS FROM RFC 5737: 192.0.2.0/24 for the LAN and
# 198.51.100.0/24 for the mesh. Neither can be anyone's network, so an unedited
# copy on a real box reaches nothing rather than working against the wrong
# network -- which is what a plausible-looking 192.168.1.0/24 or 10.101.0.0/24
# would do instead, quietly and for as long as nobody looked.
#
# NOTHING REFUSES IT, and the warning below is the whole of the enforcement.
# Evaluation cannot tell an unedited copy from a host that has decided, and
# this file has to keep building or the check it exists for stops running. So
# the addresses are ones no adopter can be using, and the rebuild says so every
# time until they are changed.
#
# WHAT IT STILL INHERITS, because saying so is cheaper than a reader finding
# out: modules/common.nix declares the `geoff` account and its public SSH key,
# so this host is reachable by that person and nobody else. That is the
# repository's existing arrangement -- every box runs from this shared config --
# and the account model for a machine somebody else owns is a separate question
# from whether the substrate is machine-neutral. It is the one thing here an
# adopter has to change outside this file.
#
# An adopter starting here changes, in order: the hardware configuration, the
# hostname, the radio blacklist if the box has radios, the LAN and mesh ranges,
# and the worker budgets. Nothing else has to move.

{
  networking.hostName = "chuggy-example";

  # gtr blacklists iwlwifi and btusb for the Intel AX200 it has. Whatever this
  # machine has is a different answer, and `lspci -k` is where it comes from --
  # blacklisting a module the box does not have silently does nothing, so an
  # inherited list reads as done and is not.
  boot.blacklistedKernelModules = [ ];

  # ------------------------------------------------------------ wireguard ----

  chuggy.wireguard = {
    enable = true;
    # A different range from gtr's 10.100.0.0/24 on purpose: two independent
    # clusters that pick the same mesh range cannot later be peered, and
    # discovering that costs a rebuild of both. Documentation range rather than
    # another private one, so this file cannot be the copy that collided.
    address = "198.51.100.1/24";
    # No peers. A peer is a public key somebody sent you; there is no example
    # key that is safe to leave here, because one that got copied would be a
    # stranger's box on your mesh with an address you allocated to it.
    peers = [ ];
  };

  # ------------------------------------------------------------------ k3s ----

  chuggy.k3s = {
    enable = true;
    apiSans = [ "198.51.100.1" ];
    apiAllowedSources = [ "192.0.2.0/24" "198.51.100.0/24" ];
    nodeLabels = [ "chuggy.dev/durable=true" "chuggy.dev/pool=work" ];
  };

  # --------------------------------------------------------------- chuggy ----

  chuggy.state = {
    enable = true;
    artifacts.path = "/var/lib/chuggy/artifacts";
  };

  chuggy.secrets.enable = true;
  chuggy.images.enable = true;

  # Numbers, not a copy of gtr's numbers. They are here because the module
  # refuses to evaluate without them, which is the point: a host that has not
  # decided what a task may cost is not a supported host.
  chuggy.work = {
    enable = true;
    worker = {
      cpu = "1";
      memory = "2Gi";
      ephemeralStorage = "10Gi";
    };
  };

  # -------------------------------------------------------------- ingress ----

  # No Cloudflare tunnel and no dynamic DNS. Both need an account, a zone and a
  # credential file this repository must never hold, so an adopter who wants
  # public ingress turns chuggy.tunnel on and supplies those -- and an adopter
  # who does not gets a cluster reachable from its own LAN and mesh, which is
  # what D14 asks for anyway.
  #
  # What that costs, stated rather than left to be discovered: nothing here
  # terminates TLS. The API is exposed over the LAN and the mesh in plaintext
  # until the adopter supplies an ingress that does, and D15 says bearer tokens
  # must not cross an observable network that way. What would close it is a
  # terminator and the D20 validation that gates ingress on its material --
  # gdoteof/chuggy-fabric#10.

  # -------------------------------------------------------------- gitops ----

  chuggy.flux = {
    enable = true;
    repositoryUrl = "https://github.com/gdoteof/chuggy-fabric.git";
    branch = "main";
  };

  # The two things about this host that a copy inherits and evaluation cannot
  # catch. A warning rather than an assertion because an assertion would stop
  # `nix flake check` building the very host it exists to build; a rebuild
  # prints these, so they are in front of whoever brings the box up rather than
  # in a file they have already skimmed.
  warnings =
    lib.optional (config.chuggy.wireguard.address == "198.51.100.1/24") ''
      hosts/example: this host still carries the example's documentation
      addresses (RFC 5737), so it reaches no real network. Replace the LAN
      range, the mesh address and the API SANs with this machine's own.
    ''
    ++ lib.optional (!config.chuggy.tunnel.enable) ''
      hosts/example: nothing on this host terminates TLS, so its API is served
      in plaintext to its LAN and mesh. D15 says that is not an exposure mode;
      see gdoteof/chuggy-fabric#10.
    '';
}
