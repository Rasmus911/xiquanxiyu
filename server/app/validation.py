from decimal import Decimal, InvalidOperation

from .api.errors import ApiError


def integer_value(value, label, *, minimum=1, maximum=2147483647):
    try:
        if isinstance(value, bool) or len(str(value)) > 80:
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or not minimum <= number <= maximum or number != number.to_integral_value():
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        raise ApiError(f"{label}需要是 {minimum}–{maximum} 范围内的整数", code="INVALID_NUMBER") from None
    return int(number)


def decimal_value(value, label, *, scale=2, minimum=Decimal("0"), positive=False):
    maximum = Decimal("9999999999.99") if scale == 2 else Decimal("999999999.999")
    try:
        if isinstance(value, bool) or len(str(value)) > 80:
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > maximum:
            raise ValueError()
        normalized = number.quantize(Decimal("1").scaleb(-scale))
        if number != normalized:
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        raise ApiError(f"{label}格式或精度无效", code="INVALID_NUMBER") from None
    if minimum is not None and normalized < minimum:
        raise ApiError(f"{label}不能小于 {minimum}", code="INVALID_NUMBER")
    if positive and normalized <= 0:
        raise ApiError(f"{label}必须大于 0", code="INVALID_NUMBER")
    return normalized
