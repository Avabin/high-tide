# main.py
#
# Copyright 2023 Nokse
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import threading
import webbrowser
from gettext import gettext as _
from pathlib import Path
from typing import Any, Callable, List

from gi.repository import Adw, Gio, GLib, Gtk

from .lib import lastfm_scrobbler, utils
from .lib.player_object import AudioSink
from .lib.secret_storage import get_default_auth_file_path
from .window import HighTideWindow


class HighTideApplication(Adw.Application):
    """The main application singleton class.

    This class handles the main application lifecycle, manages global actions,
    preferences, and provides the entry point for the High Tide TIDAL music player.
    """

    def __init__(self) -> None:
        super().__init__(
            application_id="io.github.nokse22.high-tide",
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.create_action("quit", lambda *_: self.quit(), ["<primary>q", "<primary>w"])
        self.create_action("about", self.on_about_action)
        self.create_action(
            "preferences", self.on_preferences_action, ["<primary>comma"]
        )
        self.create_action("log-in", self.on_login_action)
        self.create_action("log-out", self.on_logout_action)

        utils.init()
        utils.setup_logging()

        self.settings: Gio.Settings = Gio.Settings.new("io.github.nokse22.high-tide")

        self.preferences: Gtk.Window | None = None

        self.alsa_devices = utils.get_alsa_devices()

        # Initialize Last.fm scrobbler with saved settings
        self._lastfm_auth_token = None
        self._init_lastfm_scrobbler()

    def _init_lastfm_scrobbler(self) -> None:
        """Initialize the Last.fm scrobbler with saved settings."""
        scrobbler = lastfm_scrobbler.scrobbler
        scrobbler.enabled = self.settings.get_boolean("lastfm-enabled")
        scrobbler.scrobble_threshold = self.settings.get_int(
            "lastfm-scrobble-percentage"
        )

        session_key = self.settings.get_string("lastfm-session-key")
        if session_key:
            scrobbler.set_session_key(session_key)

    def do_open(self, files: List[Gio.File], n_files: int, hint: str) -> None:
        self.win: HighTideWindow | None = self.props.active_window
        if not self.win:
            self.do_activate()

        uri: str = files[0].get_uri()
        if uri:
            if self.win.is_logged_in:
                utils.open_tidal_uri(uri)
            else:
                self.win.queued_uri = uri

    def on_login_action(self, *args) -> None:
        """Handle the login action by initiating a new login process."""
        self.win.new_login()

    def on_logout_action(self, *args) -> None:
        """Handle the logout action by logging out the current user."""
        self.win.logout()

    def do_activate(self) -> None:
        """Activate the application by creating and presenting the main window."""
        self.win: HighTideWindow | None = self.props.active_window
        if not self.win:
            self.win = HighTideWindow(application=self)

        self.win.present()

    def on_about_action(self, widget: Any, *args) -> None:
        """Display the about dialog with application information"""
        about = Adw.AboutDialog(
            application_name="High Tide",
            application_icon="io.github.nokse22.high-tide",
            developer_name="The High Tide Contributors",
            version="1.2.0",
            developers=[
                "Nokse https://github.com/Nokse22",
                "Nila The Dragon https://github.com/nilathedragon",
                "Dråfølin https://github.com/drafolin",
                "Plamper https://github.com/Plamper",
            ],
            copyright="© 2023-2025 Nokse",
            license_type="GTK_LICENSE_GPL_3_0",
            issue_url="https://github.com/Nokse22/high-tide/issues",
            website="https://github.com/Nokse22/high-tide",
        )

        about.add_link(_("Donate with Ko-Fi"), "https://ko-fi.com/nokse22")
        about.add_link(_("Donate with Github"), "https://github.com/sponsors/Nokse22")

        about.set_support_url("https://matrix.to/#/%23high-tide:matrix.org")

        about.present(self.props.active_window)

    def on_preferences_action(self, *args) -> None:
        """Display the preferences window and bind settings to UI controls"""

        if not self.preferences:
            builder: Gtk.Builder = Gtk.Builder.new_from_resource(
                "/io/github/nokse22/high-tide/ui/preferences.ui"
            )

            builder.get_object("_quality_row").set_selected(
                self.settings.get_int("quality")
            )
            builder.get_object("_quality_row").connect(
                "notify::selected", self.on_quality_changed
            )

            builder.get_object("_sink_row").set_selected(
                self.settings.get_int("preferred-sink")
            )
            builder.get_object("_sink_row").connect(
                "notify::selected", self.on_sink_changed
            )

            bg_row: Gtk.Widget = builder.get_object("_background_row")
            bg_row.set_active(self.settings.get_boolean("run-background"))
            self.settings.bind(
                "run-background", bg_row, "active", Gio.SettingsBindFlags.DEFAULT
            )

            builder.get_object("_normalize_row").set_active(
                self.settings.get_boolean("normalize")
            )
            builder.get_object("_normalize_row").connect(
                "notify::active", self.on_normalize_changed
            )

            builder.get_object("_quadratic_volume_row").set_active(
                self.settings.get_boolean("quadratic-volume")
            )
            builder.get_object("_quadratic_volume_row").connect(
                "notify::active", self.on_quadratic_volume_changed
            )

            builder.get_object("_video_cover_row").set_active(
                self.settings.get_boolean("video-covers")
            )
            builder.get_object("_video_cover_row").connect(
                "notify::active", self.on_video_covers_changed
            )

            builder.get_object("_discord_rpc_row").set_active(
                self.settings.get_boolean("discord-rpc")
            )
            builder.get_object("_discord_rpc_row").connect(
                "notify::active", self.on_discord_rpc_changed
            )

            # Auth file path configuration
            self.auth_file_path_row = builder.get_object("_auth_file_path_row")
            current_path = self.settings.get_string("auth-file-path")
            if not current_path:
                current_path = str(get_default_auth_file_path())
            else:
                # Expand tilde for consistent display
                current_path = str(Path(current_path).expanduser())
            self.auth_file_path_row.set_text(current_path)
            self.auth_file_path_row.connect(
                "apply", self.on_auth_file_path_changed
            )

            # Client ID configuration
            self.client_id_row = builder.get_object("_client_id_row")
            current_client_id = self.settings.get_string("client-id")
            self.client_id_row.set_text(current_client_id)
            self.client_id_row.connect("apply", self.on_client_id_changed)

            self.alsa_row = builder.get_object("_alsa_device_row")

            # Create a new label factory to just set max_width
            # Idk how to add the tickmark back
            factory = Gtk.SignalListItemFactory()

            def setup(factory, list_item):
                label = Gtk.Label(xalign=0)
                label.set_width_chars(1)
                list_item.set_child(label)

            def bind(factory, list_item):
                label = list_item.get_child()
                string_obj = list_item.get_item()
                label.set_text(string_obj.get_string())

            factory.connect("setup", setup)
            factory.connect("bind", bind)

            self.alsa_row.set_factory(factory)

            names = Gtk.StringList.new([d["name"] for d in self.alsa_devices])
            self.alsa_row.set_model(names)

            last_used_device = self.settings.get_string("alsa-device")

            selected_index = next(
                (
                    i
                    for i, d in enumerate(self.alsa_devices)
                    if d["hw_device"] == last_used_device
                ),
                0,
            )
            self.alsa_row.set_selected(selected_index)
            builder.get_object("_alsa_device_row").set_selected(selected_index)
            self.alsa_row.connect("notify::selected", self.on_alsa_device_changed)

            alsa_used = AudioSink.ALSA == self.settings.get_int("preferred-sink")
            self.alsa_row.set_sensitive(alsa_used)
            if not alsa_used:
                self.alsa_row.set_selected(0)

            builder.get_object("_sink_row").connect(
                "notify::selected-item", self.deactive_alsa_device_row
            )

            # Last.fm configuration
            self.lastfm_enabled_row = builder.get_object("_lastfm_enabled_row")
            self.lastfm_enabled_row.set_active(
                self.settings.get_boolean("lastfm-enabled")
            )
            self.lastfm_enabled_row.connect(
                "notify::active", self.on_lastfm_enabled_changed
            )

            self.lastfm_login_row = builder.get_object("_lastfm_login_row")
            self.lastfm_login_button = builder.get_object("_lastfm_login_button")
            self.lastfm_login_button.connect("clicked", self.on_lastfm_login_clicked)
            self._update_lastfm_login_ui()

            self.lastfm_scrobble_percentage_row = builder.get_object(
                "_lastfm_scrobble_percentage_row"
            )
            self.lastfm_scrobble_percentage_row.set_value(
                self.settings.get_int("lastfm-scrobble-percentage")
            )
            self.lastfm_scrobble_percentage_row.connect(
                "notify::value", self.on_lastfm_scrobble_percentage_changed
            )

            self.preferences = builder.get_object("_preference_window")

        self.preferences.present(self.win)

    def on_quality_changed(self, widget: Any, *args) -> None:
        self.win.select_quality(widget.get_selected())

    def on_sink_changed(self, widget: Any, *args) -> None:
        self.win.change_audio_sink(widget.get_selected())

    def on_alsa_device_changed(self, widget: Any, *args) -> None:
        index = widget.get_selected()
        device_string = self.alsa_devices[index]["hw_device"]
        self.win.change_alsa_device(device_string)

    def on_normalize_changed(self, widget: Any, *args) -> None:
        self.win.change_normalization(widget.get_active())

    def on_quadratic_volume_changed(self, widget: Any, *args) -> None:
        self.win.change_quadratic_volume(widget.get_active())

    def on_video_covers_changed(self, widget: Any, *args) -> None:
        self.win.change_video_covers_enabled(widget.get_active())

    def on_discord_rpc_changed(self, widget: Any, *args) -> None:
        self.win.change_discord_rpc_enabled(widget.get_active())

    def on_auth_file_path_changed(self, widget: Any, *args) -> None:
        """Handle auth file path changes and ensure directory exists."""
        new_path = widget.get_text().strip()
        if not new_path:
            # Reset to default if empty
            default_path = get_default_auth_file_path()
            widget.set_text(str(default_path))
            self.settings.set_string("auth-file-path", "")
            return

        try:
            path = Path(new_path).expanduser().resolve()
            # Create directory if it doesn't exist
            path.parent.mkdir(parents=True, exist_ok=True)
            self.settings.set_string("auth-file-path", str(path))
        except Exception as e:
            # Log error but don't crash
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to set auth file path: {e}"
            )

    def on_client_id_changed(self, widget: Any, *args) -> None:
        """Handle client ID changes from preferences."""
        new_client_id = widget.get_text().strip()
        self.settings.set_string("client-id", new_client_id)

    def deactive_alsa_device_row(self, widget: Any, *args) -> None:
        alsa_used = widget.get_selected() == AudioSink.ALSA
        self.alsa_row.set_sensitive(alsa_used)
        if not alsa_used:
            self.alsa_row.set_selected(0)

    def on_lastfm_enabled_changed(self, widget: Any, *args) -> None:
        """Handle Last.fm enable/disable toggle."""
        enabled = widget.get_active()
        self.settings.set_boolean("lastfm-enabled", enabled)
        lastfm_scrobbler.scrobbler.enabled = enabled
        self.win.change_lastfm_enabled(enabled)

    def on_lastfm_scrobble_percentage_changed(self, widget: Any, *args) -> None:
        """Handle Last.fm scrobble percentage changes."""
        value = int(widget.get_value())
        self.settings.set_int("lastfm-scrobble-percentage", value)
        lastfm_scrobbler.scrobbler.scrobble_threshold = value

    def on_lastfm_login_clicked(self, widget: Any, *args) -> None:
        """Handle Last.fm login button click."""
        scrobbler = lastfm_scrobbler.scrobbler

        if scrobbler.is_authenticated:
            # Log out
            self._lastfm_logout()
        else:
            # Start login process
            self._lastfm_start_login()

    def _lastfm_start_login(self) -> None:
        """Start the Last.fm web authentication process."""
        scrobbler = lastfm_scrobbler.scrobbler

        # Get auth URL and token
        auth_url = scrobbler.get_auth_url()
        if not auth_url:
            utils.send_toast(_("Failed to start Last.fm authentication"), 3)
            return

        self._lastfm_auth_token = scrobbler.get_auth_token()
        if not self._lastfm_auth_token:
            utils.send_toast(_("Failed to get Last.fm auth token"), 3)
            return

        # Open browser for authentication
        webbrowser.open(auth_url)

        # Update button to show "Complete Login"
        self.lastfm_login_button.set_label(_("Complete Login"))
        self.lastfm_login_button.disconnect_by_func(self.on_lastfm_login_clicked)
        self.lastfm_login_button.connect("clicked", self._lastfm_complete_login)
        self.lastfm_login_row.set_subtitle(
            _("Click 'Complete Login' after authorizing in browser")
        )

        utils.send_toast(
            _("Please authorize in your browser, then click 'Complete Login'"), 5
        )

    def _lastfm_complete_login(self, widget: Any, *args) -> None:
        """Complete the Last.fm authentication after user authorizes in browser."""
        if not self._lastfm_auth_token:
            utils.send_toast(_("No authentication in progress"), 3)
            self._update_lastfm_login_ui()
            return

        # Complete auth in background thread
        def complete_auth():
            scrobbler = lastfm_scrobbler.scrobbler
            session_key = scrobbler.complete_auth(self._lastfm_auth_token)

            if session_key:
                # Save session key and authenticate
                GLib.idle_add(self._lastfm_auth_success, session_key)
            else:
                GLib.idle_add(self._lastfm_auth_failed)

        threading.Thread(target=complete_auth).start()

    def _lastfm_auth_success(self, session_key: str) -> None:
        """Handle successful Last.fm authentication."""
        self.settings.set_string("lastfm-session-key", session_key)
        lastfm_scrobbler.scrobbler.set_session_key(session_key)
        self._lastfm_auth_token = None
        self._update_lastfm_login_ui()
        utils.send_toast(_("Successfully logged in to Last.fm"), 3)

    def _lastfm_auth_failed(self) -> None:
        """Handle failed Last.fm authentication."""
        self._lastfm_auth_token = None
        self._update_lastfm_login_ui()
        utils.send_toast(
            _("Failed to authenticate with Last.fm. Please try again."), 3
        )

    def _lastfm_logout(self) -> None:
        """Log out from Last.fm."""
        self.settings.set_string("lastfm-session-key", "")
        lastfm_scrobbler.scrobbler.disconnect()
        self._update_lastfm_login_ui()
        utils.send_toast(_("Logged out from Last.fm"), 3)

    def _update_lastfm_login_ui(self) -> None:
        """Update the Last.fm login row UI based on authentication state."""
        scrobbler = lastfm_scrobbler.scrobbler

        # Disconnect any existing handlers
        try:
            self.lastfm_login_button.disconnect_by_func(self.on_lastfm_login_clicked)
        except TypeError:
            pass
        try:
            self.lastfm_login_button.disconnect_by_func(self._lastfm_complete_login)
        except TypeError:
            pass

        # Reconnect the main handler
        self.lastfm_login_button.connect("clicked", self.on_lastfm_login_clicked)

        if scrobbler.is_authenticated:
            username = scrobbler.get_username()
            if username:
                self.lastfm_login_row.set_subtitle(
                    _("Logged in as {}").format(username)
                )
            else:
                self.lastfm_login_row.set_subtitle(_("Logged in"))
            self.lastfm_login_button.set_label(_("Log Out"))
        else:
            self.lastfm_login_row.set_subtitle(_("Not logged in"))
            self.lastfm_login_button.set_label(_("Log In"))

    def create_action(
        self, name: str, callback: Callable, shortcuts: List[str] | None = None
    ) -> None:
        """Create a new application action with optional keyboard shortcuts.

        Args:
            name: The action name
            callback: The callback function to execute when action is triggered
            shortcuts: Optional list of keyboard shortcut strings
        """
        action: Gio.SimpleAction = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version: str) -> int:
    """The application's entry point."""
    app: HighTideApplication = HighTideApplication()
    return app.run(sys.argv)
