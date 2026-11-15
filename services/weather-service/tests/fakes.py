from datetime import datetime, timedelta


class FakeClock:
    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class ScriptedFetch:
    """Returns or raises the queued items in order; the last one repeats."""

    def __init__(self, *script):
        self._script = list(script)
        self.calls = 0
        self.cells = []

    async def __call__(self, cell):
        self.calls += 1
        self.cells.append(cell)
        item = self._script[min(self.calls, len(self._script)) - 1]
        if isinstance(item, Exception):
            raise item
        return item
