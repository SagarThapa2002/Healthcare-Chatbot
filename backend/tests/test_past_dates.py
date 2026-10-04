"""Booking and updating reject dates in the past (chatbot_logic._is_past_date).

"Today" is chatbot_logic._today(): the current date in CLINIC_TIMEZONE, or the
server's local date when that is not set. Every test here fixes it explicitly
by patching _today(), so nothing depends on the real date. 2026-10-03 is a Saturday; dr-okafor works
Fridays, dr-patel Mondays and Wednesdays, and no provider works weekends.

All data files are redirected to a temp directory; the real backend/*.json
files are never read or written.
"""
import datetime
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, reminder_service

# The real implementation, captured before any test patches it.
REAL_TODAY = chatbot_logic._today

OWNER = "7e570000-0000-4000-8000-000000000001"
PAST = chatbot_logic._PAST_DATE_TEXT
SATURDAY = datetime.date(2026, 10, 3)
MONDAY = datetime.date(2026, 10, 5)


class PastDateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        tmp = self.tmp_dir.name
        self.appointments_file = os.path.join(tmp, 'appointments.json')
        patches = [
            patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(chatbot_logic, 'PENDING_FILE', os.path.join(tmp, 'pending_appointments.json')),
            patch.object(chatbot_logic, 'PENDING_UPDATE_FILE', os.path.join(tmp, 'pending_update.json')),
            patch.object(chatbot_logic, 'PENDING_CANCELLATION_FILE', os.path.join(tmp, 'pending_cancellation.json')),
            patch.object(availability_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'REMINDERS_FILE', os.path.join(tmp, 'reminders.json')),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()
        self.client.environ_base['HTTP_X_OWNER_TOKEN'] = OWNER
        self.set_today(SATURDAY)

    def set_today(self, day):
        patcher = patch.object(chatbot_logic, '_today', return_value=day)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, intent, parameters=None):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        return self.client.post('/webhook/webhook', json=body).get_json()

    def text(self, response):
        return response["messages"][0]["content"]["text"]

    def pending_files(self):
        return sorted(f for f in os.listdir(self.tmp_dir.name) if f.startswith("pending_"))

    def saved(self):
        with open(self.appointments_file) as f:
            return json.load(f)


class BookingPastDateTest(PastDateTestCase):
    def book(self, provider_id, date, time=None):
        params = {"name": "Test Patient", "providerId": provider_id, "date": date}
        if time:
            params["time"] = time
        return self.post("Book Appointment", params)

    def test_regression_a_past_date_on_a_working_day_is_rejected(self):
        # Before this check, 2026-10-02 (a Friday dr-okafor works) offered
        # its slots even though it was already in the past.
        response = self.book("dr-okafor", "2026-10-02")
        self.assertEqual(response["context"]["bookingStage"], "date")
        self.assertEqual(self.text(response), PAST)
        self.assertEqual(response["messages"][0]["suggestions"], [])
        self.assertEqual(self.pending_files(), [])

    def test_a_clearly_past_date_is_rejected(self):
        response = self.book("dr-patel", "2020-01-06")
        self.assertEqual(response["context"]["bookingStage"], "date")
        self.assertEqual(self.text(response), PAST)

    def test_a_past_date_is_rejected_at_the_slot_step_too(self):
        response = self.book("dr-okafor", "2026-10-02", time="10:00")
        self.assertEqual(response["context"]["bookingStage"], "date")
        self.assertEqual(self.text(response), PAST)
        self.assertEqual(self.pending_files(), [])

    def test_today_and_tomorrow_go_on_to_the_normal_availability_check(self):
        # Nobody works weekends: the reply is the ordinary availability one,
        # not the past-date one.
        for date in ("2026-10-03", "2026-10-04"):
            with self.subTest(date=date):
                response = self.book("dr-patel", date)
                self.assertEqual(response["context"]["bookingStage"], "date")
                self.assertNotEqual(self.text(response), PAST)
                self.assertIn("isn't available that day", self.text(response))

    def test_a_bookable_today_can_be_booked_end_to_end(self):
        self.set_today(MONDAY)
        self.assertEqual(self.book("dr-patel", "2026-10-05")["context"]["bookingStage"], "slot")
        self.assertEqual(self.book("dr-patel", "2026-10-05", time="10:00")["context"]["bookingStage"], "confirm")
        self.assertEqual(self.post("YesIntent")["context"]["bookingStage"], "booked")
        self.assertEqual(self.saved()[0]["date"], "2026-10-05")

    def test_a_bookable_future_date_offers_slots(self):
        response = self.book("dr-okafor", "2026-10-09")
        self.assertEqual(response["context"]["bookingStage"], "slot")

    def test_a_malformed_date_keeps_its_existing_reply(self):
        for date in ("not-a-date", "2026-02-30"):
            with self.subTest(date=date):
                response = self.book("dr-patel", date)
                self.assertEqual(response["context"]["bookingStage"], "date")
                self.assertEqual(
                    self.text(response),
                    "I couldn't check availability for that date. Could you give me a date in YYYY-MM-DD format?",
                )

    def test_a_fully_booked_future_day_is_still_reported_as_fully_booked(self):
        raw = availability_service.get_available_slots("dr-okafor", "2026-10-09", appointments=[])
        with open(self.appointments_file, 'w') as f:
            json.dump([{"name": "Filler", "providerId": "dr-okafor", "date": "2026-10-09", "time": t,
                        "status": "booked"} for t in raw], f)
        response = self.book("dr-okafor", "2026-10-09")
        self.assertEqual(response["context"]["bookingStage"], "date")
        self.assertIn("fully booked", self.text(response))


