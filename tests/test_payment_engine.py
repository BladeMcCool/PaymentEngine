import unittest
from decimal import Decimal

from payment_engine import PaymentEngine


class TestAccounting(unittest.TestCase):
    def test__decimals_to_4_places__respected_for_amounts(self):
        # test the amount gett
        pass

    def test__deposit__credits_account(self):
        pass

    def test__withdrawal__debits_account(self):
        pass

    def test__withdrawal_nsf__ignored_and_logged(self):
        pass

    def test__dispute__holds_funds(self):
        pass

    def test__dispute_nonexisting_tx__ignored_and_logged(self):
        pass

    def test__resolve__releases_funds(self):
        pass

    def test__resolve_nonexisting_tx__ignored_and_logged(self):
        pass

    def test__resolve_nondisputed_tx__ignored_and_logged(self):
        pass

    def test__chargeback__debits_and_freezes_account(self):
        pass

    def test__chargeback_nonexisting_tx__ignored_and_logged(self):
        pass

    def test__chargeback_nondisputed_tx__ignored_and_logged(self):
        pass

    def test__sample1_results_matches_expected(self):
        engine = PaymentEngine("fixtures/sample1.csv")
        account_totals = engine.get_account_totals()

        self.assertEqual(Decimal(1.5), account_totals[1]["available"])
        self.assertEqual(Decimal(0.0), account_totals[1]["held"])
        self.assertEqual(Decimal(1.5), account_totals[1]["total"])
        self.assertEqual(False, account_totals[1]["locked"])

        self.assertEqual(Decimal(2.0), account_totals[2]["available"])
        self.assertEqual(Decimal(0.0), account_totals[2]["held"])
        self.assertEqual(Decimal(2.0), account_totals[2]["total"])
        self.assertEqual(False, account_totals[2]["locked"])

    def test__sample1_output_matches_expected(self):
        engine = PaymentEngine("fixtures/sample1.csv")
        csv_output = engine.generate_output()

    # brainstorming stuff:
        # it should jfw if the columns are in the wrong order.
            # so make sure we look at the header and not just discard it.

        # what about weird input with dumb padding?
        # client id must be >= 1 and <= 65535
        # tx id must be >= 1 and <= 4294967295
        # amount must be a valid Decimal.
            # If the internal limits of the C version are exceeded, constructing a decimal raises InvalidOperation: make sure it is caught.
        # make sure type is valid. error if not
        # input with more than 4 decimals, only 4 decimals read.
        # withdrawals (or any tx) that could not be proccessed due to error should be logged
            # ex withdrawal that tried to go negative
            # ex dispute/resolve/chargeback that could not be applied, etc

    # questions
        # can we assume the columns will always be in the specified order or should we refer to the header?
        # if the client id in a tx referenced by a dispute, resolve or chargeback does not match the original client id, what should we do?
        # if dispute/resolve/chargeback reference a tx id that is somehow not a deposit, what do?
        # ----
        # if input had too many decimal places are we rounding or truncating?