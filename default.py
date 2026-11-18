"""Deterministic local installer invoked through Kodi's native JSON-RPC API."""

import json
import os
import sys
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

DUSKMATE_ANDROID_PACKAGE = "com.duskmate.tv"
DUSKMATE_RETURN_URI = "expansionkit://open"
DUSKMATE_LAUNCHER_PACKAGE = "com.duskmate.launcher"
KODI_ANDROID_PACKAGE = "org.xbmc.kodi"


def return_to_duskmate():
    """Return to the existing Duskmate task through its exported TV deep link.

    Some Google TV builds do not resolve a package-only StartAndroidActivity call to a
    Leanback activity consistently.  The explicit VIEW URI is handled by MainActivity and,
    with no title id, deliberately preserves whichever Duskmate screen was already open.
    """
    xbmc.executebuiltin(
        "StartAndroidActivity({},android.intent.action.VIEW,,{})".format(
            DUSKMATE_ANDROID_PACKAGE,
            DUSKMATE_RETURN_URI,
        )
    )


def return_to_package(package):
    if package == DUSKMATE_ANDROID_PACKAGE:
        return_to_duskmate()
    else:
        xbmc.executebuiltin("StartAndroidActivity({})".format(package))


ADDONS = (
    ("skin.duskmate", "0.3.5"),
    ("plugin.video.duskmate", "6.21.5.31"),
    ("service.duskmate.upnext", "1.4.1.1"),
)
EMBEDDED_DEPENDENCIES = (
    ("script.module.duskmate.infotagger", "0.1.0.2"),
    ("script.module.duskmate.common", "0.2.39.2"),
)
OFFICIAL_DEPENDENCIES = (
    ("script.module.requests", "2.9.1"),
    ("script.module.pil", "1.1.7"),
    ("script.module.addon.signals", "0.0.6"),
    ("script.module.qrcode", "6.1.0"),
)
TRAKT_ADDON = ("script.module.duskmate.sync.trakt", "1.2.9.11")
MARKER = xbmcvfs.translatePath(
    "special://profile/addon_data/script.duskmate.installer/bootstrap-1.0.2.done"
)
RUNNING_PROPERTY = "Duskmate.InstallerRunning.1.0.2"
def installed(addon_id):
    return xbmc.getCondVisibility("System.HasAddon({})".format(addon_id))


def json_rpc(method, params):
    """Run a Kodi JSON-RPC mutation and accept only an explicit successful result."""
    response = json.loads(xbmc.executeJSONRPC(json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    })))
    return "error" not in response and response.get("result") is not None


def enable_addon(addon_id):
    # EnableAddon is not a supported built-in on all Kodi 21/22 builds. The JSON-RPC method is
    # stable, reports failure, and avoids treating an extracted-but-disabled package as ready.
    return json_rpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": True})


def installed_version(addon_id):
    addon_xml = xbmcvfs.translatePath(
        "special://home/addons/{}/addon.xml".format(addon_id)
    )
    try:
        # Both System.HasAddon and xbmcaddon.Addon can reject a disabled add-on. Its local
        # manifest remains authoritative and lets migrations identify the installed version.
        metadata = ET.parse(addon_xml).getroot()
        if metadata.attrib.get("id") == addon_id:
            return metadata.attrib.get("version", "")
    except (ET.ParseError, OSError):
        pass
    try:
        return xbmcaddon.Addon(addon_id).getAddonInfo("version")
    except RuntimeError:
        return ""


def ready(addon_id, expected_version):
    # A freshly extracted add-on can already have a readable addon.xml while Kodi has not
    # registered or enabled it yet. Treating that state as ready lets the bootstrapper race
    # ahead and leaves the helper and its renamed dependencies disabled on a clean install.
    return installed_version(addon_id) == expected_version and installed(addon_id)


def wait_for(addon_id, expected_version, monitor, seconds=180):
    for _ in range(seconds * 2):
        if ready(addon_id, expected_version):
            return True
        if monitor.waitForAbort(0.5):
            return False
    return False


def foreground_kodi(monitor):
    """Bring Kodi forward only for a native confirmation owned by Kodi."""
    xbmc.executebuiltin("StartAndroidActivity({})".format(KODI_ANDROID_PACKAGE))
    return not monitor.waitForAbort(0.75)


def approve_native_confirmation(monitor):
    """Approve the exact Kodi confirmation and wait until it has closed."""
    for _ in range(40):
        if not xbmc.getCondVisibility("Window.IsActive(yesnodialog)"):
            return True
        if monitor.waitForAbort(0.05):
            return False
    xbmc.log(
        "Duskmate installer: native confirmation did not close after approval",
        xbmc.LOGERROR,
    )
    return False