class UpdatePastDateTest(PastDateTestCase):
    def setUp(self):
        super().setUp()
        self.post("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel",
                                       "date": "2026-12-28", "time": "10:00"})
        self.appointment_id = self.post("YesIntent")["messages"][0]["content"]["appointment"]["id"]

    def update(self, **fields):
        return self.post("Update Appointment", {"id": self.appointment_id, **fields})

    def test_moving_to_a_past_date_is_rejected(self):
        response = self.update(date="2026-10-02")
        self.assertEqual(response["context"]["updateStage"], "fields")
        self.assertEqual(self.text(response), PAST)
        self.assertEqual(self.pending_files(), [])
        self.assertEqual(self.saved()[0]["date"], "2026-12-28")

    def test_moving_to_today_is_allowed(self):
        self.set_today(MONDAY)
        response = self.update(date="2026-10-05")
        self.assertEqual(response["context"]["updateStage"], "confirm")
        self.assertEqual(self.post("YesIntent")["context"]["updateStage"], "updated")
        self.assertEqual(self.saved()[0]["date"], "2026-10-05")

    def test_moving_to_a_future_date_is_allowed(self):
        response = self.update(date="2026-12-30")
        self.assertEqual(response["context"]["updateStage"], "confirm")

    def test_changing_only_the_time_of_an_appointment_now_in_the_past_is_rejected(self):
        self.set_today(datetime.date(2026, 12, 29))
        response = self.update(time="11:00")
        self.assertEqual(response["context"]["updateStage"], "fields")
        self.assertEqual(self.text(response), PAST)

    def test_conflicts_are_still_checked_for_a_future_date(self):
        self.post("Book Appointment", {"name": "Other", "providerId": "dr-patel", "date": "2026-12-30", "time": "10:00"})
        self.post("YesIntent")
        response = self.update(date="2026-12-30")
        self.assertEqual(response["context"]["updateStage"], "fields")
        self.assertIn("isn't available for that provider", self.text(response))


