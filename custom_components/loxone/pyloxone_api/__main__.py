"""
A quick demo of the pyloxone_api module

From the command line, run:

> python -m pyloxone_api -u username -p password -a address -t port

where username, password address and port are your Loxone login credentials

"""
import argparse
import asyncio
import json
import logging
import sys

# The main class you must import is Miniserver.
from . import Miniserver


async def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m pyloxone_api",
        description="A demonstration of how to use this module.",
    )
    parser.add_argument(
        "-u", "--user", help="A Loxone user with appropriate permissions", required=True
    )
    parser.add_argument("-p", "--password", help="The user's password", required=True)
    parser.add_argument(
        "-a", "--address", help="The address of the Miniserver", required=True
    )
    parser.add_argument(
        "-t",
        "--port",
        help="The port on which the Miniserver is listening",
        required=True,
    )
    parser.add_argument(
        "-v", "--verbose", help="Enable debug logging", action="count", default=0
    )

    args = parser.parse_args()

    # Miniserver can be used as a context object, as here. Alternitvely, you can
    # use `Miniserver.connect()`, but you must remember to call
    # `Miniserver.close()` when you have finished.
    async with Miniserver(
        user=args.user, password=args.password, host=args.address, port=args.port
    ) as miniserver:
        # DEBUG level logging will produce a LOT of info
        if args.verbose >= 1:
            # Turn on normal debug logging
            _LOGGER = logging.getLogger("pyloxone_api")
            _LOGGER.setLevel(logging.DEBUG)
            _LOGGER.addHandler(logging.StreamHandler())
        # If you want even more logging, you can turn on logging for the
        # websocket as well
        if args.verbose >= 2:
            # Turn on logging at the websocket level
            _LOGGER2 = logging.getLogger("asyncio.websocket")
            _LOGGER2.setLevel(logging.DEBUG)
            _LOGGER2.addHandler(logging.StreamHandler())

        # The structure file contains details about all the controls which are
        # visible to the user
        print(json.dumps(miniserver.structure, indent=2))

        # If you want to receive status updates from the Miniserver, you need to
        # tell it!
        await miniserver.enable_state_updates()

        while True:
            # Wait for and then print a state update
            print(await miniserver.get_state_updates())
            await asyncio.sleep(0)


if __name__ == "__main__":
    try:
        r = asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        sys.exit()
