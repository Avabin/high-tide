# lastfm_scrobbler.py
#
# Copyright 2025 Nokse
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

import logging
import os
import threading
import time
from enum import Enum
from typing import Optional

from tidalapi import Track

logger = logging.getLogger(__name__)

# Last.fm API credentials
# These can be set via environment variables or will use defaults
# To get your own API key, visit: https://www.last.fm/api/account/create
LASTFM_API_KEY = os.environ.get(
    "LASTFM_API_KEY", "c5dc9d5259e31b90c588f0bcce6ac0e0"
)
LASTFM_API_SECRET = os.environ.get(
    "LASTFM_API_SECRET", "6f3a5bc4c82db64dd9ab5cd54abf6c29"
)

try:
    import pylast

    has_pylast = True
except ImportError:
    logger.warning("pylast not found, Last.fm scrobbling disabled")
    has_pylast = False


class ScrobbleState(Enum):
    DISABLED = 0
    NOT_AUTHENTICATED = 1
    READY = 2
    NOW_PLAYING = 3
    SCROBBLED = 4


class LastFMScrobbler:
    """Handles Last.fm scrobbling functionality.

    This class is thread-safe and can be accessed from multiple threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._network: Optional["pylast.LastFMNetwork"] = None
        self._state: ScrobbleState = ScrobbleState.DISABLED
        self._session_key: str = ""
        self._current_track: Optional[Track] = None
        self._track_start_time: float = 0
        self._scrobbled: bool = False
        self._scrobble_threshold: int = 50  # percentage
        self._enabled: bool = False

    @property
    def state(self) -> ScrobbleState:
        with self._lock:
            return self._state

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = value
            if value and self._session_key:
                self._state = ScrobbleState.READY
            elif value:
                self._state = ScrobbleState.NOT_AUTHENTICATED
            else:
                self._state = ScrobbleState.DISABLED

    @property
    def scrobble_threshold(self) -> int:
        with self._lock:
            return self._scrobble_threshold

    @scrobble_threshold.setter
    def scrobble_threshold(self, value: int) -> None:
        with self._lock:
            self._scrobble_threshold = max(10, min(100, value))

    @property
    def is_authenticated(self) -> bool:
        with self._lock:
            return self._network is not None and self._session_key != ""

    def set_session_key(self, session_key: str) -> bool:
        """Set the Last.fm session key and initialize the network.

        Args:
            session_key: The Last.fm session key obtained from authentication

        Returns:
            bool: True if authentication successful, False otherwise
        """
        if not has_pylast:
            return False

        with self._lock:
            if not session_key:
                self._session_key = ""
                self._network = None
                self._state = (
                    ScrobbleState.NOT_AUTHENTICATED
                    if self._enabled
                    else ScrobbleState.DISABLED
                )
                return False

            try:
                self._network = pylast.LastFMNetwork(
                    api_key=LASTFM_API_KEY,
                    api_secret=LASTFM_API_SECRET,
                    session_key=session_key,
                )
                self._session_key = session_key
                if self._enabled:
                    self._state = ScrobbleState.READY
                logger.info("Last.fm authentication successful")
                return True
            except Exception:
                logger.exception("Failed to authenticate with Last.fm")
                self._session_key = ""
                self._network = None
                self._state = (
                    ScrobbleState.NOT_AUTHENTICATED
                    if self._enabled
                    else ScrobbleState.DISABLED
                )
                return False

    def get_auth_token(self) -> Optional[str]:
        """Get an authentication token for the web-based auth flow.

        Returns:
            str: The auth token to use for web authentication, or None if failed
        """
        if not has_pylast:
            return None

        try:
            # Create a temporary network without session key
            network = pylast.LastFMNetwork(
                api_key=LASTFM_API_KEY,
                api_secret=LASTFM_API_SECRET,
            )
            # Get session key generator
            skg = pylast.SessionKeyGenerator(network)
            # Extract token from URL
            token = skg.get_web_auth_token()
            return token
        except Exception:
            logger.exception("Failed to get Last.fm auth token")
            return None

    def get_auth_url(self) -> Optional[str]:
        """Get the URL for web-based Last.fm authentication.

        Returns:
            str: The URL to open in a browser for authentication, or None if failed
        """
        if not has_pylast:
            return None

        try:
            network = pylast.LastFMNetwork(
                api_key=LASTFM_API_KEY,
                api_secret=LASTFM_API_SECRET,
            )
            skg = pylast.SessionKeyGenerator(network)
            return skg.get_web_auth_url()
        except Exception:
            logger.exception("Failed to get Last.fm auth URL")
            return None

    def complete_auth(self, token: str) -> Optional[str]:
        """Complete the web-based authentication and get session key.

        Args:
            token: The auth token used for web authentication

        Returns:
            str: The session key if successful, or None if failed
        """
        if not has_pylast:
            return None

        try:
            network = pylast.LastFMNetwork(
                api_key=LASTFM_API_KEY,
                api_secret=LASTFM_API_SECRET,
            )
            skg = pylast.SessionKeyGenerator(network)
            session_key = skg.get_web_auth_session_key(token)
            return session_key
        except Exception:
            logger.exception("Failed to complete Last.fm authentication")
            return None

    def get_username(self) -> Optional[str]:
        """Get the authenticated username.

        Returns:
            str: The username if authenticated, or None
        """
        if not self._network:
            return None

        try:
            user = self._network.get_authenticated_user()
            return user.get_name() if user else None
        except Exception:
            logger.exception("Failed to get Last.fm username")
            return None

    def update_now_playing(self, track: Track) -> bool:
        """Update the "Now Playing" status on Last.fm.

        Args:
            track: The track that is currently playing

        Returns:
            bool: True if update was successful, False otherwise
        """
        with self._lock:
            if not self._enabled or not self._network or not track:
                return False

            try:
                artist = (
                    track.artist.name
                    if track.artist
                    else track.artists[0].name
                    if track.artists
                    else "Unknown Artist"
                )
                title = track.name or "Unknown Title"
                album = track.album.name if track.album else None
                duration = track.duration if track.duration else None

                self._network.update_now_playing(
                    artist=artist,
                    title=title,
                    album=album,
                    duration=duration,
                )

                self._current_track = track
                self._track_start_time = time.time()
                self._scrobbled = False
                self._state = ScrobbleState.NOW_PLAYING

                logger.info(f"Now playing: {artist} - {title}")
                return True
            except Exception:
                logger.exception("Failed to update now playing on Last.fm")
                return False

    def scrobble(self, track: Track, timestamp: Optional[int] = None) -> bool:
        """Scrobble a track to Last.fm.

        Args:
            track: The track to scrobble
            timestamp: Unix timestamp when the track started playing (default: current time)

        Returns:
            bool: True if scrobble was successful, False otherwise
        """
        with self._lock:
            if not self._enabled or not self._network or not track:
                return False

            if self._scrobbled:
                logger.debug("Track already scrobbled")
                return False

            try:
                artist = (
                    track.artist.name
                    if track.artist
                    else track.artists[0].name
                    if track.artists
                    else "Unknown Artist"
                )
                title = track.name or "Unknown Title"
                album = track.album.name if track.album else None

                if timestamp is None:
                    timestamp = (
                        int(self._track_start_time)
                        if self._track_start_time
                        else int(time.time())
                    )

                self._network.scrobble(
                    artist=artist,
                    title=title,
                    timestamp=timestamp,
                    album=album,
                )

                self._scrobbled = True
                self._state = ScrobbleState.SCROBBLED

                logger.info(f"Scrobbled: {artist} - {title}")
                return True
            except Exception:
                logger.exception("Failed to scrobble to Last.fm")
                return False

    def check_scrobble_threshold(
        self, position_seconds: float, duration_seconds: float
    ) -> bool:
        """Check if the scrobble threshold has been reached and scrobble if so.

        According to Last.fm rules, a track should be scrobbled when the user has listened
        to at least half of the track, or for 4 minutes - whichever occurs first.

        Args:
            position_seconds: Current playback position in seconds
            duration_seconds: Total track duration in seconds

        Returns:
            bool: True if scrobble was triggered, False otherwise
        """
        track = None
        should_scrobble = False

        with self._lock:
            if not self._enabled or not self._current_track or self._scrobbled:
                return False

            if duration_seconds <= 0:
                return False

            percentage = (position_seconds / duration_seconds) * 100

            # Last.fm recommendation: scrobble after 50% or 4 minutes (240 seconds)
            # We use the user's configured threshold percentage
            should_scrobble = (
                percentage >= self._scrobble_threshold or position_seconds >= 240
            )

            if should_scrobble and not self._scrobbled:
                # Copy track reference before releasing lock
                track = self._current_track

        # Call scrobble outside the lock since it acquires its own lock
        if should_scrobble and track:
            return self.scrobble(track)

        return False

    def on_track_changed(self, track: Optional[Track]) -> None:
        """Handle track change events.

        Args:
            track: The new track, or None if playback stopped
        """
        if track:
            self.update_now_playing(track)
        else:
            with self._lock:
                self._current_track = None
                self._scrobbled = False
                self._track_start_time = 0
                if self._enabled and self._network is not None and self._session_key:
                    self._state = ScrobbleState.READY

    def disconnect(self) -> None:
        """Disconnect and clean up."""
        with self._lock:
            self._network = None
            self._session_key = ""
            self._current_track = None
            self._scrobbled = False
            self._track_start_time = 0
            self._state = (
                ScrobbleState.NOT_AUTHENTICATED
                if self._enabled
                else ScrobbleState.DISABLED
            )


# Global scrobbler instance
scrobbler = LastFMScrobbler()
