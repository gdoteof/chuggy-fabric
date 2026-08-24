{ config, pkgs, lib, ... }:

{
  # ---------------------------------------------------------------- boot ----

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  # The ESP is 511 MB and each generation costs ~37 MB of initrd. Without a cap
  # it fills up and rebuilds start failing to install their kernel, which is
  # exactly how /boot reached 96% before.
  boot.loader.systemd-boot.configurationLimit = 10;

  # ------------------------------------------------------------- identity ----
  # hostName is set per-host in hosts/<name>/default.nix

  time.timeZone = "America/New_York";
  i18n.defaultLocale = "en_US.UTF-8";

  # ---------------------------------------------------------------- nix -----

  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Keep the store from creeping back to 217 GB.
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 30d";
  };
  nix.optimise.automatic = true;

  # Retained from the previous config. Nothing unfree is currently pulled in now
  # that the DisplayLink driver is gone, but leaving it on avoids a surprise
  # eval failure later.
  nixpkgs.config.allowUnfree = true;

  # -------------------------------------------------------------- network ----

  # NetworkManager is heavier than a server needs, but it is what currently holds
  # the DHCP lease on enp2s0. Swapping to systemd-networkd is a change worth making
  # from the console, not over the SSH session it would interrupt.
  networking.networkmanager.enable = true;

  networking.firewall = {
    enable = true;
    # Was [ 2375 22 80 443 ] plus the range 4000-5550 and UDP 24800.
    #   2375      -- unauthenticated, unencrypted Docker daemon API. Nothing was
    #                bound to it, but the hole was declared. Removed.
    #   80/443    -- no web server on this host.
    #   4000-5550 -- 1551 ports for long-dead dev servers.
    #   24800/udp -- Synergy. The desktop is gone.
    # k8s ports get added when the distro is chosen.
    allowedTCPPorts = [ 22 ];
  };


  # --------------------------------------------------------------- access ----

  services.openssh = {
    enable = true;
    settings = {
      PermitRootLogin = "no";

      # Both of these, not just the first. Disabling PasswordAuthentication on
      # its own leaves keyboard-interactive, which PAM answers with a password
      # prompt -- the door looks shut and is not.
      #
      # What makes this safe to turn on is that key auth is already proven, not
      # assumed. What it costs: ~geoff/.ssh/authorized_keys becomes the only way
      # in, and that file is imperative state this repo does not declare, so a
      # freshly built box has no key in it and no password fallback either.
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
    };
  };

  security.sudo.wheelNeedsPassword = false;

  users.users.geoff = {
    isNormalUser = true;
    description = "geoff";
    extraGroups = [ "networkmanager" "wheel" "docker" ];
    shell = pkgs.zsh;

    # The only way into this box now that password auth is off. These lived
    # solely in ~/.ssh/authorized_keys before -- imperative state a rebuilt
    # machine would not have, leaving a box with no way in at all. That is the
    # gap this closes.
    #
    # Public keys are not secret and belong in a public repo; the same argument
    # this repo already makes for WireGuard peers. GitHub hands anyone's out at
    # github.com/<user>.keys.
    #
    # These are additive, not authoritative: NixOS writes them to
    # /etc/ssh/authorized_keys.d/geoff, and sshd's AuthorizedKeysFile lists that
    # *alongside* ~/.ssh/authorized_keys. The imperative file keeps working until
    # it is deleted, which is the step that makes this the single source of
    # truth -- and the step to take only after a rebuild proves these work.
    openssh.authorizedKeys.keys = [
      # Workstation "shame". Two 3072-bit RSA keys from a Mac mini were dropped
      # here rather than carried forward: same comment, different fingerprints,
      # and no login on record between them. If that machine comes back, it gets
      # a fresh ed25519 rather than a resurrected key nobody can account for.
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID+SRfaxLzKg91rkDZbC+ybupon0rG3iU+m2Fwp4bFlm geoff@shame"
    ];
  };

  # A second human on the box, reachable only over the WireGuard mesh (its peer
  # is declared in hosts/gtr/default.nix). dev2 already holds cluster-admin via
  # cluster/apps/dev2-access.yaml; on this single node that is root-equivalent
  # already -- a cluster-admin can schedule a privileged host-mounting pod, and
  # the kubeconfig is 0644, so the system:masters cert is theirs to read. This
  # block does not widen that power; it makes it a usable shell for bootstrap
  # imports and host diagnostics. Registry-backed releases retire routine
  # imports once the remaining `chuggy.invalid` references migrate.
  #
  # THE COST, stated so the next reader sees it beside the grant: this softens
  # the revocation story dev2-access.yaml rests on. That file prefers a
  # ServiceAccount to a client cert because deleting the SA invalidates every
  # token at once, whereas a cert cannot be revoked short of rotating the CA. A
  # wheel shell reintroduces the un-revocable half -- the 0644 system:masters
  # cert is copyable from any root shell here -- so cutting dev2 off now means
  # deleting this user AND rotating what a root shell could have taken, not just
  # deleting the ServiceAccount. Accepted deliberately for a rig; revisit with
  # --write-kubeconfig-mode=0600 (see modules/k3s-server.nix) if it ever isn't.
  users.users.dev2 = {
    isNormalUser = true;
    description = "dev2 (david)";
    # wheel -> passwordless sudo; docker -> build images on the box.
    # Same pair geoff carries; both are root-equivalent, matching the access
    # dev2 already holds rather than pretending to a boundary sudo erases.
    extraGroups = [ "wheel" "docker" ];
    shell = pkgs.zsh;

    # Public key only, same argument as geoff's above: not secret, belongs in a
    # public repo, and the single way in while password auth is off.
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBI+Q42CQ3DZ0/+ocfwTEqsLXFSO/ano20kVH+jkGk3e david@Mac.lan"
    ];
  };

  # users.users.geoff.shell points here -- dropping this block breaks login.
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestions.enable = true;
    syntaxHighlighting.enable = true;
    ohMyZsh = {
      enable = true;
      theme = "lambda";
      plugins = [ "git" ];
    };
  };

  # -------------------------------------------------------------- packages ----

  environment.systemPackages = with pkgs; [
    # basics
    wget curl git rsync tree jq gnumake fzf vifm-full
    # diagnostics -- nvme-cli and smartmontools were both missing when the SSD
    # health check was needed, which meant shelling out to nix-shell to read it.
    htop tmux nvme-cli smartmontools pciutils usbutils bind
    # nix tooling
    nixpkgs-fmt
  ];

  # ------------------------------------------------------------- container ----

  # Left enabled: the box still has containers on it and Docker is not in k3s's
  # way. Revisit when the k8s distro lands -- k3s ships its own containerd, so
  # this may become redundant.
  virtualisation.docker.enable = true;

  # ------------------------------------------------------------------ state ----

  # Frozen at the original install value on purpose. This is not a "current
  # version" field and must not be bumped to match the release.
  system.stateVersion = "23.05";
}
