"""Minimal valid agent.py used by the E2E smoke test.

Validates against the three-step validator in
``services/spm_api/agent_validator.py``:

  1. Parses as Python 3.12.
  2. Has a top-level ``async def main()``.
  3. Imports cleanly (only stdlib).
"""
import asyncio


async def main():
    print("hello from agent")
    await asyncio.sleep(1)


asyncio.run(main())
