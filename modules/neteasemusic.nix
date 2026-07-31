{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.neteasemusic;

  # The official cask requires Homebrew's `user_agent: :fake` URL setting.
  # brew-nix currently does not forward url_specs to fetchurl.
  neteasemusicDmg = pkgs.brewCasks.neteasemusic.src.overrideAttrs (oldAttrs: {
    curlOptsList = (oldAttrs.curlOptsList or [ ]) ++ [
      "--user-agent"
      "Mozilla/5.0 (Macintosh; Apple Silicon Mac OS X 15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ];
  });

  applicationsDirectory = "/Applications";
  appName = "NeteaseMusic.app";
  appSource = cfg.package;
  appTarget = "${applicationsDirectory}/${appName}";
  marker = "${applicationsDirectory}/.NeteaseMusic.nix-store-path";
  deploymentId = "official-cask-v1:${appSource}";
in
{
  options.programs.neteasemusic = {
    enable = lib.mkEnableOption "NetEase Cloud Music";

    package = lib.mkOption {
      type = lib.types.package;
      default = neteasemusicDmg;
      description = "Verified NetEase Cloud Music DMG source to deploy.";
    };
  };

  config = {
    system.activationScripts.postActivation.text = lib.mkAfter (
      if cfg.enable then
        ''
          (
            app_source=${lib.escapeShellArg (toString appSource)}
            app_directory=${lib.escapeShellArg applicationsDirectory}
            app_target=${lib.escapeShellArg appTarget}
            app_marker=${lib.escapeShellArg marker}
            deployment_id=${lib.escapeShellArg deploymentId}

            existing_deployment_id=""
            if [[ -r "$app_marker" ]]; then
              existing_deployment_id="$(/bin/cat "$app_marker")"
            fi

            if [[ -d "$app_target" ]] \
              && [[ "$existing_deployment_id" == "$deployment_id" ]] \
              && /usr/bin/codesign --verify --deep --strict "$app_target" >/dev/null 2>&1; then
              echo "NetEase Cloud Music is already current." >&2
              exit 0
            fi

            if [[ -e "$app_target" || -L "$app_target" ]] \
              && [[ -z "$existing_deployment_id" ]]; then
              echo "error: refusing to replace unmanaged NetEase Cloud Music: $app_target" >&2
              exit 1
            fi

            stage="$(/usr/bin/mktemp -d "$app_directory/.NeteaseMusic.nix-darwin.XXXXXX")"
            mountpoint="$stage/mount"
            backup="$stage/previous.app"
            mounted=0
            replacement_started=0
            completed=0
            marker_temp=""

            # shellcheck disable=SC2329 # Invoked indirectly by the EXIT trap.
            cleanup_neteasemusic() {
              if [[ "$mounted" == 1 ]]; then
                /usr/bin/hdiutil detach "$mountpoint" -quiet || true
              fi
              if [[ "$completed" != 1 ]]; then
                if [[ "$replacement_started" == 1 && ( -e "$app_target" || -L "$app_target" ) ]]; then
                  /bin/rm -rf "$app_target"
                fi
                if [[ -e "$backup" || -L "$backup" ]]; then
                  /bin/mv "$backup" "$app_target" || true
                fi
              fi
              [[ -z "$marker_temp" ]] || /bin/rm -f "$marker_temp"
              /bin/rm -rf "$stage"
            }
            trap cleanup_neteasemusic EXIT

            /bin/mkdir "$mountpoint"
            /usr/bin/hdiutil attach -nobrowse -noverify -readonly \
              -mountpoint "$mountpoint" "$app_source" >/dev/null
            mounted=1
            /usr/bin/ditto "$mountpoint/${appName}" "$stage/${appName}"
            /usr/sbin/chown -R root:wheel "$stage/${appName}"
            /usr/bin/codesign --verify --deep --strict "$stage/${appName}"

            if [[ -e "$app_target" || -L "$app_target" ]]; then
              /bin/mv "$app_target" "$backup"
            fi
            /bin/mv "$stage/${appName}" "$app_target"
            replacement_started=1
            /usr/bin/codesign --verify --deep --strict "$app_target"

            marker_temp="$(/usr/bin/mktemp "$app_directory/.NeteaseMusic.nix-store-path.XXXXXX")"
            printf '%s\n' "$deployment_id" >"$marker_temp"
            /usr/sbin/chown root:wheel "$marker_temp"
            /bin/chmod 0644 "$marker_temp"
            /bin/mv -f "$marker_temp" "$app_marker"
            marker_temp=""
            completed=1
            [[ ! -e "$backup" && ! -L "$backup" ]] || /bin/rm -rf "$backup"

            echo "installed NetEase Cloud Music at $app_target" >&2
          )
        ''
      else
        ''
          (
            app_target=${lib.escapeShellArg appTarget}
            app_marker=${lib.escapeShellArg marker}

            if [[ -r "$app_marker" ]]; then
              [[ ! -e "$app_target" && ! -L "$app_target" ]] \
                || /bin/rm -rf "$app_target"
              /bin/rm -f "$app_marker"
              echo "removed Nix-managed NetEase Cloud Music from $app_target" >&2
            elif [[ -e "$app_target" || -L "$app_target" ]]; then
              echo "leaving unmanaged NetEase Cloud Music at $app_target" >&2
            else
              echo "NetEase Cloud Music is disabled." >&2
            fi
          )
        ''
    );
  };
}
