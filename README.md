# brew-nix-extra

Reusable nix-darwin modules for Homebrew casks that need package-specific
normalization or lifecycle behavior beyond a normal application bundle.

Add the flake input. Follow the consumer's existing inputs when they are
available so package metadata and generator revisions stay aligned:

```nix
inputs.brew-nix-extra = {
  url = "github:futuping/brew-nix-extra";
  inputs.brew-nix.follows = "brew-nix";
  inputs.brew-api-extra.follows = "brew-api-extra";
};
```

## Motrix Next

The Motrix Next overlay consumes its metadata from `brew-api-extra`, normalizes
the upstream ad-hoc signature for the complete application bundle, and exposes
the result as `pkgs.brewCasks.motrix-next`.

Import the module once to append the overlay, then manage Motrix Next in the
ordinary system package list:

```nix
modules = [
  inputs.brew-nix-extra.darwinModules.motrix-next
];

environment.systemPackages = with pkgs.brewCasks; [
  motrix-next
];
```

## WeType

The WeType module keeps package metadata in the official Homebrew cask through
brew-nix, then deploys the input method to its required writable system
location at `/Library/Input Methods/WeType.app`.

Import brew-nix before the WeType module:

```nix
modules = [
  inputs.brew-nix.darwinModules.default
  inputs.brew-nix-extra.darwinModules.wetype
];
```

Then enable the input method:

```nix
programs.wetype.enable = true;
```

The module expects `brew-nix.enable = true;` so that
`pkgs.brewCasks.wetype` is available. It installs, upgrades, and removes only
the WeType copy tracked by its ownership marker. After the first installation,
add WeType once in System Settings.
