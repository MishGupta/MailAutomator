import pytest

from mailauto.parsing import Contact, is_valid_email, write_contacts_csv, load_contacts_csv, find_email, parse_rows


def test_is_valid_email():
    assert is_valid_email("akanksha.puri@sourcefuse.com")
    assert is_valid_email("ak@8kmiles.com")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("")
    assert not is_valid_email("foo@bar")  # no TLD


def test_csv_round_trip(tmp_path):
    contacts = [
        Contact("Akanksha Puri", "akanksha.puri@sourcefuse.com",
                "Associate Director HR", "SourceFuse Technologies"),
        Contact("Akhil Jogiparthi", "akhil@ibhubs.co",
                "Vice President - Talent Accelerator", "iB Hubs"),
    ]
    p = tmp_path / "contacts.csv"
    write_contacts_csv(str(p), contacts)
    loaded = load_contacts_csv(str(p))
    assert loaded == contacts


def test_find_email():
    assert find_email(["1", "Jane", "jane@acme.com", "HR", "Acme"]) == (2, "jane@acme.com")
    assert find_email(["SNo", "Name", "Email", "Title", "Company"]) == (-1, "")


def test_parse_rows_normal():
    rows = [
        ["SNo", "Name", "Email", "Title", "Company"],  # header, skipped
        ["1", "Akanksha Puri", "akanksha.puri@sourcefuse.com",
         "Associate Director HR", "SourceFuse Technologies"],
    ]
    out = parse_rows(rows)
    assert len(out) == 1
    assert out[0] == Contact("Akanksha Puri", "akanksha.puri@sourcefuse.com",
                             "Associate Director HR", "SourceFuse Technologies")


def test_parse_rows_skips_rows_without_email():
    rows = [["5", "John Doe", "not-an-email", "Head HR", "Acme"]]
    assert parse_rows(rows) == []


def test_parse_rows_strips_trailing_punctuation_from_company():
    # The PDF table leaves separators on some company cells; left alone they
    # render as "...openings at Estuate,." in the outgoing email.
    rows = [
        ["1", "A B", "a@b.com", "Head HR", "Estuate,"],
        ["2", "C D", "c@d.com", "Head HR", "CEIPAL Corp."],
        ["3", "E F", "e@f.com", "Head HR", "iB Hubs"],
    ]
    out = parse_rows(rows)
    assert out[0].company == "Estuate"
    assert out[1].company == "CEIPAL Corp"
    assert out[2].company == "iB Hubs"  # clean names are untouched


# --- header validation (Finding 2) --------------------------------------------
#
# csv.DictReader silently yields None for any missing column, so a mis-saved
# header ("Email" capitalised, "E-mail", or the header row deleted entirely)
# used to make every contact come out with email="" -- nothing pending, and
# the scheduler would read that as "the list is finished" and shut itself
# down without ever having emailed anyone. These pin that a bad header is now
# a loud failure instead.

def test_load_contacts_csv_rejects_capitalised_header(tmp_path):
    p = tmp_path / "contacts.csv"
    p.write_text("Name,Email,Title,Company\nA,a@b.com,T,C\n")
    with pytest.raises(ValueError):
        load_contacts_csv(str(p))


def test_load_contacts_csv_rejects_e_mail_header(tmp_path):
    p = tmp_path / "contacts.csv"
    p.write_text("name,E-mail,title,company\nA,a@b.com,T,C\n")
    with pytest.raises(ValueError):
        load_contacts_csv(str(p))


def test_load_contacts_csv_rejects_missing_header_row(tmp_path):
    """The header row deleted entirely: the first data row is read as the header."""
    p = tmp_path / "contacts.csv"
    p.write_text("A,a@b.com,T,C\nD,d@e.com,U,V\n")
    with pytest.raises(ValueError):
        load_contacts_csv(str(p))


def test_load_contacts_csv_correct_lowercase_header_still_loads(tmp_path):
    p = tmp_path / "contacts.csv"
    p.write_text("name,email,title,company\nA,a@b.com,T,C\n")
    out = load_contacts_csv(str(p))
    assert out == [Contact("A", "a@b.com", "T", "C")]


def test_load_contacts_csv_utf8_bom_on_correct_header_still_loads(tmp_path):
    """This already worked before the header check was added; must not regress."""
    p = tmp_path / "contacts.csv"
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write("name,email,title,company\nA,a@b.com,T,C\n")
    out = load_contacts_csv(str(p))
    assert out == [Contact("A", "a@b.com", "T", "C")]


def test_load_contacts_csv_empty_file_still_returns_empty_list(tmp_path):
    p = tmp_path / "contacts.csv"
    p.write_text("")
    assert load_contacts_csv(str(p)) == []


def test_parse_rows_split_title_cells():
    # pdfplumber sometimes splits a long title across cells; company is always last
    rows = [["3", "Akhil", "akhil@ibhubs.co",
             "Vice President -", "Talent Accelerator", "iB Hubs"]]
    out = parse_rows(rows)
    assert out[0].title == "Vice President - Talent Accelerator"
    assert out[0].company == "iB Hubs"
    assert out[0].name == "Akhil"
