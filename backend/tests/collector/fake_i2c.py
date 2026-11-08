"""In-memory SPA06-003 register file for driver and sensor tests."""

from collections.abc import Sequence

from app.collector.spa06 import (
    COEF_RDY,
    REG_COEF,
    REG_MEAS_CFG,
    REG_PSR_B2,
    REG_RESET,
    SENSOR_RDY,
)

# Plausible calibration set (12/20/16-bit signed fields, incl. negatives).
COEFFS = {
    "c0": 204,
    "c1": -261,
    "c00": 80469,
    "c10": -54769,
    "c01": -2848,
    "c11": 1214,
    "c20": -10313,
    "c21": 166,
    "c30": -1462,
    "c31": 10,
    "c40": -5,
}


def encode_coefficients(c: dict[str, int]) -> list[int]:
    """Inverse of spa06.decode_coefficients: pack into the 21 register bytes."""

    def b16(v: int) -> list[int]:
        return [(v >> 8) & 0xFF, v & 0xFF]

    return [
        (c["c0"] >> 4) & 0xFF,
        ((c["c0"] & 0x0F) << 4) | ((c["c1"] >> 8) & 0x0F),
        c["c1"] & 0xFF,
        (c["c00"] >> 12) & 0xFF,
        (c["c00"] >> 4) & 0xFF,
        ((c["c00"] & 0x0F) << 4) | ((c["c10"] >> 16) & 0x0F),
        (c["c10"] >> 8) & 0xFF,
        c["c10"] & 0xFF,
        *b16(c["c01"]),
        *b16(c["c11"]),
        *b16(c["c20"]),
        *b16(c["c21"]),
        *b16(c["c30"]),
        (c["c31"] >> 4) & 0xFF,
        ((c["c31"] & 0x0F) << 4) | ((c["c40"] >> 8) & 0x0F),
        c["c40"] & 0xFF,
    ]


class FakeBus:
    """Behaves like smbus2.SMBus talking to one SPA06-003."""

    def __init__(
        self,
        *,
        address: int = 0x77,
        coeffs: dict[str, int] | None = None,
        chip_id: int = 0x11,
    ) -> None:
        self.address = address
        self.regs = [0] * 0x30
        self.regs[0x0D] = chip_id
        self.regs[REG_MEAS_CFG] = COEF_RDY | SENSOR_RDY
        for i, b in enumerate(encode_coefficients(coeffs or COEFFS)):
            self.regs[REG_COEF + i] = b
        self.fail = False
        self.closed = False
        self.writes: list[tuple[int, int]] = []

    def set_raw(self, p_raw: int, t_raw: int) -> None:
        for offset, v in ((0, p_raw), (3, t_raw)):
            v &= 0xFFFFFF
            self.regs[REG_PSR_B2 + offset : REG_PSR_B2 + offset + 3] = [
                (v >> 16) & 0xFF,
                (v >> 8) & 0xFF,
                v & 0xFF,
            ]

    def set_status(self, bits: int) -> None:
        self.regs[REG_MEAS_CFG] = (self.regs[REG_MEAS_CFG] & 0x07) | bits

    def _check(self, addr: int) -> None:
        if self.fail or addr != self.address:
            raise OSError(121, "Remote I/O error")

    def read_byte_data(self, i2c_addr: int, register: int) -> int:
        self._check(i2c_addr)
        return self.regs[register]

    def write_byte_data(self, i2c_addr: int, register: int, value: int) -> None:
        self._check(i2c_addr)
        self.writes.append((register, value))
        if register == REG_RESET:
            return
        if register == REG_MEAS_CFG:
            # Upper bits are read-only status; only MEAS_CTRL is writable.
            value = (self.regs[register] & 0xF8) | (value & 0x07)
        self.regs[register] = value

    def read_i2c_block_data(
        self, i2c_addr: int, register: int, length: int
    ) -> Sequence[int]:
        self._check(i2c_addr)
        return self.regs[register : register + length]

    def close(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
