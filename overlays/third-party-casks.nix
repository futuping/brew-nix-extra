{
  brew-api-extra,
  brew-nix,
}:

final: prev:

let
  thirdPartyBrewCasks = import "${brew-nix}/casks.nix" {
    pkgs = final;
    brew-api = brew-api-extra.outPath;
  };

  # The upstream app is not Developer ID signed. Normalize its linker-generated
  # ad-hoc signature into a valid signature for the complete application bundle.
  motrixNextPackage = thirdPartyBrewCasks."motrix-next".overrideAttrs (oldAttrs: {
    installPhase = oldAttrs.installPhase + ''
      /usr/bin/codesign --force --deep --sign - \
      "$out/Applications/MotrixNext.app"
    '';
  });
in
{
  brewCasks = (prev.brewCasks or { }) // {
    motrix-next = motrixNextPackage;
    tinycast = thirdPartyBrewCasks.tinycast;
  };
}
