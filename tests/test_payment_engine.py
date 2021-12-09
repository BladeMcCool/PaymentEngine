import unittest
import contextlib
from contextlib import redirect_stdout, redirect_stderr
import io, os
from decimal import Decimal, InvalidOperation
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
        filepath = None
        if filename is not None:
            filepath = os.path.dirname(os.path.abspath(__file__)) + os.path.sep + 'fixtures' + os.path.sep + filename
        engine = PaymentEngine(filepath)
        engine.discover_field_order(["type", "client", "tx", "amount"])
        return engine

    def test__invalid_client_id__rejected(self):
        # client id must be >= 1 and <= 65535
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "-100", "1", "1.23"])
            engine.process_record(["deposit", "0", "2", "1.23"])
            engine.process_record(["deposit", "65536", "3", "1.23"])
            engine.process_record(["deposit", "88", "4", "1.23"])
            engine.process_record(["deposit", "1", "33", "1.24"])
            engine.process_record(["deposit", "65535", "3", "1.25"])
            self.assertEqual(3, buffer.getvalue().count("invalid client_id"))

        self.assertNotIn(-100, engine.account_totals)
        self.assertNotIn(0, engine.account_totals)
        self.assertNotIn(65536, engine.account_totals)
        self.assertEqual(Decimal("1.23"), engine.account_totals[88]["total"])
        self.assertEqual(Decimal("1.24"), engine.account_totals[1]["total"])
        self.assertEqual(Decimal("1.25"), engine.account_totals[65535]["total"])

    def test__invalid_tx_id__rejected(self):
        # tx id must be >= 1 and <= 4294967295
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "1", "-1", "1.23"])
            engine.process_record(["deposit", "2", "0", "1.23"])
            engine.process_record(["deposit", "3", "1", "1.33"])
            engine.process_record(["deposit", "4", "4294967295", "1.44"])
            engine.process_record(["deposit", "5", "4294967296", "1.24"])
            self.assertEqual(3, buffer.getvalue().count("invalid tx_id"))

        self.assertNotIn(1, engine.account_totals)
        self.assertNotIn(2, engine.account_totals)
        self.assertNotIn(5, engine.account_totals)
        self.assertEqual(Decimal("1.33"), engine.account_totals[3]["total"])
        self.assertEqual(Decimal("1.44"), engine.account_totals[4]["total"])

    def test__normalize_record_failure__logged_and_skipped(self):
        # because of the possibilty of a failed typecast we should handle failure gracefully.
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "invalidclient", "1", "1.33"])
            engine.process_record(["deposit", "3", "invalidtx", "1.33"])
            engine.process_record(["deposit", "3", "3", "invalidamount"])
            engine.process_record([])
            engine.process_record(["corn", "potato"])
            err_output = buffer.getvalue()
            self.assertIn("invalid literal for int() with base 10: 'invalidclient'", err_output)
            self.assertIn("invalid literal for int() with base 10: 'invalidtx'", err_output)
            self.assertIn("<class 'decimal.ConversionSyntax'>", err_output)
            self.assertIn("list index out of range while attempting to normalize", err_output)
            self.assertIn("invalid literal for int() with base 10: 'potato'", err_output)

    def test__invalid_amount__rejected(self):
        engine = self.get_payment_engine()
        with self.assertRaises(InvalidOperation):
            engine.get_normalized_amount(["deposit", "1", "1", "  13  122   . 99 , 5"])

        with self.assertRaises(InvalidOperation):
            engine.get_normalized_amount(["deposit", "1", "1", ",122   . 99 , 1./234"])

        # preventing negatives too
        with self.assertRaises(ValueError):
            engine.get_normalized_amount(["deposit", "1", "1", "-1"])

        with self.assertRaises(ValueError):
            engine.get_normalized_amount(["withdrawal", "1", "1", "-1"])

    def test__invalid_tx_type__ignored_and_logged(self):
        engine = self.get_payment_engine()
        with self.err_capture() as buffer:
            engine.process_record(["deposit", "55", "1", "0"])
            engine.process_record(["bacon", "55", "123", "17.64"])
            self.assertEqual(Decimal("0"), engine.account_totals[55]["total"])
            self.assertIn('bacon: invalid record_type', buffer.getvalue())

    def test__too_many_decimal_amount__truncated(self):
        # chose to round down in all cases.
        # this requirement possibly could change to round up or down according to different rounding rules
        engine = self.get_payment_engine()
        tx_id = 0
        for try_amount in [
            "5.7245462362",
            "5.72459",
            "5.72451"
        ]:
            tx_id += 1
            self.assertEqual(Decimal("5.7245"), engine.get_normalized_amount(["deposit", "1", tx_id, try_amount]))

    def test__whitespace_around_values__stripped_silently(self):
        engine = self.get_payment_engine()
        engine.process_record(["   deposit   ", " 55     ", "     123 ", "    17.64  "])
        self.assertEqual(Decimal("17.64"), engine.account_totals[55]["available"])
        tx = engine.get_tx(123)
        self.assertIsNotNone(tx)
        self.assertTrue(engine.check_tx(tx, engine.FLAG_DEPOSIT))

    def test__read_transcation_data__without_filename__fails(self):
        # i expect this to raise
        engine = self.get_payment_engine()
        with self.assertRaises(RuntimeError) as test_exc:
            engine.read_transaction_data()

        self.assertEqual(
            'no filename to read has been set. aborting.',
            str(test_exc.exception)
        )

    def test__deposit__credits_account(self):
        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["available"])
        self.assertEqual(Decimal("1.23"), engine.account_totals[55]["total"])

        # though it may be silly, it doesnt seem unreasonable to allow deposit of 0, it should just have no actual effect on the balance.
        engine.process_record(["deposit", "55", "2", "0"])
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
            self.assertEqual("tx_id 1, client_id 55, failed to apply dispute: tx is already disputed\n",
                             buffer.getvalue())

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
        # and possible redundancy in the flag checking given that the logic for not performing anything
        # on locked clients had not been conceptualized yet.

        engine = self.get_payment_engine()
        engine.process_record(["deposit", "55", "1", "1.23"])
        engine.process_record(["dispute", "55", "1"])
        engine.process_record(["resolve", "55", "1"])

        engine.process_record(["deposit", "56", "2", "5.67"])
        engine.process_record(["dispute", "56", "2"])
        engine.process_record(["chargeback", "56", "2"])

        with self.err_capture() as buffer:
            engine.process_record(["resolve", "55", "1"])
            engine.process_record(["chargeback", "55", "1"])
            engine.process_record(["dispute", "55", "1"])

            engine.process_record(["chargeback", "56", "2"])
            engine.process_record(["resolve", "56", "2"])
            engine.process_record(["dispute", "56", "2"])

            self.assertEqual((
                "tx_id 1, client_id 55, failed to apply resolve: tx is already resolved\n"
                "tx_id 1, client_id 55, failed to apply chargeback: tx is resolved\n"
                "tx_id 1, client_id 55, failed to apply dispute: tx is resolved\n"
                "tx_id 2, client_id 56, failed to apply chargeback: tx is already charged back\n"
                "tx_id 2, client_id 56, failed to apply resolve: tx is charged back\n"
                "tx_id 2, client_id 56, failed to apply dispute: tx is charged back\n"
            ), buffer.getvalue())

    def test__sample1_results__matches_expected(self):
        engine = self.get_payment_engine("sample1.csv")
        account_totals = engine.get_account_totals()

        self.assertEqual(Decimal(1.5), account_totals[1]["available"])
        self.assertEqual(Decimal(0.0), account_totals[1]["held"])
        self.assertEqual(Decimal(1.5), account_totals[1]["total"])
        self.assertEqual(False, account_totals[1]["locked"])

        self.assertEqual(Decimal(2.0), account_totals[2]["available"])
        self.assertEqual(Decimal(0.0), account_totals[2]["held"])
        self.assertEqual(Decimal(2.0), account_totals[2]["total"])
        self.assertEqual(False, account_totals[2]["locked"])

    def test__sample1__output_matches_expected(self):
        engine = self.get_payment_engine("sample1.csv")

        f = io.StringIO()
        with redirect_stdout(f):
            engine.generate_output()
        csv_output = f.getvalue()
        expect_output = ("client,available,held,total,locked\n"
                         "1,1.5,0,1.5,false\n"
                         "2,2,0,2,false\n")
        self.assertEqual(expect_output, csv_output)

    def test__no_header__assumes_default_field_order(self):
        engine = self.get_payment_engine("sample1a.csv")
        engine.read_transaction_data()
        self.assertEqual(0, engine.type_field_idx)
        self.assertEqual(1, engine.client_field_idx)
        self.assertEqual(2, engine.tx_field_idx)
        self.assertEqual(3, engine.amount_field_idx)

    def test__sample1a_no_header_in_input__output_matches_expected(self):
        engine = self.get_payment_engine("sample1a.csv")

        f = io.StringIO()
        with redirect_stdout(f):
            engine.generate_output()
        csv_output = f.getvalue()
        expect_output = ("client,available,held,total,locked\n"
                         "1,1.5,0,1.5,false\n"
                         "2,2,0,2,false\n")
        self.assertEqual(expect_output, csv_output)

    def test__sample2__output_matches_expected(self):
        # sample 2 uses nonstandard field order and has some junk columns to ignore
        engine = self.get_payment_engine("sample2.csv")

        f = io.StringIO()
        with redirect_stdout(f):
            engine.generate_output()
        csv_output = f.getvalue()
        expect_output = ("client,available,held,total,locked\n"
                         "1,1.5,0,1.5,false\n"
                         "2,2,0,2,false\n")
        self.assertEqual(expect_output, csv_output)

    def test__sample3__output_matches_expected(self):
        # sample 3 has some more complex scenario with disputes and chargebacks and invalid state attempts etc.
        engine = self.get_payment_engine("sample3.csv")

        f = io.StringIO()
        with redirect_stdout(f):
            engine.generate_output()
        csv_output = f.getvalue()
        expect_output = ("client,available,held,total,locked\n"
                         "1,199.6234,0,199.6234,false\n"
                         "2,1.01,0,1.01,false\n"
                         "3,12.342,0,12.342,false\n"
                         "15,1.00,0.00,1.00,true\n"
                         "16,1.89,0.00,1.89,true\n")
        self.assertEqual(expect_output, csv_output)
