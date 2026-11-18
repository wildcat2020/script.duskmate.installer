# Duskmate Installer for Kodi

`script.duskmate.installer` is the small executable bridge used by the Duskmate setup wizard.
It is invoked through Kodi's native JSON-RPC `Addons.ExecuteAddon` method and asks Kodi to install
only the components explicitly selected by the viewer from `repository.duskmate`.

It also exposes an explicit `uninstall` action for the product's uninstall/recovery flow. That
action removes only the fixed list of Duskmate-owned Kodi packages and their settings. It leaves
Kodi libraries, sources, artwork caches, generated media and unrelated add-ons untouched.

The repository add-on itself remains repository-only. This installer does not contain player
definitions, streaming-provider add-ons, credentials or Duskmate application source code.

Licensed under Apache-2.0.
