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


def test_parse_rows_split_title_cells():
    # pdfplumber sometimes splits a long title across cells; company is always last
    rows = [["3", "Akhil", "akhil@ibhubs.co",
             "Vice President -", "Talent Accelerator", "iB Hubs"]]
    out = parse_rows(rows)
    assert out[0].title == "Vice President - Talent Accelerator"
    assert out[0].company == "iB Hubs"
    assert out[0].name == "Akhil"
