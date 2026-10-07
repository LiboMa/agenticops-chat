"""Protected values (MVP-2.7.0 S6): every command, reference, id and number is masked before translation and must
come back exactly once — a model never sees them, so it cannot change them; a tampered result is refused."""
import pytest
from agenticops.services.content_protect import ProtectedValuesChanged, protect, protected_hash, restore

F = "`" * 3
SRC = ("Restart nginx on i-0abc123 (see I#12, E-301, pc-2): run `sudo systemctl restart nginx`.\n\n"
       f"{F}bash\naws ec2 describe-instances --region us-east-1\n{F}\n"
       "CPU was 97% for 15 minutes; arn:aws:iam::123456789012:role/ops; https://example.com/x?a=1 from 10.0.0.12")


def test_every_protected_value_is_masked():
    masked, values = protect(SRC)
    for v in ("i-0abc123", "I#12", "E-301", "pc-2", "`sudo systemctl restart nginx`", "97%", "15",
              "arn:aws:iam::123456789012:role/ops", "https://example.com/x?a=1", "10.0.0.12"):
        assert v in values and v not in masked, v
    assert "aws ec2 describe-instances" not in masked
    assert "Restart nginx on" in masked and "minutes" in masked


def test_restore_round_trips():
    masked, values = protect(SRC)
    assert restore(masked, values) == SRC


def test_restore_puts_values_where_the_translation_moved_them():
    masked, values = protect("CPU was 97% on i-0abc123")
    moved = "在 ⟦P1⟧ 上 CPU 为 ⟦P0⟧"
    assert restore(moved, values) == "在 i-0abc123 上 CPU 为 97%"


@pytest.mark.parametrize("tamper", [
    lambda m: m.replace("⟦P0⟧", "", 1),        # dropped
    lambda m: m + " ⟦P0⟧",                      # duplicated
    lambda m: m + " ⟦P99⟧",                     # invented
    lambda m: m.replace("⟦P1⟧", "⟦P 1⟧", 1),    # mangled
])
def test_a_tampered_translation_is_refused(tamper):
    masked, values = protect(SRC)
    with pytest.raises(ProtectedValuesChanged):
        restore(tamper(masked), values)


def test_the_hash_ignores_prose_but_not_values():
    assert protected_hash(SRC) == protected_hash(SRC.replace("Restart nginx on", "重启 nginx，位于"))
    assert protected_hash(SRC) != protected_hash(SRC.replace("97%", "79%"))


def test_text_without_values():
    assert protect("all fine") == ("all fine", [])
    assert restore("一切正常", []) == "一切正常"


def test_a_placeholder_like_string_in_the_source_is_itself_protected():
    masked, values = protect("literal ⟦P0⟧ here")
    assert "⟦P0⟧" in values and restore(masked, values) == "literal ⟦P0⟧ here"
