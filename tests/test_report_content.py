"""Reports carry their content hash and source language (MVP-2.7.0 S6), stamped on every insert / update."""
import pytest
from agenticops.services.report_content import content_hash, detect_language

FENCE = "`" * 3


@pytest.mark.parametrize("text,lang", [
    ("Daily report: 3 issues found in us-east-1.", "en"),
    ("日报：us-east-1 发现 3 个问题，均已处理。", "zh"),
    ("", "en"),
    (f"{FENCE}\naws ec2 describe-instances --region us-east-1 --output json\n{FENCE}\n中文说明在这里，比较长的一段话", "zh"),
    (f"{FENCE}\n中文中文中文中文中文中文\n{FENCE}\nAll systems nominal today.", "en"),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_content_hash_is_sha256_hex():
    assert content_hash("a") == "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"


def test_a_saved_report_is_stamped(tmp_path, monkeypatch):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import Base, Report, get_session
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/r.db")
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    r = Report(report_type="daily", title="t", summary="s", content_markdown="日报：全部正常，没有发现问题。")
    s.add(r); s.commit()
    assert (r.content_version, r.source_language, r.visibility) == (1, "zh", "workspace")
    assert r.content_hash == content_hash("日报：全部正常，没有发现问题。")
    r.content_markdown = "changed"; s.commit()
    assert r.content_hash == content_hash("changed") and r.source_language == "en"
    s.close()


def test_the_migration_backfills_old_reports(tmp_path):
    import sqlalchemy as sa
    import agenticops.models as models_mod
    eng = sa.create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE reports (id INTEGER PRIMARY KEY, report_type VARCHAR(50), title VARCHAR(200), "
                          "summary TEXT, content_markdown TEXT, content_html TEXT, file_path VARCHAR(500), "
                          "report_metadata JSON, created_at DATETIME)"))
        c.execute(sa.text("INSERT INTO reports (report_type,title,summary,content_markdown) VALUES ('daily','t','s','all fine')"))
    models_mod._run_migrate_2_7_0(eng)
    with eng.begin() as c:
        row = c.execute(sa.text("SELECT content_version, content_hash, source_language, visibility FROM reports")).one()
    assert row == (1, content_hash("all fine"), "en", "workspace")
