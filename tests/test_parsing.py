from mailauto.parsing import Contact, is_valid_email, write_contacts_csv, load_contacts_csv


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
