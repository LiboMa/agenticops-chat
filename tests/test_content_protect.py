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


# ── S6 review: Chinese text sits right next to values (no spaces); \b treats CJK as word characters ──

@pytest.mark.parametrize("text,value", [
    ("问题I#12已修复", "I#12"),
    ("实例i-0abc123重启后正常", "i-0abc123"),
    ("证据E-301显示", "E-301"),
    ("检查pc-2通过", "pc-2"),
    ("地址10.0.0.12不可达", "10.0.0.12"),
])
def test_a_value_next_to_chinese_is_protected_whole(text, value):
    masked, values = protect(text)
    assert value in values and value not in masked


def test_an_en_to_zh_round_trip_without_spaces_passes():
    src = "Issue I#12 on i-0abc123 is fixed (E-301)."
    masked, values = protect(src)
    translated = masked.replace("Issue ", "问题").replace(" on ", "上的").replace(" is fixed ", "已修复").replace(".", "。")
    body = restore(translated, values)
    assert protected_hash(body) == protected_hash(src)


def test_an_arn_or_url_ends_before_chinese_text():
    masked, values = protect("见arn:aws:iam::123456789012:role/ops，以及https://example.com/x。然后")
    assert "arn:aws:iam::123456789012:role/ops" in values and "https://example.com/x" in values
    assert "以及" in masked and "然后" in masked


@pytest.mark.parametrize("word", ["cluster-admin", "cluster-wide", "db-admin", "nat-gateway", "lt-style", "snap-shot"])
def test_a_hyphenated_word_is_prose_not_a_resource_id(word):
    # S7 live E2E: «cluster-admin» was masked as a resource id, the model dropped the opaque placeholder in a
    # parenthetical, and the whole report's translation failed (protected_values_changed)
    masked, values = protect(f"user sa-malibo ({word} via EKS Access Policy) scaled it")
    assert word not in values and word in masked


@pytest.mark.parametrize("rid", ["i-0abc123def4567890", "vol-0a1b2c3d", "sg-12345", "subnet-0ab12", "i-0s4web01",
                                 "cluster-7f3k2", "db-4x9"])
def test_a_resource_id_with_a_digit_is_still_protected(rid):
    masked, values = protect(f"restart {rid} now")
    assert rid in values and rid not in masked


def test_a_translation_may_reorder_the_values():
    # S7 live E2E: zh puts the date before the time — the same values in another order are not a change
    src = "the alarm fired at 08:42:59 UTC on 2026-10-08 on I#1"
    assert protected_hash("告警于 2026-10-08 的 08:42:59 UTC 在 I#1 上触发") == protected_hash(src)


def test_a_duplicated_or_dropped_value_still_changes_the_hash():
    src = "scale from 3 to 2 on I#1"
    assert protected_hash("从 3 扩到 3，I#1") != protected_hash(src)
    assert protected_hash("扩到 2，I#1") != protected_hash(src)


@pytest.mark.parametrize("text, value", [("on 2026-10-08 at 08:42:59", "2026-10-08"),
                                         ("(2026-10-08 08:57:32)", "2026-10-08 08:57:32"),
                                         ("at 2026-10-08T08:57:32Z", "2026-10-08T08:57:32Z")])
def test_a_date_or_datetime_is_one_value(text, value):
    # S7 review: split into three numbers, a date's parts could be permuted (2026-10-08 → 2026-08-10) and the
    # multiset would not notice; as one value it can only move whole
    masked, values = protect(text)
    assert value in values and value not in masked


def test_a_swapped_pair_of_values_passes_by_design():
    # S7 decision (owner 10-08: kept for prose; narrowed per table row in MVP-2.7.1 — see the table tests below):
    # outside a table the values are compared as a multiset, so a translation may put them in another order —
    # which also means two values may trade places; which value goes with which subject is the model's
    assert protected_hash("Restart i-0bbb222, keep i-0aaa111 running.") == protected_hash("Restart i-0aaa111, keep i-0bbb222 running.")


