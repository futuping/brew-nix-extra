{
  brew-api-extra,
  brew-nix,
}:

final: prev:

let
  brewApiExtraCaskTokens = import ./brew-api-extra-cask-tokens.nix;
  thirdPartyBrewCasks = import "${brew-nix}/casks.nix" {
    pkgs = final;
    brew-api = brew-api-extra.outPath;
  };
  catalogCasks = builtins.listToAttrs (
    builtins.map (token: {
      name = token;
      value = thirdPartyBrewCasks.${token};
    }) brewApiExtraCaskTokens
  );

  # The upstream app is not Developer ID signed. Normalize its linker-generated
  # ad-hoc signature into a valid signature for the complete application bundle.
  motrixNextPackage = catalogCasks."motrix-next".overrideAttrs (oldAttrs: {
    installPhase = oldAttrs.installPhase + ''
      /usr/bin/codesign --force --deep --sign - \
      "$out/Applications/MotrixNext.app"
    '';
  });
in
{
  brewCasks =
    (prev.brewCasks or { })
    // catalogCasks
    // {
      motrix-next = motrixNextPackage;
    };
}
