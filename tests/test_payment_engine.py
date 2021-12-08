import contextlib
import unittest
from contextlib import redirect_stdout, redirect_stderr
import io
from decimal import Decimal
from payment_engine import PaymentEngine


class TestAccounting(unittest.TestCase):

    @contextlib.contextmanager
    def err_capture(self):
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            try:
                yield buffer
            finally:
                buffer.close()

    def get_payment_engine(self, filename=None):
        return PaymentEngine(filename)

    def test__invalid_client_id__rejected(self):
        pass

    def test__invalid_tx_id__rejected(self):
        pass

    def test__invalid_amount__rejected(self):
        # try string
        # try weird number like "  13  122   . 99 , 5"
        # try weird number like ",122   . 99 , 5"
        # try weird number like ",122   . 99 , 1./234"
        pass

    def test__invalid_tx_type__ignored_and_logged(self):
        pass

    def test__too_many_decimal_amount__truncated(self):
        # chose to round down in all cases.
        # this requirement possibly could change to round up or down according to different rounding rules
        pass

    def test__whitespace_around_values__stripped_silently(self):
        engine = self.get_payment_engine()
        engine.process_record(["   deposit   ", " 55     ", "     123 ", "    17.64  "])
        self.assertEqual(Decimal("17.64"), engine.account_totals[55]["available"])
        tx = engine.get_tx(123)
        self.assertIsNotNone(tx)
        self.assertTrue(engine.check_tx(tx, engine.FLAG_DEPOSIT))

    def test__read_transcation_data__without_filename__fails(self):
        # i expect this to raise
        pass

    def test__deposit__credits_account(self):
        engine = self.get_payment_engine()

        engine.process_record(["deposit", "55", "1", "1.23"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])

    def test_deposit_existing_tx_id__ignored_and_logged(self):
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "55", "1", "12.23"])
            engine.process_record(["withdrawal", "55", "2", "3.45"])
            engine.process_record(["deposit", "55", "2", "999.99"])
            self.assertEqual(
                "tx_id 2, client_id 55, failed to apply deposit of $999.99: deposit duplicates existing tx_id\n",
                buffer.getvalue()
            )

        self.assertEqual(Decimal("8.78"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("8.78"), engine.account_totals[55]["total"])

    def test__withdrawal__debits_account(self):
        engine = self.get_payment_engine()

        # establish a balance
        engine.process_record(["deposit", "55", "1", "1.23"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])

        # withdraw it
        engine.process_record(["withdrawal", "55", "2", "1.23"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["total"])
        self.assertFalse(engine.account_totals[55]["locked"])

    def test__withdrawal_nsf__ignored_and_logged(self):
        engine = self.get_payment_engine()

        engine.process_record(["deposit", "55", "1", "1.23"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])

        with self.err_capture() as buffer:
            engine.process_record(["withdrawal", "55", "2", "1.24"])
            self.assertEqual("tx_id 2, client_id 55, failed to apply withdrawal of $1.24: nsf\n", buffer.getvalue())

        # available and total funds unchanged
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])

    def test_withdrawal_existing_tx_id__ignored_and_logged(self):
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "55", "1", "1.23"])
            engine.process_record(["withdrawal", "55", "1", "1.23"])
            self.assertEqual(
                "tx_id 1, client_id 55, failed to apply withdrawal of $1.23: withdrawal duplicates existing tx_id\n",
                buffer.getvalue()
            )

        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])

    def test__dispute__holds_funds(self):
        engine = self.get_payment_engine()

        # establish a balance
        engine.process_record(["deposit", "55", "1", "1.23"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["held"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])

        # dispute it
        engine.process_record(["dispute", "55", "1"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["held"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])
        self.assertFalse(engine.account_totals[55]["locked"])
        self.assertTrue(engine.check_tx(engine.get_tx(1), engine.FLAG_DISPUTE))

    def test__dispute_nonexisting_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["dispute", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply dispute: tx not found\n", buffer.getvalue())

    def test__dispute_otherclient_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "44", "987", "1.23"])

        with self.err_capture() as buffer:
            engine.process_record(["dispute", "55", "987"])
            self.assertEqual("tx_id 987, client_id 55, failed to apply dispute: tx client_id mismatch\n",
                             buffer.getvalue())

    def test__dispute_nondeposit_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["withdrawal", "55", "2", ".23"])

        with self.err_capture() as buffer:
            engine.process_record(["dispute", "55", "2"])
            self.assertEqual("tx_id 2, client_id 55, failed to apply dispute: tx is not a deposit\n", buffer.getvalue())

    def test__dispute_chargedback_tx__ignored_and_logged(self):
        # cannot dispute something that was already chargedback
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "55", "1", "1.23"])
            engine.process_record(["dispute", "55", "1"])
            engine.process_record(["chargeback", "55", "1"])
            engine.process_record(["dispute", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply dispute: tx is charged back\n", buffer.getvalue())

    def test__dispute_resolved_tx__ignored_and_logged(self):
        # cannot dispute something that was already resolved
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "55", "1", "1.23"])
            engine.process_record(["dispute", "55", "1"])
            engine.process_record(["resolve", "55", "1"])
            engine.process_record(["dispute", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply dispute: tx is resolved\n", buffer.getvalue())

    def test__dispute_disputed_tx__ignored_and_logged(self):
        # cannot dispute something that is already under dispute
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "55", "1", "1.23"])
            engine.process_record(["dispute", "55", "1"])
            engine.process_record(["dispute", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply dispute: tx is already disputed\n", buffer.getvalue())

    def test__resolve__releases_funds(self):
        engine = self.get_payment_engine()

        # establish a balance
        engine.process_record(["deposit", "55", "1", "1.23"])

        # dispute it + check status is as expected
        engine.process_record(["dispute", "55", "1"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["held"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])
        self.assertFalse(engine.account_totals[55]["locked"])
        self.assertTrue(engine.check_tx(engine.get_tx(1), engine.FLAG_DISPUTE))

        # resolve it + check status is as expected
        engine.process_record(["resolve", "55", "1"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["held"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])
        self.assertFalse(engine.account_totals[55]["locked"])
        self.assertTrue(engine.check_tx(engine.get_tx(1), engine.FLAG_RESOLVE))

    def test__resolve_nonexisting_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["resolve", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply resolve: tx not found\n", buffer.getvalue())

    def test__resolve_nondeposit_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["withdrawal", "55", "2", ".23"])

        with self.err_capture() as buffer:
            engine.process_record(["resolve", "55", "2"])
            self.assertEqual("tx_id 2, client_id 55, failed to apply resolve: tx is not a deposit\n", buffer.getvalue())

    def test__resolve_nondisputed_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["withdrawal", "55", "2", ".23"])

        with self.err_capture() as buffer:
            engine.process_record(["resolve", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply resolve: tx is not disputed\n", buffer.getvalue())

    def test__resolve_chargedback_tx__ignored_and_logged(self):
        # cannot resolve something that was already charged back

        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["dispute", "55", "1"])
        engine.process_record(["chargeback", "55", "1"])

        with self.err_capture() as buffer:
            engine.process_record(["resolve", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply resolve: tx is charged back\n", buffer.getvalue())

    def test__chargeback__debits_and_locks_account(self):
        engine = self.get_payment_engine()

        # establish a balance
        engine.process_record(["deposit", "55", "1", "1.23"])

        # dispute it + check status is as expected
        engine.process_record(["dispute", "55", "1"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["held"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])
        self.assertFalse(engine.account_totals[55]["locked"])
        self.assertTrue(engine.check_tx(engine.get_tx(1), engine.FLAG_DISPUTE))

        # chargeback it + check status is as expected
        engine.process_record(["chargeback", "55", "1"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["held"])
        self.assertEqual(Decimal("0"), engine.account_totals[55]["total"])
        self.assertTrue(engine.account_totals[55]["locked"])
        self.assertTrue(engine.check_tx(engine.get_tx(1), engine.FLAG_CHARGEBACK))

    def test__chargeback_nonexisting_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["chargeback", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply chargeback: tx not found\n", buffer.getvalue())

    def test__chargeback_nondeposit_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["withdrawal", "55", "2", ".23"])

        with self.err_capture() as buffer:
            engine.process_record(["chargeback", "55", "2"])
            self.assertEqual("tx_id 2, client_id 55, failed to apply chargeback: tx is not a deposit\n",
                             buffer.getvalue())

    def test__chargeback_nondisputed_tx__ignored_and_logged(self):
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["withdrawal", "55", "2", ".23"])

        with self.err_capture() as buffer:
            engine.process_record(["chargeback", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply chargeback: tx is not disputed\n",
                             buffer.getvalue())

    def test__chargeback_resolved_tx__ignored_and_logged(self):
        # cannot charge back a tx that was resolved
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["dispute", "55", "1"])
        engine.process_record(["resolve", "55", "1"])

        with self.err_capture() as buffer:
            engine.process_record(["chargeback", "55", "1"])
            self.assertEqual("tx_id 1, client_id 55, failed to apply chargeback: tx is resolved\n", buffer.getvalue())

    def test__operation_on_finalized_tx__ignored_and_logged(self):
        # cannot do anything more on a tx that was either charged back or resolved.
        # i wanted to abstract this concept better but was running out of time.
        # so we have a lot of very similar code of checking tx flags in the various record processing functions.

        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["dispute", "55", "1"])
        engine.process_record(["resolve", "55", "1"])

        engine.process_record(["deposit", "55", "2", "5.67"])
        engine.process_record(["dispute", "55", "2"])
        engine.process_record(["chargeback", "55", "2"])

        with self.err_capture() as buffer:
            engine.process_record(["resolve", "55", "1"])
            engine.process_record(["chargeback", "55", "1"])
            engine.process_record(["dispute", "55", "1"])

            engine.process_record(["chargeback", "55", "2"])
            engine.process_record(["resolve", "55", "2"])
            engine.process_record(["dispute", "55", "2"])

            self.assertEqual((
                "tx_id 1, client_id 55, failed to apply resolve: tx is already resolved\n"
                "tx_id 1, client_id 55, failed to apply chargeback: tx is resolved\n"
                "tx_id 1, client_id 55, failed to apply dispute: tx is resolved\n"
                "tx_id 2, client_id 55, failed to apply chargeback: tx is already charged back\n"
                "tx_id 2, client_id 55, failed to apply resolve: tx is charged back\n"
                "tx_id 2, client_id 55, failed to apply dispute: tx is charged back\n"
            ), buffer.getvalue())


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

        f = io.StringIO()
        with redirect_stdout(f):
            engine.generate_output()
        csv_output = f.getvalue()
        expect_output = ("client,available,held,total,locked\n"
                         "1,1.5,0,1.5,false\n"
                         "2,2,0,2,false\n")
        self.assertEqual(expect_output, csv_output)

    # brainstorming stuff:
    # it should jfw if the columns are in the wrong order.
    # so make sure we look at the header and not just discard it.

    # what about weird input with dumb padding?
    # client id must be >= 1 and <= 65535
    # tx id must be >= 1 and <= 4294967295
    # amount must be a valid Decimal.
    #    If the internal limits of the C version are exceeded, constructing a decimal raises InvalidOperation: make sure it is caught.
    # make sure type is valid. error if not
    # input with more than 4 decimals, only 4 decimals read.
    # withdrawals (or any tx) that could not be proccessed due to error should be logged
    # ex withdrawal that tried to go negative
    # ex dispute/resolve/chargeback that could not be applied, etc
    # csv data with quoted fields?
    # csv data with thousands separator in numeric values?

    # questions
    # can we assume the columns will always be in the specified order or should we refer to the header?
    #  could do dynamic but up to me
    # if the client id in a tx referenced by a dispute, resolve or chargeback does not match the original client id, what should we do?
    #  err, log and move on
    # if dispute/resolve/chargeback reference a tx id that is somehow not a deposit, what do?
    #  err, log and move on
    # ----
    # if input had too many decimal places are we rounding or truncating?
    # consider 180 day chargeback window? b/c otherwise we hae to track all tx ids indefinitely in memory or make use of the file system/external db
    #  ... theres no dates on the tx, so can't really know.

