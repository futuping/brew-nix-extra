final: prev:

let
  source = builtins.fromJSON (builtins.readFile ../sources/google-chrome.json);

  googleChromePackage = prev.brewCasks.google-chrome.overrideAttrs (oldAttrs: {
    inherit (source) version;

    src = final.fetchurl {
      inherit (source) url hash;
    };

    # brew-nix keeps the official cask's app artifact and installation logic.
    # Its APFS DMG extraction does not preserve Chrome's nested signatures, so
    # normalize the complete bundle after it reaches the Nix output.
    installPhase = oldAttrs.installPhase + ''
      /usr/bin/codesign --force --deep --sign - \
        "$out/Applications/Google Chrome.app"
      /usr/bin/codesign --verify --deep --strict \
        "$out/Applications/Google Chrome.app"
    '';

    dontFixup = true;
  });
in
{
  brewCasks = (prev.brewCasks or { }) // {
    google-chrome = googleChromePackage;
  };
}
