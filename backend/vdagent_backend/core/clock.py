"""Wall-clock time: aware UTC datetimes and the API timestamp format `YYYY-MM-DDTHH:MM:SS.mmmZ`."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """The current time as an aware UTC `datetime`."""
    return datetime.now(UTC)


def iso_ms(moment: datetime) -> str:
    """`moment` (aware) in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, the format every API timestamp uses."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