def install(addon_id, expected_version, monitor):
    current = installed_version(addon_id) or "not installed"
    xbmc.log(
        "Duskmate installer: installing/updating {} from {} to {}".format(
            addon_id, current, expected_version
        ),
        xbmc.LOGINFO,
    )
    xbmc.executebuiltin("UpdateAddonRepos")
    monitor.waitForAbort(1)
    if not foreground_kodi(monitor):
        return False
    xbmc.executebuiltin("InstallAddon({})".format(addon_id))
    refresh_tick = 0
    for _ in range(720):
        if xbmc.getCondVisibility("Window.IsActive(yesnodialog)"):
            xbmc.executebuiltin("SendClick(10100,11)")
            if not approve_native_confirmation(monitor):
                return False
        # Refresh Kodi's add-on registry once per second rather than flooding it four times
        # per second while a package is being downloaded or unpacked.
        if refresh_tick % 4 == 0:
            xbmc.executebuiltin("UpdateLocalAddons")
            if installed_version(addon_id):
                enable_addon(addon_id)
        refresh_tick += 1
        if ready(addon_id, expected_version):
            return True
        if monitor.waitForAbort(0.25):
            return False
    if not handed_back:
        return_to_package(return_package)
    return False


def ensure_official_dependency(addon_id, minimum_version, monitor, seconds=90):
    """Install only dependencies distributed by Kodi's official repository."""
    if installed_version(addon_id):
        return True
    xbmc.log(
        "Duskmate installer: requesting official dependency {} >= {}".format(
            addon_id, minimum_version
        ),
        xbmc.LOGINFO,
    )
    if not foreground_kodi(monitor):
        return False
    xbmc.executebuiltin("InstallAddon({})".format(addon_id))
    for _ in range(seconds * 4):
        if installed_version(addon_id):
            return True
        # InstallAddon opens Kodi's native confirmation dialog on a clean profile. The viewer
        # already approved this exact dependency through Duskmate's package-specific Install
        # action. Confirm only DialogConfirm's affirmative control; never send a generic Select
        # to whichever Kodi window happens to be visible.
        if xbmc.getCondVisibility("Window.IsActive(yesnodialog)"):
            xbmc.executebuiltin("SendClick(10100,11)")
            if not approve_native_confirmation(monitor):
                return False
        if monitor.waitForAbort(0.25):
            return False
    if not handed_back:
        return_to_package(return_package)
    return False


def activate_skin(monitor):
    """Activate only the pinned Duskmate skin and accept only Kodi's exact confirm dialog."""
    if xbmc.getSkinDir() == "skin.duskmate":
        return True
    # A freshly extracted skin can already be visible on disk while Kodi's add-on database is
    # still replacing its old snapshot. The first enable request then reports "Unknown addon"
    # even though UpdateLocalAddons registers it moments later. Retry this bounded, idempotent
    # registration step instead of aborting the whole approved deployment on that race.
    enabled = False
    for _ in range(120):
        xbmc.executebuiltin("UpdateLocalAddons")
        if enable_addon("skin.duskmate"):
            enabled = True
            break
        if monitor.waitForAbort(0.25):
            return False
    if not enabled:
        return False
    if not json_rpc("Settings.SetSettingValue", {
        "setting": "lookandfeel.skin",
        "value": "skin.duskmate",
    }):
        return False
    if not foreground_kodi(monitor):
        return False
    stable_polls = 0
    for _ in range(120):
        if xbmc.getCondVisibility("Window.IsActive(yesnodialog)"):
            # DialogConfirm control 11 is the affirmative button. SendClick targets that exact
            # window/control pair and cannot activate a different Kodi screen accidentally.
            xbmc.executebuiltin("SendClick(10100,11)")
            if not approve_native_confirmation(monitor):
                return False
            stable_polls = 0
        elif xbmc.getSkinDir() == "skin.duskmate":
            # Kodi can show a second "keep this skin?" dialog shortly after the new skin first
            # becomes visible. Do not report success during that transient window; require five
            # stable seconds with the intended skin active and no pending confirmation.
            stable_polls += 1
            if stable_polls >= 20:
                if not handed_back:
                    return_to_package(return_package)
                return True
        else:
            stable_polls = 0
        if monitor.waitForAbort(0.25):
            return False
    return False


