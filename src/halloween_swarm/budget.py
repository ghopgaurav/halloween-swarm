"""Process-wide count of active agents, so the decision swarm and background review swarms together never
exceed a tick's swarm_budget.max_active_agents."""

import threading
from contextlib import contextmanager


class AgentPool:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.active = 0
        self.peak = 0

    @contextmanager
    def hold(self, n: int, limit: int):
        """Wait until n agents fit under limit, hold them for the block, then release."""
        n = min(n, limit)
        with self._cond:
            while self.active + n > limit:
                self._cond.wait()
            self.active += n
            self.peak = max(self.peak, self.active)
        try:
            yield n
        finally:
            with self._cond:
                self.active -= n
                self._cond.notify_all()

    def take_peak(self) -> int:
        with self._cond:
            peak, self.peak = self.peak, self.active
        return peak


AGENTS = AgentPool()
