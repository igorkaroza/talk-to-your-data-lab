"""Persistent agent runtime for the Streamlit UI.

Streamlit reruns the whole script on every interaction, so we cannot
``asyncio.run`` per turn — :class:`claude_agent_sdk.ClaudeSDKClient`
binds its subprocess transport to the loop at ``__aenter__``, and a
per-turn loop would break on the second turn.

Instead, this module owns a single background thread that hosts one
long-lived asyncio loop and one :class:`ClaudeSDKClient`. The Streamlit
main thread drives a turn through :meth:`AgentRuntime.run_turn`, which
returns a plain :class:`queue.Queue` of :data:`genbi.events.TurnEvent`
items terminated by :data:`DONE_SENTINEL` (``None``). The UI drains the
queue from its main thread and never awaits directly.

Wrap :class:`AgentRuntime` construction with ``@st.cache_resource`` in
the app so the thread, loop, and client survive reruns.
"""

from __future__ import annotations

import asyncio
import atexit
import queue
import threading
from collections.abc import Awaitable
from typing import Any

from claude_agent_sdk import ClaudeSDKClient

from genbi.agent import OPTIONS, stream_turn
from genbi.kb_ingest import IngestResult, ingest_upload

DONE_SENTINEL = None


class AgentRuntime:
    """Owns one asyncio loop + one :class:`ClaudeSDKClient` on a worker thread."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="genbi-agent-loop", daemon=True)
        self._thread.start()
        self._client = ClaudeSDKClient(options=OPTIONS)
        self._submit(self._client.__aenter__()).result()
        self._closed = False
        atexit.register(self.close)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Awaitable):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run_turn(self, prompt: str) -> queue.Queue:
        """Kick off one turn and return a queue the UI can drain.

        The queue receives :class:`genbi.events.TurnEvent` instances, or
        an :class:`Exception` if ``stream_turn`` raises. A terminal
        :data:`DONE_SENTINEL` marks end-of-turn.
        """
        q: queue.Queue = queue.Queue()
        self._submit(self._pipe(prompt, q))
        return q

    async def _pipe(self, prompt: str, q: queue.Queue) -> None:
        try:
            async for event in stream_turn(self._client, prompt):
                q.put(event)
        except Exception as err:
            q.put(err)
        finally:
            q.put(DONE_SENTINEL)

    def ingest_files(self, files: list[Any]) -> list[IngestResult]:
        """Synchronously ingest each Streamlit ``UploadedFile`` via the worker loop.

        Blocks the caller until all files are processed. Per-file failures are
        captured in :class:`IngestResult.error`; one bad file does not abort
        the others, so the UI can show per-file outcomes side by side.
        """
        return self._submit(self._ingest_all(files)).result()

    async def _ingest_all(self, files: list[Any]) -> list[IngestResult]:
        return [await ingest_upload(f.name, f.read()) for f in files]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._submit(self._client.__aexit__(None, None, None)).result(timeout=5)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
