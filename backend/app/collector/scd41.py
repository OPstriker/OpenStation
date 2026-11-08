"""Driver for the Sensirion SCD41 CO2 / temperature / humidity sensor on I2C.

Used through the Seeed Grove SCD41 module (I2C address 0x62). The SCD4x speaks
16-bit commands rather than registers; every 16-bit data word is followed by
a CRC-8 (SCD4x datasheet section 3.11). The I2C transport is passed in so the
driver can be tested without hardware.
"""

import time
from collections.abc import Callable
from typing import Protocol

ADDR_DEFAULT = 0x62

CMD_START_PERIODIC = 0x21B1
CMD_READ_MEASUREMENT = 0xEC05
CMD_STOP_PERIODIC = 0x3F86
CMD_SET_TEMPERATURE_OFFSET = 0x241D
CMD_SET_AMBIENT_PRESSURE = 0xE000
CMD_SET_ASC_ENABLED = 0x2416
CMD_GET_DATA_READY = 0xE4B8
CMD_GET_SERIAL = 0x3682

# Execution times (datasheet table 9)
STOP_PERIODIC_S = 0.5
COMMAND_S = 0.001

# set_ambient_pressure accepts 700-1200 hPa
MIN_AMBIENT_HPA = 700.0
MAX_AMBIENT_HPA = 1200.0


class RawI2C(Protocol):
    """Plain I2C write/read transfers to one device address."""

    def write(self, data: bytes) -> None: ...

    def read(self, length: int) -> bytes: ...

    def close(self) -> None: ...


class SMBusRawI2C:
    """RawI2C over smbus2 (/dev/i2c-<bus>), using combined i2c_rdwr transfers."""

    def __init__(self, bus: int, address: int) -> None:
        from smbus2 import SMBus

        self._bus = SMBus(bus)
        self.address = address

    def write(self, data: bytes) -> None:
        from smbus2 import i2c_msg

        self._bus.i2c_rdwr(i2c_msg.write(self.address, data))

    def read(self, length: int) -> bytes:
        from smbus2 import i2c_msg

        msg = i2c_msg.read(self.address, length)
        self._bus.i2c_rdwr(msg)
        # smbus2's stubs type i2c_msg.__iter__ as returning int; at runtime it
        # yields the received bytes as ints.
        return bytes(list(msg))  # type: ignore[call-overload]  # ty: ignore[invalid-argument-type]

    def close(self) -> None:
        self._bus.close()


class CRCError(OSError):
    """A data word failed its CRC: treated like any other bus error."""


def crc8(data: bytes) -> int:
    """Sensirion CRC-8: polynomial 0x31, init 0xFF, no reflection, no final XOR."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def pack_word(word: int) -> bytes:
    data = (word & 0xFFFF).to_bytes(2, "big")
    return data + bytes([crc8(data)])


def unpack_words(raw: bytes) -> list[int]:
    words = []
    for i in range(0, len(raw), 3):
        data, crc = raw[i : i + 2], raw[i + 2]
        if crc8(data) != crc:
            raise CRCError(f"SCD41 CRC mismatch in word {i // 3}")
        words.append(int.from_bytes(data, "big"))
    return words


def convert_measurement(words: list[int]) -> tuple[float, float, float]:
    """read_measurement words -> (CO2 ppm, temperature degC, relative humidity %)."""
    co2, t_raw, rh_raw = words
    return float(co2), -45.0 + 175.0 * t_raw / 65535.0, 100.0 * rh_raw / 65535.0


class SCD41:
    def __init__(
        self, i2c: RawI2C, *, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self.i2c = i2c
        self._sleep = sleep

    def _command(self, cmd: int, delay_s: float = COMMAND_S) -> None:
        self.i2c.write(cmd.to_bytes(2, "big"))
        self._sleep(delay_s)

    def _write_word(self, cmd: int, word: int, delay_s: float = COMMAND_S) -> None:
        self.i2c.write(cmd.to_bytes(2, "big") + pack_word(word))
        self._sleep(delay_s)

    def _read_words(self, cmd: int, count: int) -> list[int]:
        self._command(cmd)
        return unpack_words(self.i2c.read(3 * count))

    def stop_periodic_measurement(self) -> None:
        """Always accepted; the sensor takes 500 ms to become idle."""
        self._command(CMD_STOP_PERIODIC, STOP_PERIODIC_S)

    def start_periodic_measurement(self) -> None:
        """A new measurement every 5 s; the first is ready ~5 s after this."""
        self._command(CMD_START_PERIODIC)

    def data_ready(self) -> bool:
        return (self._read_words(CMD_GET_DATA_READY, 1)[0] & 0x07FF) != 0

    def read_measurement(self) -> tuple[float, float, float]:
        return convert_measurement(self._read_words(CMD_READ_MEASUREMENT, 3))

    def get_serial_number(self) -> int:
        """48-bit serial. Idle mode only."""
        w = self._read_words(CMD_GET_SERIAL, 3)
        return (w[0] << 32) | (w[1] << 16) | w[2]

    def set_ambient_pressure_hpa(self, hpa: float) -> None:
        """Pressure compensation; allowed while measuring. 700-1200 hPa."""
        self._write_word(CMD_SET_AMBIENT_PRESSURE, round(hpa))

    def set_temperature_offset_c(self, offset_c: float) -> None:
        """Idle mode only. Not persisted (persist_settings wears the EEPROM)."""
        self._write_word(CMD_SET_TEMPERATURE_OFFSET, round(offset_c * 65535 / 175))

    def set_asc_enabled(self, enabled: bool) -> None:
        """Automatic self-calibration. Idle mode only. Not persisted."""
        self._write_word(CMD_SET_ASC_ENABLED, 1 if enabled else 0)

    def close(self) -> None:
        self.i2c.close()
