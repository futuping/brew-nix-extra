final: prev:

let
  neteasemusicPackage = prev.brewCasks.neteasemusic.overrideAttrs (oldAttrs: {
    # The official cask sets Homebrew's `user_agent: :fake` URL option.  brew-nix
    # does not currently pass cask URL options to fetchurl, so supply its browser
    # user agent here.
    src = oldAttrs.src.overrideAttrs (oldSrcAttrs: {
      curlOptsList = (oldSrcAttrs.curlOptsList or [ ]) ++ [
        "--user-agent"
        "Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X 15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
      ];
    });

    # 7zz reports an error after extracting this APFS DMG, although the complete
    # app bundle is already present.  Keep that recovery narrowly scoped and
    # still fail if the expected bundle was not extracted.
    unpackPhase = ''
      cp -- "$src" ./archive
      if ! undmg ./archive 2>/dev/null; then
        if ! 7zz x -snld20 ./archive; then
          if [ -z "$(find . -type d -name "NeteaseMusic.app" -print -quit)" ]; then
            exit 1
          fi
        fi
        find . -name '*:com.apple.*' -print -delete
      fi
      rm -f ./archive
      if [ ! -e "NeteaseMusic.app" ]; then
        nested=$(find . -mindepth 2 -maxdepth 3 -name "NeteaseMusic.app" -print -quit)
        [ -n "$nested" ] && mv "$nested" .
      fi
      find . -maxdepth 1 -type l -delete
    '';

    # Copying the bundle into the Nix store invalidates its Developer ID
    # signature.  Sign the final immutable bundle ad-hoc and preserve it.
    installPhase = oldAttrs.installPhase + ''
      /usr/bin/codesign --force --deep --sign - \
        "$out/Applications/NeteaseMusic.app"
      /usr/bin/codesign --verify --deep --strict \
        "$out/Applications/NeteaseMusic.app"
    '';

    dontFixup = true;
  });
in
{
  brewCasks = (prev.brewCasks or { }) // {
    neteasemusic = neteasemusicPackage;
  };
}
