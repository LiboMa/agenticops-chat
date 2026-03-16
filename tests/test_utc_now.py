"""Tests for utc_now() helper."""

from datetime import datetime, timezone

from agenticops.utils.timeutils import utc_now


class TestUtcNow:
    """utc_now() should return naive UTC datetime."""

    def test_returns_datetime(self):
        result = utc_now()
        assert isinstance(result, datetime)

    def test_naive_no_tzinfo(self):
        result = utc_now()
        assert result.tzinfo is None, "utc_now() must return naive datetime for SQLite compat"

    def test_close_to_real_utc(self):
        """Result should be within 1 second of aware UTC now."""
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        result = utc_now()
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert before <= result <= after

    def test_no_deprecation_warning(self, recwarn):
        """No DeprecationWarning should be raised."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            utc_now()  # Should not raise

    def test_sqlite_comparison_compatible(self):
        """Naive datetimes can be compared without TypeError."""
        t1 = utc_now()
        t2 = utc_now()
        assert (t2 - t1).total_seconds() >= 0  # No TypeError
