import sqlite3

from rflp_lite.adapters.knowledge_sources import read_knowledge_rows, read_sqlite_knowledge_rows


def test_json_and_csv_knowledge_rows():
    assert read_knowledge_rows("history.json", b'[{"id":"h-1"}]')[0]["id"] == "h-1"
    assert read_knowledge_rows("history.csv", b"id,statement\nh-1,hello\n")[0]["id"] == "h-1"


def test_sqlite_reader_is_read_only(tmp_path):
    database = tmp_path / "dataset.db"
    connection = sqlite3.connect(database)
    connection.execute("create table combat_scenarios (id text, title text)")
    connection.execute("insert into combat_scenarios values ('scenario-1', '侦察')")
    connection.commit()
    connection.close()
    rows = read_sqlite_knowledge_rows(database, "combat_scenarios")
    assert rows[0]["id"] == "scenario-1"
    assert not database.with_suffix(".db-journal").exists()
