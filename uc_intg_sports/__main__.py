"""
Entry point wrapper for the Sports integration.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio

from uc_intg_sports import main

if __name__ == "__main__":
    asyncio.run(main())
