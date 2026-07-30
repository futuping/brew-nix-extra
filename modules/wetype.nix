{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.wetype;

  wetypePackage = pkgs.brewCasks.wetype.overrideAttrs (_: {
    unpackPhase = ''
      runHook preUnpack
      unzip -q "$src"
      runHook postUnpack
    '';

    installPhase = ''
      runHook preInstall

      mkdir -p "$out/Applications"
      cp -R WeType.app "$out/Applications/"
      chmod -R u+w "$out/Applications/WeType.app"

      # The upstream signature does not survive Nix store materialization.
      /usr/bin/codesign --force --deep --sign - \
        "$out/Applications/WeType.app"
      /usr/bin/codesign --verify --deep --strict \
        "$out/Applications/WeType.app"

      runHook postInstall
    '';

    # Keep the package-level signature valid after installation.
    dontFixup = true;
  });

  # WeType and its updater require this exact writable system location.
  inputMethodsDirectory = "/Library/Input Methods";
  wetypeSource = "${cfg.package}/Applications/WeType.app";
  wetypeTarget = "${inputMethodsDirectory}/WeType.app";
  wetypeMarker = "${inputMethodsDirectory}/.WeType.nix-store-path";
  wetypeDeploymentId = "official-cask-v1:${wetypeSource}";
in
{
  options.programs.wetype = {
    enable = lib.mkEnableOption "the WeType input method";

    package = lib.mkOption {
      type = lib.types.package;
      default = wetypePackage;
      description = "WeType application bundle to deploy as a system input method.";
    };
  };

  config = {
    system.activationScripts.postActivation.text = lib.mkAfter (
      if cfg.enable then
        ''
          (
            wetype_source=${lib.escapeShellArg wetypeSource}
            wetype_directory=${lib.escapeShellArg inputMethodsDirectory}
            wetype_target=${lib.escapeShellArg wetypeTarget}
            wetype_marker=${lib.escapeShellArg wetypeMarker}
            wetype_deployment_id=${lib.escapeShellArg wetypeDeploymentId}

            wetype_existing_deployment_id=""
            if [[ -r "$wetype_marker" ]]; then
              wetype_existing_deployment_id="$(/bin/cat "$wetype_marker")"
            fi

            if [[ -d "$wetype_target" ]] \
              && [[ "$wetype_existing_deployment_id" == "$wetype_deployment_id" ]] \
              && /usr/bin/codesign --verify --deep --strict "$wetype_target" >/dev/null 2>&1; then
              echo "WeType input method is already current." >&2
              exit 0
            fi

            if [[ -e "$wetype_target" || -L "$wetype_target" ]] \
              && [[ -z "$wetype_existing_deployment_id" ]]; then
              echo "error: refusing to replace unmanaged WeType input method: $wetype_target" >&2
              exit 1
            fi

            echo "installing WeType input method..." >&2

            if [[ -e "$wetype_directory" && ! -d "$wetype_directory" ]]; then
              echo "error: WeType input method directory is not a directory: $wetype_directory" >&2
              exit 1
            fi

            if [[ ! -d "$wetype_directory" ]]; then
              /bin/mkdir -p "$wetype_directory"
              /usr/sbin/chown root:wheel "$wetype_directory"
              /bin/chmod 0755 "$wetype_directory"
            fi

            wetype_stage="$(/usr/bin/mktemp -d "$wetype_directory/.WeType.nix-darwin.XXXXXX")"
            wetype_marker_temp=""
            # shellcheck disable=SC2329 # Invoked indirectly by the EXIT trap.
            cleanup_wetype() {
              [[ -z "$wetype_stage" ]] || /bin/rm -rf "$wetype_stage"
              [[ -z "$wetype_marker_temp" ]] || /bin/rm -f "$wetype_marker_temp"
            }
            trap cleanup_wetype EXIT

            /usr/bin/ditto "$wetype_source" "$wetype_stage/WeType.app"
            /usr/sbin/chown -R root:staff "$wetype_stage/WeType.app"
            /bin/chmod -R u+rwX,g+rwX,o+rX "$wetype_stage/WeType.app"
            /usr/bin/codesign --verify --deep --strict "$wetype_stage/WeType.app"

            /usr/bin/killall WeType >/dev/null 2>&1 || true
            if [[ -e "$wetype_target" || -L "$wetype_target" ]]; then
              /bin/rm -rf "$wetype_target"
            fi
            /bin/mv "$wetype_stage/WeType.app" "$wetype_target"
            /usr/bin/codesign --verify --deep --strict "$wetype_target"
            /bin/rmdir "$wetype_stage"
            wetype_stage=""

            wetype_marker_temp="$(/usr/bin/mktemp "$wetype_directory/.WeType.nix-store-path.XXXXXX")"
            printf '%s\n' "$wetype_deployment_id" >"$wetype_marker_temp"
            /usr/sbin/chown root:wheel "$wetype_marker_temp"
            /bin/chmod 0644 "$wetype_marker_temp"
            /bin/mv -f "$wetype_marker_temp" "$wetype_marker"
            wetype_marker_temp=""

            echo "installed WeType input method at $wetype_target; add it once in System Settings." >&2
          )
        ''
      else
        ''
          (
            wetype_target=${lib.escapeShellArg wetypeTarget}
            wetype_marker=${lib.escapeShellArg wetypeMarker}

            if [[ -r "$wetype_marker" ]]; then
              [[ ! -e "$wetype_target" && ! -L "$wetype_target" ]] \
                || /bin/rm -rf "$wetype_target"
              /bin/rm -f "$wetype_marker"
              echo "removed Nix-managed WeType input method from $wetype_target" >&2
            elif [[ -e "$wetype_target" || -L "$wetype_target" ]]; then
              echo "leaving unmanaged WeType input method at $wetype_target" >&2
            else
              echo "WeType input method is disabled." >&2
            fi
          )
        ''
    );
  };
}
