"""The Documents page: see what Sahl read, correct it, remove a document, change what you told Sahl. Invented values only."""
import pytest
from fastapi.testclient import TestClient

from sahl import library, server, taught, vault


@pytest.fixture
def docs(monkeypatch, tmp_path):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    lib = library.folder()
    passport = lib / "passport.png"
    passport.write_bytes(b"x")
    with vault._db() as db:
        pid = db.execute("insert into people (name, first, last, dob) values ('Test Person', 'test', 'person', '1990-01-01')").lastrowid
        db.execute("insert into files values (?, 1, ?, ?, 'passport', 0)", (str(passport), int(passport.stat().st_mtime), pid))
        db.execute("insert into readings values (?, 'passport.number', 'X1234567', 0, null)", (str(passport),))
        db.execute("insert into readings values (?, 'passport.expiry', '2031-05-06', 1, null)", (str(passport),))
    trashed = []
    monkeypatch.setattr(library, "trash", lambda p: (trashed.append(p), p.unlink()))
    c = TestClient(server.create_app("t0k"), headers={"x-sahl-token": "t0k"})
    return c, str(passport), str(pid), trashed


def test_a_correction_wins_counts_as_verified_and_survives_a_reread(docs):
    c, path, pid, _ = docs
    assert vault.get("passport.number", pid)["verified"] is False
    page = c.post("/vault/correct", json={"path": path, "key": "passport.number", "value": " X7654321 "}).json()
    field = next(f for f in page["documents"][0]["fields"] if f["id"] == "passport.number")
    assert field == {"key": "number", "id": "passport.number", "value": "X7654321", "read": "X1234567", "verified": True, "edited": True}
    assert vault.get("passport.number", pid) | {"crop": None} == {"value": "X7654321", "verified": True, "source": "passport.png", "crop": None}
    with vault._db() as db:  # a re-read replaces the readings, not the person's change
        db.execute("delete from readings where path=? and key='passport.number'", (path,))
        db.execute("insert into readings values (?, 'passport.number', 'X0000000', 0, null)", (path,))
    assert vault.get("passport.number", pid)["value"] == "X7654321"
    c.post("/vault/correct", json={"path": path, "key": "passport.number", "value": None})  # undo
    assert vault.get("passport.number", pid)["value"] == "X0000000"


def test_only_what_was_read_can_be_corrected(docs):
    c, path, *_ = docs
    assert c.post("/vault/correct", json={"path": path, "key": "made.up", "value": "1"}).status_code == 404
    assert c.post("/vault/correct", json={"path": "/etc/hosts", "key": "passport.number", "value": "1"}).status_code == 404


def test_removing_a_document_sahl_copied_trashes_it_and_forgets_the_person(docs):
    c, path, pid, trashed = docs
    page = c.post("/vault/remove", json={"path": path}).json()
    assert [str(p) for p in trashed] == [path]
    assert page["documents"] == [] and page["people"] == []
    assert vault.get("passport.number", pid) is None


def test_removing_from_a_chosen_folder_leaves_the_file_and_stops_reading_it(docs, tmp_path, monkeypatch):
    c, _, _, trashed = docs
    chosen = tmp_path / "mine"
    chosen.mkdir()
    (chosen / "scan.png").write_bytes(b"x")
    library.set_folder(chosen)
    with vault._db() as db:
        db.execute("insert into files values (?, 1, 1, null, 'other', 0)", (str(chosen / "scan.png"),))
    c.post("/vault/remove", json={"path": str(chosen / "scan.png")})
    assert trashed == [] and (chosen / "scan.png").exists()
    monkeypatch.setattr(vault, "import_document", lambda f: pytest.fail(f"read a removed document: {f}"))
    vault.sync(chosen)
    vault.unhide(str(chosen))  # dropped on Sahl again
    assert not vault._db().execute("select 1 from hidden").fetchone()


def test_removing_needs_a_document_sahl_has(docs):
    c, *_ = docs
    assert c.post("/vault/remove", json={"path": "/etc/hosts"}).status_code == 404


def test_told_values_change_and_go_per_person(docs):
    c, _, pid, _ = docs
    taught.teach("Company", "Acme Test Co", pid)
    taught.teach("Company", "Other Test Co", None)  # told before any person existed
    told = c.get("/vault/documents").json()["told"]
    assert sorted((t["person"], t["value"]) for t in told) == [("0", "Other Test Co"), (pid, "Acme Test Co")]
    assert c.post("/taught/change", json={"concept": "Company", "value": "New Test Co", "person": pid}).status_code == 200
    assert taught.get("Company", pid)["value"] == "New Test Co"
    c.post("/taught/forget", json={"concept": "Company", "person": pid})
    assert taught.get("Company", pid)["value"] == "Other Test Co"  # the one told for anyone is still there
    assert taught.concept_for("Company") == "Company"
