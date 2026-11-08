from typing import Protocol


class Sensor(Protocol):
    """A sensor the collector samples once per SAMPLE_INTERVAL_S.

    To add a sensor: implement this protocol in a new module under
    app/collector/, then build it in app/collector/__main__.py:build_sensors().
    Each metric becomes a SensorReading row (sensor=name, metric=key).
    """

    name: str

    def sample(self, elapsed_s: float) -> dict[str, float]:
        """Return metric values for the interval that just ended.

        elapsed_s is the measured time since the previous sample() call.
        """
        ...

    def close(self) -> None: ...
