"""Issue #295: P-scaled numeric items (a negative cobc scale, or a scale
larger than the stored digits) decode to the value they hold. Attributes
are cobc 3.1.2's own for each PICTURE."""

from __future__ import annotations

import pytest

from mockymock.debug.variable_map import _decode_field


@pytest.mark.parametrize(
    ("type_code", "digits", "scale", "flags", "raw", "expected"),
    [
        (0x10, 6, -3, 0, b"637", "637000"),  # PIC 9(3)PPP
        (0x10, 4, 4, 0, b"12", "0.0012"),  # PIC VPP99
        (0x12, 6, -3, 1, bytes([0x04, 0x5D]), "-45000"),  # S9(3)PPP COMP-3
        (0x11, 6, -3, 0x20, (12).to_bytes(2, "big"), "12000"),  # 9(3)PPP COMP
    ],
)
def test_p_scaled_items_decode_to_their_value(
    type_code, digits, scale, flags, raw, expected
) -> None:
    assert (
        _decode_field("X", type_code, digits, scale, flags, "", raw).decoded == expected
    )
