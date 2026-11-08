"""Driver for the Goermicro SPA06-003 barometer (Seeed Grove Barometer) on I2C.

Port of Seeed's Arduino SPL07-003 "BasicRead" example. The register map and
compensation math follow the SPA06-003 datasheet v2.0. The I2C bus is passed
in (smbus2.SMBus in production, a fake in tests).
"""

import time
from collections.abc import Callable, Sequence
from typing import Protocol

# I2C addresses
ADDR_DEFAULT = 0x77  # SDO high (Grove board default)
ADDR_ALT = 0x76  # SDO low (address pads re-soldered)

# Registers
REG_PSR_B2 = 0x00  # 0x00-0x02 pressure, 0x03-0x05 temperature
REG_PRS_CFG = 0x06
REG_TMP_CFG = 0x07
REG_MEAS_CFG = 0x08
REG_CFG_REG = 0x09
REG_RESET = 0x0C
REG_ID = 0x0D
REG_COEF = 0x10  # 0x10-0x24 (21 bytes)
COEF_LEN = 21

SOFT_RESET = 0x09

# MEAS_CFG status bits
COEF_RDY = 0x80
SENSOR_RDY = 0x40
TMP_RDY = 0x20
PRS_RDY = 0x10

# CFG_REG result bit-shift bits (required when oversampling > 8x)
T_SHIFT = 0x08
P_SHIFT = 0x04

# Measurement rate (upper nibble of PRS_CFG / TMP_CFG)
RATE_1HZ, RATE_2HZ, RATE_4HZ, RATE_8HZ = 0, 1, 2, 3
RATE_16HZ, RATE_32HZ, RATE_64HZ, RATE_128HZ = 4, 5, 6, 7

# Oversampling (lower nibble)
OS_1, OS_2, OS_4, OS_8, OS_16, OS_32, OS_64, OS_128 = range(8)

# Compensation scale factors (datasheet Table 4), indexed by oversampling code
SCALE = (524288, 1572864, 3670016, 7864320, 253952, 516096, 1040384, 2088960)

# Operating modes (MEAS_CTRL, low 3 bits of MEAS_CFG)
MODE_IDLE = 0b000
MODE_CMD_PRES = 0b001
MODE_CMD_TEMP = 0b010
MODE_CONT_PRES = 0b101
MODE_CONT_TEMP = 0b110
MODE_CONT_PRES_TEMP = 0b111

SEA_LEVEL_PA = 101325.0


class I2CBus(Protocol):
    """The subset of smbus2.SMBus the driver uses."""

    def read_byte_data(self, i2c_addr: int, register: int) -> int: ...

    def write_byte_data(self, i2c_addr: int, register: int, value: int) -> None: ...

    def read_i2c_block_data(
        self, i2c_addr: int, register: int, length: int
    ) -> Sequence[int]: ...

    def close(self) -> None: ...


def signed(value: int, bits: int) -> int:
    """Interpret an unsigned `bits`-wide value as two's complement."""
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def decode_coefficients(b: Sequence[int]) -> dict[str, int]:
    """Decode the 21 calibration bytes at REG_COEF (datasheet section 8.11)."""
    return {
        "c0": signed((b[0] << 4) | (b[1] >> 4), 12),
        "c1": signed(((b[1] & 0x0F) << 8) | b[2], 12),
        "c00": signed((b[3] << 12) | (b[4] << 4) | (b[5] >> 4), 20),
        "c10": signed(((b[5] & 0x0F) << 16) | (b[6] << 8) | b[7], 20),
        "c01": signed((b[8] << 8) | b[9], 16),
        "c11": signed((b[10] << 8) | b[11], 16),
        "c20": signed((b[12] << 8) | b[13], 16),
        "c21": signed((b[14] << 8) | b[15], 16),
        "c30": signed((b[16] << 8) | b[17], 16),
        "c31": signed((b[18] << 4) | (b[19] >> 4), 12),
        "c40": signed(((b[19] & 0x0F) << 8) | b[20], 12),
    }


