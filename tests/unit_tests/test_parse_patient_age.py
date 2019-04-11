import pytest
import run as idm

SECONDS_IN_DAY = 24 * 60 * 60
SECONDS_IN_WEEK = 7 * SECONDS_IN_DAY
SECONDS_IN_MONTH = 30 * SECONDS_IN_DAY
SECONDS_IN_YEAR = 365.25 * SECONDS_IN_DAY


def test_parse_age_years():
    patient_age = idm.parse_patient_age('03Y')
    assert patient_age == 3 * SECONDS_IN_YEAR


def test_parse_age_months():
    patient_age = idm.parse_patient_age('23M')
    assert patient_age == 23 * SECONDS_IN_MONTH


def test_parse_age_weeks():
    patient_age = idm.parse_patient_age('18W')
    assert patient_age == 18 * SECONDS_IN_WEEK


def test_parse_age_days():
    patient_age = idm.parse_patient_age('18D')
    assert patient_age == 18 * SECONDS_IN_DAY


