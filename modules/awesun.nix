{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.awesun;
  source = cfg.package.src;
  version = cfg.package.version;

  target = "/Applications/AweSun.app";
  agent = "/Library/LaunchAgents/com.oray.awesun.agent.plist";
  startup = "/Library/LaunchAgents/com.oray.awesun.startup.plist";
  helper = "/Library/LaunchDaemons/com.oray.awesun.helper.plist";
  service = "/Library/LaunchDaemons/com.oray.awesun.plist";
  audioDriver = "/Library/Audio/Plug-Ins/HAL/OrayVirtualAudioDevice.driver";
  markerDirectory = "/Library/Application Support/Nix-Darwin/AweSun";
  marker = "${markerDirectory}/deployment";
  deploymentId = "official-cask-v1:${version}:${toString source}";
in
{
  options.programs.awesun = {
    enable = lib.mkEnableOption "AweSun remote control with its privileged macOS services";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.brewCasks.awesun;
      description = "Official AweSun cask whose signed installer is deployed during activation.";
    };
  };

  config.system.activationScripts.postActivation.text = lib.mkAfter (
    if cfg.enable then
      ''
        (
        awesun_source=${lib.escapeShellArg (toString source)}
        awesun_version=${lib.escapeShellArg version}
        awesun_target=${lib.escapeShellArg target}
        awesun_agent=${lib.escapeShellArg agent}
        awesun_startup=${lib.escapeShellArg startup}
        awesun_helper=${lib.escapeShellArg helper}
        awesun_service=${lib.escapeShellArg service}
        awesun_audio_driver=${lib.escapeShellArg audioDriver}
        awesun_marker_directory=${lib.escapeShellArg markerDirectory}
        awesun_marker=${lib.escapeShellArg marker}
        awesun_deployment_id=${lib.escapeShellArg deploymentId}

        awesun_existing_deployment_id=""
        if [[ -r "$awesun_marker" ]]; then
          awesun_existing_deployment_id="$(/bin/cat "$awesun_marker")"
        fi

        awesun_receipt_version="$(
          /usr/sbin/pkgutil --pkg-info com.oray.sunlogin.macclient 2>/dev/null \
            | /usr/bin/awk -F': ' '$1 == "version" { print $2 }' || true
        )"
        awesun_bundle_short_version=""
        awesun_bundle_build=""
        awesun_team_id=""
        if [[ -d "$awesun_target" ]]; then
          awesun_bundle_short_version="$(
            /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
              "$awesun_target/Contents/Info.plist" 2>/dev/null || true
          )"
          awesun_bundle_build="$(
            /usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' \
              "$awesun_target/Contents/Info.plist" 2>/dev/null || true
          )"
          awesun_team_id="$(
            /usr/bin/codesign -dv --verbose=4 "$awesun_target" 2>&1 \
              | /usr/bin/sed -n 's/^TeamIdentifier=//p' || true
          )"
        fi

        awesun_current=1
        [[ "$awesun_existing_deployment_id" == "$awesun_deployment_id" ]] || awesun_current=0
        [[ "$awesun_receipt_version" == "$awesun_version" ]] || awesun_current=0
        [[ "$awesun_bundle_short_version.$awesun_bundle_build" == "$awesun_version" ]] \
          || awesun_current=0
        [[ "$awesun_team_id" == "ZBNMDRTU32" ]] || awesun_current=0
        for awesun_path in \
          "$awesun_target" \
          "$awesun_agent" \
          "$awesun_startup" \
          "$awesun_helper" \
          "$awesun_service" \
          "$awesun_audio_driver"
        do
          [[ -e "$awesun_path" || -L "$awesun_path" ]] || awesun_current=0
        done
        /usr/sbin/pkgutil --pkg-info com.oray.sunlogin.MacVirtualAudioDevice \
          >/dev/null 2>&1 || awesun_current=0

        if [[ "$awesun_current" -eq 1 ]]; then
          echo "AweSun $awesun_version is already current." >&2
          exit 0
        fi

        if [[ -z "$awesun_existing_deployment_id" ]]; then
          for awesun_path in \
            "$awesun_target" \
            "$awesun_agent" \
            "$awesun_startup" \
            "$awesun_helper" \
            "$awesun_service" \
            "$awesun_audio_driver"
          do
            if [[ -e "$awesun_path" || -L "$awesun_path" ]]; then
              echo "error: refusing to replace unmanaged AweSun artifact: $awesun_path" >&2
              exit 1
            fi
          done

          for awesun_receipt in \
            com.oray.sunlogin.macclient \
            com.oray.awesun.macclient \
            com.oray.sunlogin.MacVirtualAudioDevice
          do
            if /usr/sbin/pkgutil --pkg-info "$awesun_receipt" >/dev/null 2>&1; then
              echo "error: refusing to replace unmanaged AweSun package receipt: $awesun_receipt" >&2
              exit 1
            fi
          done
        fi

        echo "installing AweSun $awesun_version and its macOS services..." >&2

        awesun_mount="$(/usr/bin/mktemp -d /private/tmp/awesun-nix-darwin.XXXXXX)"
        awesun_signature="$(/usr/bin/mktemp /private/tmp/awesun-signature.XXXXXX)"
        awesun_marker_temp=""
        awesun_mounted=0

        # shellcheck disable=SC2329 # Invoked indirectly by the EXIT trap.
        cleanup_awesun() {
          if [[ "$awesun_mounted" -eq 1 ]]; then
            /usr/bin/hdiutil detach "$awesun_mount" >/dev/null 2>&1 || true
          fi
          [[ -z "$awesun_signature" ]] || /bin/rm -f "$awesun_signature"
          [[ -z "$awesun_marker_temp" ]] || /bin/rm -f "$awesun_marker_temp"
          /bin/rmdir "$awesun_mount" >/dev/null 2>&1 || true
        }
        trap cleanup_awesun EXIT

        /usr/bin/hdiutil attach \
          -readonly \
          -nobrowse \
          -mountpoint "$awesun_mount" \
          "$awesun_source" >/dev/null
        awesun_mounted=1

        awesun_installer="$awesun_mount/AweSun.pkg"
        if [[ ! -f "$awesun_installer" ]]; then
          echo "error: AweSun.pkg is missing from the official disk image" >&2
          exit 1
        fi

        if ! /usr/sbin/pkgutil --check-signature "$awesun_installer" \
          >"$awesun_signature" 2>&1; then
          /bin/cat "$awesun_signature" >&2
          echo "error: AweSun installer signature verification failed" >&2
          exit 1
        fi
        if ! /usr/bin/grep -Fq '(ZBNMDRTU32)' "$awesun_signature"; then
          /bin/cat "$awesun_signature" >&2
          echo "error: AweSun installer is not signed by the expected developer" >&2
          exit 1
        fi
        if ! /usr/sbin/spctl --assess --type install "$awesun_installer"; then
          echo "error: Gatekeeper rejected the AweSun installer" >&2
          exit 1
        fi

        /usr/sbin/installer -pkg "$awesun_installer" -target /
        /usr/bin/killall AweSun >/dev/null 2>&1 || true

        /usr/bin/hdiutil detach "$awesun_mount" >/dev/null
        awesun_mounted=0

        for awesun_path in \
          "$awesun_target" \
          "$awesun_agent" \
          "$awesun_startup" \
          "$awesun_helper" \
          "$awesun_service" \
          "$awesun_audio_driver"
        do
          if [[ ! -e "$awesun_path" && ! -L "$awesun_path" ]]; then
            echo "error: AweSun installer did not create expected artifact: $awesun_path" >&2
            exit 1
          fi
        done
        if ! /usr/sbin/pkgutil --pkg-info com.oray.sunlogin.MacVirtualAudioDevice \
          >/dev/null 2>&1; then
          echo "error: AweSun virtual audio package receipt is missing" >&2
          exit 1
        fi

        awesun_receipt_version="$(
          /usr/sbin/pkgutil --pkg-info com.oray.sunlogin.macclient 2>/dev/null \
            | /usr/bin/awk -F': ' '$1 == "version" { print $2 }' || true
        )"
        awesun_bundle_short_version="$(
          /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
            "$awesun_target/Contents/Info.plist"
        )"
        awesun_bundle_build="$(
          /usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' \
            "$awesun_target/Contents/Info.plist"
        )"
        awesun_team_id="$(
          /usr/bin/codesign -dv --verbose=4 "$awesun_target" 2>&1 \
            | /usr/bin/sed -n 's/^TeamIdentifier=//p' || true
        )"

        if [[ "$awesun_receipt_version" != "$awesun_version" ]] \
          || [[ "$awesun_bundle_short_version.$awesun_bundle_build" != "$awesun_version" ]] \
          || [[ "$awesun_team_id" != "ZBNMDRTU32" ]]; then
          echo "error: installed AweSun identity or version validation failed" >&2
          exit 1
        fi

        if [[ ! -d "$awesun_marker_directory" ]]; then
          /bin/mkdir -p "$awesun_marker_directory"
          /usr/sbin/chown root:wheel "$awesun_marker_directory"
          /bin/chmod 0755 "$awesun_marker_directory"
        fi
        awesun_marker_temp="$(
          /usr/bin/mktemp "$awesun_marker_directory/.deployment.XXXXXX"
        )"
        printf '%s\n' "$awesun_deployment_id" >"$awesun_marker_temp"
        /usr/sbin/chown root:wheel "$awesun_marker_temp"
        /bin/chmod 0644 "$awesun_marker_temp"
        /bin/mv -f "$awesun_marker_temp" "$awesun_marker"
        awesun_marker_temp=""

        echo "installed AweSun $awesun_version at $awesun_target" >&2
        )
      ''
    else
      ''
        (
          awesun_target=${lib.escapeShellArg target}
          awesun_agent=${lib.escapeShellArg agent}
          awesun_startup=${lib.escapeShellArg startup}
          awesun_helper=${lib.escapeShellArg helper}
          awesun_service=${lib.escapeShellArg service}
          awesun_audio_driver=${lib.escapeShellArg audioDriver}
          awesun_marker_directory=${lib.escapeShellArg markerDirectory}
          awesun_marker=${lib.escapeShellArg marker}

          if [[ -r "$awesun_marker" ]]; then
            awesun_console_uid="$(/usr/bin/stat -f '%u' /dev/console 2>/dev/null || true)"
            if [[ -n "$awesun_console_uid" && "$awesun_console_uid" != "0" ]]; then
              /bin/launchctl bootout \
                "gui/$awesun_console_uid/com.oray.awesun.desktopagent" \
                >/dev/null 2>&1 || true
              /bin/launchctl bootout \
                "gui/$awesun_console_uid/com.oray.awesun.client.startup" \
                >/dev/null 2>&1 || true
            fi
            /bin/launchctl bootout system/com.oray.awesun.helper \
              >/dev/null 2>&1 || true
            /bin/launchctl bootout system/com.oray.awesun.service \
              >/dev/null 2>&1 || true

            /usr/bin/killall AweSun >/dev/null 2>&1 || true
            /usr/bin/killall AweSun_Desktop >/dev/null 2>&1 || true
            /usr/bin/killall AweSun_Helper >/dev/null 2>&1 || true

            /bin/rm -rf "$awesun_target" "$awesun_audio_driver"
            /bin/rm -f \
              "$awesun_agent" \
              "$awesun_startup" \
              "$awesun_helper" \
              "$awesun_service"

            for awesun_receipt in \
              com.oray.sunlogin.macclient \
              com.oray.awesun.macclient \
              com.oray.sunlogin.MacVirtualAudioDevice
            do
              /usr/sbin/pkgutil --forget "$awesun_receipt" >/dev/null 2>&1 || true
            done

            /bin/rm -f "$awesun_marker"
            /bin/rmdir "$awesun_marker_directory" >/dev/null 2>&1 || true
            echo "removed Nix-managed AweSun; application data and logs were preserved." >&2
          else
            awesun_unmanaged=0
            for awesun_path in \
              "$awesun_target" \
              "$awesun_agent" \
              "$awesun_startup" \
              "$awesun_helper" \
              "$awesun_service" \
              "$awesun_audio_driver"
            do
              if [[ -e "$awesun_path" || -L "$awesun_path" ]]; then
                awesun_unmanaged=1
              fi
            done
            for awesun_receipt in \
              com.oray.sunlogin.macclient \
              com.oray.awesun.macclient \
              com.oray.sunlogin.MacVirtualAudioDevice
            do
              if /usr/sbin/pkgutil --pkg-info "$awesun_receipt" >/dev/null 2>&1; then
                awesun_unmanaged=1
              fi
            done

            if [[ "$awesun_unmanaged" -eq 1 ]]; then
              echo "leaving unmanaged AweSun installation unchanged." >&2
            else
              echo "AweSun is disabled." >&2
            fi
          fi
        )
      ''
  );
}