def compensate(
    c: dict[str, int], p_raw: int, t_raw: int, k_p: int, k_t: int
) -> tuple[float, float]:
    """Raw readings -> (pressure Pa, temperature degC), datasheet section 5.6."""
    p_sc = p_raw / k_p
    t_sc = t_raw / k_t
    temperature = c["c0"] * 0.5 + c["c1"] * t_sc
    pressure = (
        c["c00"]
        + p_sc * (c["c10"] + p_sc * (c["c20"] + p_sc * (c["c30"] + p_sc * c["c40"])))
        + t_sc * (c["c01"] + p_sc * (c["c11"] + p_sc * (c["c21"] + p_sc * c["c31"])))
    )
    return pressure, temperature


def calc_altitude(pressure_pa: float, sea_level_pa: float = SEA_LEVEL_PA) -> float:
    """International barometric formula (datasheet section 5.3), metres."""
    return 44330.0 * (1.0 - float((pressure_pa / sea_level_pa) ** (1.0 / 5.255)))


class SPA06_003:
    def __init__(
        self,
        bus: I2CBus,
        address: int = ADDR_DEFAULT,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bus = bus
        self.address = address
        self.chip_id: int | None = None
        self._sleep = sleep
        self._clock = clock
        self._p_os = OS_1
        self._t_os = OS_1
        self.k_p = SCALE[OS_1]
        self.k_t = SCALE[OS_1]
        self.coefficients: dict[str, int] = {}

    # ---- low-level I2C ----
    def _read(self, reg: int, n: int) -> list[int]:
        return list(self.bus.read_i2c_block_data(self.address, reg, n))

    def _read_byte(self, reg: int) -> int:
        return self.bus.read_byte_data(self.address, reg)

    def _write(self, reg: int, value: int) -> None:
        self.bus.write_byte_data(self.address, reg, value & 0xFF)

    # ---- setup ----
    def begin(self, timeout: float = 1.0) -> bool:
        """Soft-reset, wait until ready, load calibration. False on failure."""
        try:
            self.chip_id = self._read_byte(REG_ID)
            self._write(REG_RESET, SOFT_RESET)
        except OSError:
            return False

        self._sleep(0.05)
        deadline = self._clock() + timeout
        ready = COEF_RDY | SENSOR_RDY
        while True:
            try:
                if (self._read_byte(REG_MEAS_CFG) & ready) == ready:
                    break
            except OSError:
                pass  # the sensor may NACK briefly during reset
            if self._clock() > deadline:
                return False
            self._sleep(0.01)

        self.coefficients = decode_coefficients(self._read(REG_COEF, COEF_LEN))
        return True

    def set_pressure_config(self, rate: int, oversampling: int) -> None:
        self._write(REG_PRS_CFG, (rate << 4) | oversampling)
        self._p_os = oversampling
        self.k_p = SCALE[oversampling]
        self._update_shift()

    def set_temperature_config(self, rate: int, oversampling: int) -> None:
        self._write(REG_TMP_CFG, (rate << 4) | oversampling)
        self._t_os = oversampling
        self.k_t = SCALE[oversampling]
        self._update_shift()

    def _update_shift(self) -> None:
        cfg = self._read_byte(REG_CFG_REG) & ~(T_SHIFT | P_SHIFT) & 0xFF
        if self._p_os > OS_8:
            cfg |= P_SHIFT
        if self._t_os > OS_8:
            cfg |= T_SHIFT
        self._write(REG_CFG_REG, cfg)

    def set_mode(self, mode: int) -> None:
        # TMP_EXT = 0: internal temperature sensor (recommended)
        self._write(REG_MEAS_CFG, mode & 0x07)

    # ---- status / data ----
    def status(self) -> int:
        return self._read_byte(REG_MEAS_CFG)

    def read_raw(self) -> tuple[int, int]:
        d = self._read(REG_PSR_B2, 6)
        p_raw = signed((d[0] << 16) | (d[1] << 8) | d[2], 24)
        t_raw = signed((d[3] << 16) | (d[4] << 8) | d[5], 24)
        return p_raw, t_raw

    def read(self) -> tuple[float, float]:
        """Latest result as (pressure Pa, temperature degC)."""
        p_raw, t_raw = self.read_raw()
        return compensate(self.coefficients, p_raw, t_raw, self.k_p, self.k_t)

    def close(self) -> None:
        self.bus.close()