# ── MVP-2.7.1 (owner 10-08): inside a markdown table, the values are compared row by row ──

TABLE = ("| Deployment | Replicas | HPA min / max |\n|---|---|---|\n"
         "| frontend | 3 | 2 / 6 |\n| backend | 2 | 1 / 4 |\n")


def test_a_value_moved_to_another_table_row_changes_the_hash():
    swapped = TABLE.replace("| frontend | 3 |", "| frontend | 2 |").replace("| backend | 2 |", "| backend | 3 |")
    assert sorted(protect(swapped)[1]) == sorted(protect(TABLE)[1])  # the same multiset …
    assert protected_hash(swapped) != protected_hash(TABLE)          # … in other rows


def test_a_translated_table_with_its_values_in_their_rows_passes():
    zh = ("| 部署 | 副本数 | HPA 最小 / 最大 |\n|:---|---:|:---:|\n"
          "| frontend | 3 | 2 / 6 |\n| backend | 2 | 1 / 4 |\n")
    assert protected_hash(zh) == protected_hash(TABLE)


def test_values_may_still_move_within_their_cell():
    src = "| alarm | when |\n|---|---|\n| I#1 | 08:42:59 UTC on 2026-10-08 |\n"
    zh = "| 告警 | 时间 |\n|---|---|\n| I#1 | 2026-10-08 的 08:42:59 UTC |\n"
    assert protected_hash(zh) == protected_hash(src)


def test_two_values_of_one_row_trading_cells_changes_the_hash():
    # the 2.7.0 swap, tightened for table rows: replicas and max trading columns is a change
    src = "| app | replicas | max |\n|---|---|---|\n| web | 3 | 6 |\n"
    assert protected_hash("| app | replicas | max |\n|---|---|---|\n| web | 6 | 3 |\n") != protected_hash(src)


def test_two_values_of_one_cell_may_still_trade_places_by_design():
    # the remaining gap (MVP-2.7.1): within ONE cell the values are a multiset, so «2 / 6» → «6 / 2» passes —
    # the price of letting zh reorder a date and a time inside a cell
    src = "| app | min / max |\n|---|---|\n| web | 2 / 6 |\n"
    assert protected_hash("| app | min / max |\n|---|---|\n| web | 6 / 2 |\n") == protected_hash(src)


def test_outer_pipes_and_cell_padding_do_not_matter():
    src = "| app | n |\n|---|---|\n| web | 3 |\n"
    assert protected_hash("app | n\n:--- | ---:\nweb   |   3\n") == protected_hash(src)


def test_a_table_without_outer_pipes_is_read_too():
    src = "name | replicas\n--- | ---\nweb | 3\napi | 2\n"
    assert protected_hash("name | replicas\n--- | ---\nweb | 2\napi | 3\n") != protected_hash(src)
    assert protected_hash("名称 | 副本数\n--- | ---\nweb | 3\napi | 2\n") == protected_hash(src)


def test_a_value_moved_out_of_its_table_into_prose_changes_the_hash():
    src = "Replicas:\n\n| app | n |\n|---|---|\n| web | 3 |\n"
    assert protected_hash("副本数：3\n\n| 应用 | 数 |\n|---|---|\n| web |  |\n") != protected_hash(src)


def test_merging_or_dropping_a_row_changes_the_hash():
    merged = TABLE.replace("| frontend | 3 | 2 / 6 |\n| backend | 2 | 1 / 4 |\n", "| frontend, backend | 3, 2 | 2 / 6, 1 / 4 |\n")
    assert protected_hash(merged) != protected_hash(TABLE)


def test_a_pipe_inside_code_or_prose_is_not_a_table():
    src = "Run `kubectl get pods | grep web` on 3 nodes, then 2 more.\n"
    assert protected_hash("先在 2 个节点上，再在 3 个节点上运行 `kubectl get pods | grep web`。\n") == protected_hash(src)
