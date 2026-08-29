# brew-nix-extra

Reusable overlays and nix-darwin modules for Homebrew casks that need
package-specific normalization or lifecycle behavior beyond a normal
application bundle.

Add the flake input. Follow the consumer's existing inputs when they are
available so package metadata and generator revisions stay aligned:

```nix
inputs.brew-nix-extra = {
  url = "github:futuping/brew-nix-extra";
  inputs.brew-nix.follows = "brew-nix";
  inputs.brew-api-extra.follows = "brew-api-extra";
};
```

## Google Chrome

The official Homebrew cask intentionally publishes the mutable Stable DMG with
`sha256: no_check`. The Google Chrome overlay preserves brew-nix's official
cask metadata, app artifact, and installation logic while replacing only the
version and source with an automatically maintained fixed hash. It also
normalizes the extracted application's signature after brew-nix materializes
the APFS DMG in the Nix store.

Import the module once, then select Chrome like an ordinary cask:

```nix
modules = [
  inputs.brew-nix-extra.darwinModules.google-chrome
];

environment.systemPackages = with pkgs.brewCasks; [
  google-chrome
];
```

The scheduled updater cross-checks the official Homebrew cask and Google's
fully rolled-out Apple Silicon Stable release. When the DMG changes, a macOS
runner mounts it and verifies its Google Team ID, bundle ID, version, and
Developer ID signature before publishing the new SRI hash. HTTP validators
avoid downloading the unchanged DMG on routine checks.

## Lock consistency

The flake validates that every cask exported from the shared third-party
overlay exists in its own locked `brew-api-extra` catalog. This is a
compatibility check rather than a freshness check: an older catalog is valid
as long as it contains every required cask. Pushes and pull requests run the
standalone check without consumer input overrides:

```sh
nix flake check --no-build --no-update-lock-file
```

When adding another catalog-backed cask, add its token to
`overlays/brew-api-extra-cask-tokens.nix`; the shared overlay and lock check
both consume that registry.

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

## Shared third-party casks

When a configuration uses catalog-backed casks such as Motrix Next, import the
shared overlay once. It consumes the packages from `brew-api-extra`, preserves
Motrix's signature normalization, and exposes each package as an ordinary
brew-nix cask.

```nix
modules = [
  inputs.brew-nix-extra.darwinModules.third-party-casks
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