class TodayTest(unittest.TestCase):
    """_today() itself, with the clock fixed at 2026-10-03 23:30 UTC."""

    INSTANT = datetime.datetime(2026, 10, 3, 23, 30, tzinfo=datetime.timezone.utc)

    def setUp(self):
        instant = self.INSTANT

        class FixedDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        class FixedDate(datetime.date):
            @classmethod
            def today(cls):
                return instant.date()

        for name, fake in (('datetime', FixedDateTime), ('date', FixedDate)):
            patcher = patch.object(chatbot_logic.datetime, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_today_is_the_clinic_date(self):
        for zone, expected in (("Europe/London", datetime.date(2026, 10, 4)),
                               ("America/New_York", datetime.date(2026, 10, 3))):
            with self.subTest(zone=zone), patch.dict(os.environ, {"CLINIC_TIMEZONE": zone}):
                self.assertEqual(REAL_TODAY(), expected)

    def test_without_a_clinic_timezone_it_falls_back_to_the_server_date(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLINIC_TIMEZONE", None)
            self.assertEqual(REAL_TODAY(), datetime.date(2026, 10, 3))


class IsPastDateTest(unittest.TestCase):
    def test_only_well_formed_dates_before_today_are_past(self):
        with patch.object(chatbot_logic, '_today', return_value=SATURDAY):
            self.assertTrue(chatbot_logic._is_past_date("2026-10-02"))
            self.assertTrue(chatbot_logic._is_past_date("2020-01-06"))
            self.assertFalse(chatbot_logic._is_past_date("2026-10-03"))
            self.assertFalse(chatbot_logic._is_past_date("2026-10-04"))
            for value in (None, "", "not-a-date", "2026-02-30", 20261002):
                self.assertFalse(chatbot_logic._is_past_date(value))


if __name__ == '__main__':
    unittest.main()


class FinalConfirmationTest(PastDateTestCase):
    """The date is checked again at the final "yes", immediately before
    anything is saved, in case the clinic date moved on (e.g. midnight)
    after the date was chosen.
    """

    def test_a_booking_whose_date_has_passed_by_yes_is_not_saved(self):
        self.set_today(MONDAY)
        confirm = self.post("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel",
                                                 "date": "2026-10-05", "time": "10:00"})
        self.assertEqual(confirm["context"]["bookingStage"], "confirm")
        self.assertEqual(self.pending_files(), ["pending_appointments.json"])

        self.set_today(datetime.date(2026, 10, 6))  # midnight has passed
        rejected = self.post("YesIntent")

        self.assertEqual(rejected["context"], {"intent": "YesIntent", "bookingStage": "date"})
        self.assertEqual(self.text(rejected), PAST)
        self.assertFalse(os.path.exists(self.appointments_file))
        self.assertEqual(self.pending_files(), [])
        # Nothing stale is left to confirm, and booking continues from the date.
        self.assertIn("no appointment pending", self.text(self.post("YesIntent")))
        retry = self.post("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-10-07"})
        self.assertEqual(retry["context"]["bookingStage"], "slot")

    def test_a_booking_still_dated_today_at_yes_is_saved(self):
        self.set_today(MONDAY)
        self.post("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel",
                                       "date": "2026-10-05", "time": "10:00"})
        self.assertEqual(self.post("YesIntent")["context"]["bookingStage"], "booked")
        self.assertEqual(self.saved()[0]["date"], "2026-10-05")

    def test_an_update_whose_target_date_has_passed_by_yes_changes_nothing(self):
        self.post("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel",
                                       "date": "2026-12-28", "time": "10:00"})
        appointment_id = self.post("YesIntent")["messages"][0]["content"]["appointment"]["id"]
        before = self.saved()

        self.set_today(MONDAY)
        confirm = self.post("Update Appointment", {"id": appointment_id, "date": "2026-10-05"})
        self.assertEqual(confirm["context"]["updateStage"], "confirm")
        self.assertEqual(self.pending_files(), ["pending_update.json"])

        self.set_today(datetime.date(2026, 10, 6))  # midnight has passed
        rejected = self.post("YesIntent")

        self.assertEqual(rejected["context"], {"intent": "YesIntent", "updateStage": "fields"})
        self.assertEqual(self.text(rejected), PAST)
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.pending_files(), [])
        # The update continues from the fields step for the same appointment.
        retry = self.post("Update Appointment", {"id": appointment_id, "date": "2026-10-07"})
        self.assertEqual(retry["context"]["updateStage"], "confirm")

    def test_the_final_date_check_comes_after_the_ownership_re_check(self):
        # Another owner confirming gets the existing "no longer available"
        # reply even when the date has also passed - nothing about the
        # appointment is revealed, and nothing changes.
        self.post("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel",
                                       "date": "2026-12-28", "time": "10:00"})
        appointment_id = self.post("YesIntent")["messages"][0]["content"]["appointment"]["id"]
        before = self.saved()
        self.set_today(MONDAY)
        self.post("Update Appointment", {"id": appointment_id, "date": "2026-10-05"})
        self.set_today(datetime.date(2026, 10, 6))

        self.client.environ_base['HTTP_X_OWNER_TOKEN'] = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b"
        rejected = self.post("YesIntent")

        self.assertNotIn("updateStage", rejected["context"])
        self.assertIn("no longer available to update", self.text(rejected))
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.pending_files(), [])
