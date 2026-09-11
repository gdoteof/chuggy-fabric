# The repositories whose images this site builds, and the one place they are
# declared.
#
# A repository reaches the control plane by being bound to a project over the
# API, and every credential a control-plane pod needs for it that pod mints for
# itself from the portal App key it mounts. What that leaves per repository is
# the image build: Shipwright clones the source with a Git basic-auth Secret
# the build request names, and a build is not one of this cluster's processes,
# so nothing mints it for itself.
#
# SO AN ENTRY HERE IS A REPOSITORY THIS SITE BUILDS IMAGES FOR, and not a
# repository the cluster can run work on. `hosts/gtr/default.nix` mints the
# clone credential from the entry, `tests/github-repository-transition.py`
# refuses a build request whose source or clone Secret is not the entry's, and
# nothing else reads this file.
#
# THE KEY IS THE REPOSITORY'S NAME ON GITHUB, under `owner`, which is what lets
# one entry name the repository in its URL and in its Secret without repeating
# the name.
#
# THE INSTALLATION ID IS PER OWNER AND PER APP. A GitHub App installation is an
# owner's, so a repository under a second owner is a second installation of the
# portal App even though the App is the same one. It is readable from that
# account's app settings page and nowhere else.

let
  site = {
    chuggy = {
      owner = "kasofsk";
      portalInstallationId = "156333284";
    };
  };
in
builtins.mapAttrs
  (name: entry: {
    inherit (entry) owner;

    # What a build request addresses the source by.
    github = "https://github.com/${entry.owner}/${name}.git";

    # Exactly the shape `chuggy.githubAppTokens.repositories` takes, so a host
    # passes it through rather than restating it. The role the Secret serves is
    # modules/github-app-token.nix's; the name is here because the build
    # requests that clone with it are held against this.
    tokens = {
      repository = name;
      inherit (entry) portalInstallationId;
      buildReaderSecret = "${name}-build-source-read";
    };
  })
  site
