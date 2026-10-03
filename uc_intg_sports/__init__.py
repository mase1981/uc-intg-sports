"""
Sports integration for Unfolded Circle Remote.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

# Version: single source of truth in driver.json
try:
    _driver_path = Path(__file__).parent.parent / "driver.json"
    with open(_driver_path, "r", encoding="utf-8") as f:
        __version__ = json.load(f).get("version", "0.0.0")
except (FileNotFoundError, json.JSONDecodeError):
    __version__ = "0.0.0"

__all__ = ["__version__", "main"]

_LOG = logging.getLogger(__name__)


async def main():
    """Main entry point."""
    from ucapi import DeviceStates
    from ucapi_framework import get_config_path

    from uc_intg_sports import logos
    from uc_intg_sports.config import SportsConfig, SportsConfigManager
    from uc_intg_sports.driver import SportsDriver
    from uc_intg_sports.setup_flow import SportsSetupFlow

    level = os.getenv("UC_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
    logging.getLogger("PIL").setLevel(logging.WARNING)

    _LOG.info("Starting Sports Integration v%s", __version__)

    driver = SportsDriver()

    config_path = get_config_path(driver.api.config_dir_path or "")
    _LOG.info("Using configuration path: %s", config_path)
    logos.set_cache_dir(os.path.join(config_path, "logos"))

    config_manager = SportsConfigManager(
        config_path,
        add_handler=driver.on_device_added,
        remove_handler=driver.on_device_removed,
        config_class=SportsConfig,
    )
    driver.config_manager = config_manager

    setup_handler = SportsSetupFlow.create_handler(driver)

    driver_json = os.path.join(os.path.dirname(__file__), "..", "driver.json")
    await driver.api.init(os.path.abspath(driver_json), setup_handler)

    await driver.register_all_device_instances(connect=False)

    team_count = len(list(config_manager.all()))
    await driver.api.set_device_state(DeviceStates.CONNECTED if team_count > 0 else DeviceStates.DISCONNECTED)
    _LOG.info("Sports integration started - %d team(s) followed", team_count)

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
