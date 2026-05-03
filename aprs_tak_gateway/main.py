import argparse
import asyncio
import logging
import sys

from .config import load_config
from .dedupe import Deduper
from .direwolf_agw import DirewolfAgwClient
from .aprsis import AprsIsClient
from .roster import RosterDB
from .tak_client import TakClient

logger = logging.getLogger("aprs_tak_gateway")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="APRS-to-TAK gateway")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML configuration file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging to console")
    return parser.parse_args()


async def _run(config_path: str) -> int:
    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}")
        return 1
    roster_db = RosterDB(config["database"]["path"])
    await roster_db.initialize()
    deduper = Deduper(expiry_seconds=int(config["gateway"].get("dedupe_seconds", 60)))
    tak_client = TakClient(config["tak"])

    tasks = []
    if config["aprsis"].get("enabled", False):
        aprsis_client = AprsIsClient(config["aprsis"], config["gateway"], roster_db, deduper, tak_client)
        tasks.append(asyncio.create_task(aprsis_client.run()))
    if config["direwolf"].get("enabled", False):
        direwolf_client = DirewolfAgwClient(config["direwolf"], config["gateway"], roster_db, deduper, tak_client)
        tasks.append(asyncio.create_task(direwolf_client.run()))

    if not tasks:
        logger.error("No enabled listeners in configuration. Exiting.")
        await roster_db.close()
        return 1

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Gateway shutdown requested")
    finally:
        await roster_db.close()
    return 0


def main() -> None:
    args = parse_args()
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting APRS-to-TAK Gateway")

    try:
        result = asyncio.run(_run(args.config))
    except KeyboardInterrupt:
        logger.info("Received interrupt, exiting")
        sys.exit(0)
    sys.exit(result)


if __name__ == "__main__":
    main()
