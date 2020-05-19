import time
from typing import Generator, Any, MutableMapping, Union, List, ContextManager
from typing_extensions import TYPE_CHECKING
from contextlib import contextmanager

# Once cwltool's minimum python version hits 3.7 we can use contextlib.nullcontext
@contextmanager
def nullcontext() -> Generator[None, None, None]:
    yield

from ruamel.yaml import safe_dump

if TYPE_CHECKING:
    from .context import RuntimeContext

TimingsT = MutableMapping[str, Any]
class ExecutionTiming:
    """Class to manage timing of named and possibly nested steps.

    Use as a factory for context managers

    timing = ExecutionTiming()

    with timing(ctx, "Complex thing"):
        with timings(ctx, "Step 1"):
            do_stuff()

        with timing(ctx, "Step 2"):
            setup()
            with timing(ctx, "Step A"):
               work()
            tidy_up()

    with timing(ctx, "Simple thing"):
        time.sleep(1)

    Now timing.timings has a dictionary of the top level start/stop
    times and a dictionary of any sub timers.
    """

    def __init__(self) -> None:
        self.timings = {} # type: TimingsT
        self.active_timer_stack = [] # type: List[MutableMapping[str, TimingsT]]

    @contextmanager
    def __call__(self, runtime_context : "RuntimeContext", job_name : str) -> Generator[None, None, None]:
        if runtime_context.toplevel ^ (len(self.active_timer_stack) == 0):
            raise ValueError("Timing nesting has gone wrong")

        self.active_timer_stack.append({})
        start_time = time.perf_counter()
        try:
            yield
        finally:
            stop_time = time.perf_counter()
            data = {
                'start': start_time,
                'stop': stop_time,
                'subtimes': self.active_timer_stack.pop()
            }
            if len(self.active_timer_stack):
               self.active_timer_stack[-1][job_name] = data
            else:
                self.timings[job_name] = data

    def write(self, filename: str) -> None:
        """Output the timings data to a yaml file."""
        with open(filename, "w") as f:
            safe_dump(self.timings, f)

def exec_timing(rt_ctx: "RuntimeContext", name: str) -> ContextManager[None]:
    """Helper factory function for context managers that will either do
    the timings or nothing, depending on whether the RuntimeContext has
    an ExecutionTiming object or None.
    """
    et = rt_ctx.exec_timing
    if et is None:
        return nullcontext()
    return et(rt_ctx, name)
