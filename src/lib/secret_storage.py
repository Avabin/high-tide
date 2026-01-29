# secret_storage.py
#
# Copyright 2025 Nokse <nokse@posteo.com>
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 3 of the License, or (at
# your option) any later version.
#
# This file is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public
# License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: LGPL-3.0-or-later

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import tidalapi
from gi.repository import Secret, Xdp

import logging
logger = logging.getLogger(__name__)


def get_auth_file_path() -> Path:
    """Get the path to the auth.json file.

    Returns:
        Path: The path to ~/.high-tide/auth.json
    """
    return Path.home() / ".high-tide" / "auth.json"


def load_client_id() -> Optional[str]:
    """Load the client ID from ~/.high-tide/auth.json if it exists.

    Returns:
        Optional[str]: The client ID if found, None otherwise
    """
    auth_file = get_auth_file_path()
    if not auth_file.exists():
        return None

    try:
        with open(auth_file, "r") as f:
            data = json.load(f)
            return data.get("client_id")
    except Exception:
        logger.exception("Failed to load client ID from auth.json")
        return None


def save_client_id(client_id: str) -> None:
    """Save the client ID to ~/.high-tide/auth.json.

    Args:
        client_id: The client ID to save
    """
    auth_file = get_auth_file_path()

    # Create the directory if it doesn't exist
    auth_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data if file exists
    data: Dict[str, Any] = {}
    if auth_file.exists():
        try:
            with open(auth_file, "r") as f:
                data = json.load(f)
        except Exception:
            logger.exception("Failed to read existing auth.json, will overwrite")

    # Update with new client_id
    data["client_id"] = client_id

    try:
        with open(auth_file, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved client ID to {auth_file}")
    except Exception:
        logger.exception("Failed to save client ID to auth.json")


class SecretStore:
    def __init__(self, session: tidalapi.Session) -> None:
        super().__init__()

        logger.info("initializing secret store")

        self.version = "0.0"
        self.session: tidalapi.Session = session

        self.token_dictionary: Dict[str, str] = {}
        self.attributes: Dict[str, Secret.SchemaAttributeType] = {
            "version": Secret.SchemaAttributeType.STRING
        }

        self.schema = Secret.Schema.new(
            "io.github.nokse22.high-tide", Secret.SchemaFlags.NONE, self.attributes
        )

        self.key: str = "high-tide-login"

        # Ensure the Login keyring is unlocked (https://github.com/Nokse22/high-tide/issues/97)
        # This is also only possible outside of a flatpak.
        if not Xdp.Portal.running_under_flatpak():
            service = Secret.Service.get_sync(Secret.ServiceFlags.NONE)
            if service:
                collection = Secret.Collection.for_alias_sync(
                    service, Secret.COLLECTION_DEFAULT, Secret.CollectionFlags.NONE
                )
                if collection and collection.get_locked():
                    logger.info("Collection is locked, attempting to unlock")
                    service.unlock_sync([collection])

        password = Secret.password_lookup_sync(self.schema, {}, None)
        try:
            if password:
                json_data = json.loads(password)
                self.token_dictionary = json_data

        except Exception:
            logger.exception("Failed to load secret store, resetting")

            self.token_dictionary = {}

    def get(self) -> Tuple[str, str, str]:
        """Get the stored authentication tokens.

        Returns:
            tuple: A tuple containing (token_type, access_token, refresh_token)
        """
        return (
            self.token_dictionary["token-type"],
            self.token_dictionary["access-token"],
            self.token_dictionary["refresh-token"],
        )

    def clear(self) -> None:
        """Clear all stored authentication tokens from memory and keyring.

        Removes tokens from the internal dictionary and deletes them from
        the system keyring/secret storage.
        """
        self.token_dictionary.clear()
        self.save()

        Secret.password_clear_sync(self.schema, {}, None)

    def save(self) -> None:
        """Save the current session tokens to secure storage.

        Stores the session's token_type, access_token, and refresh_token
        in the system keyring for persistent authentication.
        Also saves the client_id to ~/.high-tide/auth.json.
        """
        token_type: str = self.session.token_type
        access_token: str = self.session.access_token
        refresh_token: str = self.session.refresh_token
        expiry_time: Any = self.session.expiry_time

        self.token_dictionary = {
            "token-type": token_type,
            "access-token": access_token,
            "refresh-token": refresh_token,
            "expiry-time": str(expiry_time),
        }

        json_data: str = json.dumps(self.token_dictionary)

        Secret.password_store_sync(
            self.schema, {}, Secret.COLLECTION_DEFAULT, self.key, json_data, None
        )

        # Save client_id to auth.json for easy user configuration
        if self.session.config.client_id:
            save_client_id(self.session.config.client_id)
