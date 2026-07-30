# brew-nix-extra

Reusable nix-darwin modules for Homebrew casks that need lifecycle behavior
beyond a normal application bundle.

## WeType

The WeType module keeps package metadata in the official Homebrew cask through
brew-nix, then deploys the input method to its required writable system
location at `/Library/Input Methods/WeType.app`.

Add the flake input:

```nix
inputs.brew-nix-extra.url = "github:futuping/brew-nix-extra";
```

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