def _deploy(
    include_skin=False,
    include_helper=True,
    include_upnext=False,
    include_trakt=False,
    skin_only=False,
    return_package=DUSKMATE_ANDROID_PACKAGE,
):
    monitor = xbmc.Monitor()
    # Kodi leaves the Install-from-ZIP file browser open after the repository
    # has been approved. That modal blocks InstallAddon built-ins even while
    # Kodi is in the background, so close only that dialog before deployment.
    xbmc.executebuiltin("Dialog.Close(filebrowser,true)")
    monitor.waitForAbort(0.5)
    xbmc.log("Duskmate installer: installing approved repository packages", xbmc.LOGINFO)

    if skin_only:
        include_skin = True
        include_helper = False
        include_upnext = False

    if include_helper:
        # Kodi's native confirmation window is considered active only while Kodi's Android
        # activity owns the foreground. The caller deliberately brings Kodi forward for this
        # short, security-sensitive phase. Returning to Duskmate before InstallAddon finishes
        # leaves a hidden dialog that cannot be targeted by Window.IsActive on Android TV.
        for addon_id, minimum_version in OFFICIAL_DEPENDENCIES:
            if not ensure_official_dependency(addon_id, minimum_version, monitor):
                xbmc.log(
                    "Duskmate installer: official dependency unavailable: {}".format(addon_id),
                    xbmc.LOGERROR,
                )
                return

    # Preserve the product setup order approved by the viewer: visual integration first,
    # then the core media helper, followed by independently selected enhancements.
    packages = ()
    if include_skin:
        packages += (ADDONS[0],)
    if include_helper:
        packages += EMBEDDED_DEPENDENCIES + (ADDONS[1],)
    if include_upnext:
        packages += (ADDONS[2],)
    if include_trakt:
        packages += (TRAKT_ADDON,)
    for addon_id, expected_version in packages:
        if monitor.abortRequested():
            return
        if not ready(addon_id, expected_version):
            if not install(addon_id, expected_version, monitor):
                xbmc.log("Duskmate installer: installation timed out for {}".format(addon_id), xbmc.LOGERROR)
                return
        if not wait_for(addon_id, expected_version, monitor):
            xbmc.log("Duskmate installer: installation timed out for {}".format(addon_id), xbmc.LOGERROR)
            return
        # Kodi can retain a dependency on disk but leave it disabled after replacing a renamed
        # module. Enable every approved package even when its pinned files were already present,
        # then refresh local add-on metadata before the helper is first invoked.
        enable_addon(addon_id)
        xbmc.executebuiltin("UpdateLocalAddons")
        monitor.waitForAbort(0.25)
        if addon_id == "skin.duskmate" and not activate_skin(monitor):
            xbmc.log("Duskmate installer: Duskmate skin activation failed", xbmc.LOGERROR)
            return

    return_to_package(return_package)
    monitor.waitForAbort(0.5)

    parent = os.path.dirname(MARKER)
    if not xbmcvfs.exists(parent):
        xbmcvfs.mkdirs(parent)
    marker = xbmcvfs.File(MARKER, "w")
    marker.write("complete\n")
    marker.close()
    xbmc.log(
        "Duskmate installer: approved deployment complete "
        "(helper={}, skin={}, upnext={}, trakt={})".format(
            include_helper, include_skin, include_upnext, include_trakt
        ),
        xbmc.LOGINFO,
    )


def deploy(
    force=False,
    include_skin=False,
    include_helper=True,
    include_upnext=False,
    include_trakt=False,
    skin_only=False,
    return_package=DUSKMATE_ANDROID_PACKAGE,
):
    if os.path.exists(MARKER) and not force:
        return

    window = xbmcgui.Window(10000)
    if window.getProperty(RUNNING_PROPERTY) == "true":
        return
    window.setProperty(RUNNING_PROPERTY, "true")
    try:
        _deploy(
            include_skin=include_skin,
            include_helper=include_helper,
            include_upnext=include_upnext,
            include_trakt=include_trakt,
            skin_only=skin_only,
            return_package=return_package,
        )
    finally:
        window.clearProperty(RUNNING_PROPERTY)
        # Kodi is the foreground app, so Android permits this hand-off even when Android would
        # reject a background activity launch made directly by Duskmate itself.
        return_to_package(return_package)


def arguments():
    """Accept Kodi's object-style key=value arguments and simple positional arguments."""
    values = {}
    positional = []
    for value in sys.argv[1:]:
        if "=" in value:
            key, item = value.split("=", 1)
            values[key.strip().lower()] = item.strip()
        else:
            positional.append(value.strip().lower())
    if positional and "action" not in values:
        values["action"] = positional[0]
    if len(positional) > 1 and "addonid" not in values:
        values["addonid"] = positional[1]
    return values


def enabled(values, key):
    return values.get(key, "").lower() in ("1", "true", "yes", "on")


if __name__ == "__main__":
    args = arguments()
    action = args.get("action", "install").lower()
    return_package = args.get("return_package", DUSKMATE_ANDROID_PACKAGE)
    if action == "return":
        return_to_package(return_package)
    elif action == "install":
        deploy(
            force=True,
            include_skin=enabled(args, "skin"),
            include_upnext=enabled(args, "upnext"),
            include_trakt=enabled(args, "trakt"),
            skin_only=enabled(args, "skin_only"),
            return_package=return_package,
        )
    else:
        xbmc.log("Duskmate installer: unsupported action {}".format(action), xbmc.LOGERROR)
