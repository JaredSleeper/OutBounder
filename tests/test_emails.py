from src.pipeline import emails


def test_split_name_handles_honorifics_and_accents():
    assert emails.split_name("Dr. José Núñez-García Jr.") == ("jose", "nunezgarcia")
    assert emails.split_name("Mary Anne O'Neil") == ("mary", "oneil")
    assert emails.split_name("Prince") == ("prince", "")


def test_permutations_cover_common_patterns():
    perms = emails.permutations("jane", "doe", "acme.com")
    assert perms["first.last"] == "jane.doe@acme.com"
    assert perms["flast"] == "jdoe@acme.com"
    assert perms["first"] == "jane@acme.com"
    assert "last.first" in perms


def test_permutations_without_last_name_skip_last_patterns():
    perms = emails.permutations("prince", "", "acme.com")
    assert perms == {"first": "prince@acme.com"}


def test_infer_pattern_from_sample():
    assert emails.infer_pattern("jdoe@acme.com", "jane", "doe") == "flast"
    assert emails.infer_pattern("jane.doe@acme.com", "jane", "doe") == "first.last"
    assert emails.infer_pattern("hello@acme.com", "jane", "doe") is None


def test_extract_emails_filters_generic_and_other_domains():
    text = "Reach jane.doe@acme.com or info@acme.com, not bob@other.com."
    assert emails.extract_emails(text, "acme.com") == ["jane.doe@acme.com"]


def test_shape_guesses():
    assert emails._shape("j.doe") == "f.last"
    assert emails._shape("jane.d") == "first.l"
    assert emails._shape("jane.doe") == "first.last"
    assert emails._shape("jane_doe") == "first_last"
    assert emails._shape("jane") == "first"
    assert emails._shape("janedoe") is None
