import csv
import sys
from decimal import Decimal, ROUND_DOWN, InvalidOperation


class PaymentEngine:
    FLAG_DEPOSIT = 1
    FLAG_WITHDRAWAL = 2
    FLAG_DISPUTE = 4
    FLAG_RESOLVE = 8
    FLAG_CHARGEBACK = 16

    def __init__(self, filename):
        self.filename = filename
        self.account_totals = {}
        self.valid_record_types = {"deposit", "withdrawal", "dispute", "resolve", "chargeback"}
        self.tx_log = {}

        self.type_field_idx = 0
        self.client_field_idx = 1
        self.tx_field_idx = 2
        self.amount_field_idx = 3

    def read_transaction_data(self):
        if not self.filename:
            raise RuntimeError("no filename to read has been set. aborting.")
        with open(self.filename) as file:
            csvreader = csv.reader(file)
            _ = next(csvreader)  # read and discard header -- but maybe we should interpret it for record field order?
            for record in csvreader:
                self.process_record(record)

    def get_client_record(self, client_id):
        if client_id not in self.account_totals:
            self.account_totals[client_id] = {
                "available": Decimal(0),
                "held": Decimal(0),
                "total": Decimal(0),
                "locked": False,
            }
        return self.account_totals[client_id]

    def process_record(self, record):

        if not self.attempt_normalize_record(record):
            return

        if not self.validate_record(record):
            return

        record_type = record[self.type_field_idx]
        client_id = record[self.client_field_idx]
        tx_id = record[self.tx_field_idx]

        existing_tx = self.get_tx(tx_id)

        if existing_tx and existing_tx[1] != client_id:
            self.error_log("tx client_id mismatch", tx_id, client_id, record_type)
            return

        client_accounting = self.get_client_record(client_id)

        if record_type == "deposit":
            self.process_deposit(client_accounting, existing_tx, tx_id, client_id, record)
        elif record_type == "withdrawal":
            self.process_withdrawal(client_accounting, existing_tx, tx_id, client_id, record)
        elif record_type == "dispute":
            self.process_dispute(client_accounting, existing_tx, tx_id, client_id)
        elif record_type == "resolve":
            self.process_resolve(client_accounting, existing_tx, tx_id, client_id)
        elif record_type == "chargeback":
            self.process_chargeback(client_accounting, existing_tx, tx_id, client_id)

    def process_deposit(self, client_accounting, existing_tx, tx_id, client_id, record):
        amount = record[self.amount_field_idx]
        if existing_tx:
            self.error_log("deposit duplicates existing tx_id", tx_id, client_id, "deposit", amount)
            return

        client_accounting["available"] += amount
        client_accounting["total"] += amount
        self.add_tx_log(tx_id, client_id, self.FLAG_DEPOSIT, amount)

    def process_withdrawal(self, client_accounting, existing_tx, tx_id, client_id, record):
        record_type = "withdrawal"
        amount = record[self.amount_field_idx]
        if existing_tx:
            self.error_log("withdrawal duplicates existing tx_id", tx_id, client_id, record_type, amount)
            return

        if client_accounting["available"] < amount:
            self.error_log("nsf", tx_id, client_id, record_type, amount)
            return

        client_accounting["available"] -= amount
        client_accounting["total"] -= amount
        self.add_tx_log(tx_id, client_id, self.FLAG_WITHDRAWAL, amount)

    def process_dispute(self, client_accounting, existing_tx, tx_id, client_id):
        record_type = "dispute"
        if not existing_tx:
            self.error_log("tx not found", tx_id, client_id, record_type)
            return

        if not self.check_tx(existing_tx, self.FLAG_DEPOSIT):
            self.error_log("tx is not a deposit", tx_id, client_id, record_type)
            return

        if self.check_tx(existing_tx, self.FLAG_CHARGEBACK):
            self.error_log("tx is charged back", tx_id, client_id, record_type)
            return

        if self.check_tx(existing_tx, self.FLAG_RESOLVE):
            self.error_log("tx is resolved", tx_id, client_id, record_type)
            return

        if self.check_tx(existing_tx, self.FLAG_DISPUTE):
            self.error_log("tx is already disputed", tx_id, client_id, record_type)
            return

        amount = existing_tx[2]
        client_accounting["available"] -= amount
        client_accounting["held"] += amount
        self.add_tx_log(tx_id, client_id, self.FLAG_DISPUTE, amount)

    def process_resolve(self, client_accounting, existing_tx, tx_id, client_id):
        record_type = "resolve"
        if not existing_tx:
            self.error_log("tx not found", tx_id, client_id, record_type)
            return

        if not self.check_tx(existing_tx, self.FLAG_DEPOSIT):
            self.error_log("tx is not a deposit", tx_id, client_id, record_type)
            return

        if not self.check_tx(existing_tx, self.FLAG_DISPUTE):
            self.error_log("tx is not disputed", tx_id, client_id, record_type)
            return

        if self.check_tx(existing_tx, self.FLAG_CHARGEBACK):
            self.error_log("tx is charged back", tx_id, client_id, record_type)
            return

        if self.check_tx(existing_tx, self.FLAG_RESOLVE):
            self.error_log("tx is already resolved", tx_id, client_id, record_type)
            return

        amount = existing_tx[2]
        client_accounting["held"] -= amount
        client_accounting["available"] += amount
        self.add_tx_log(tx_id, client_id, self.FLAG_RESOLVE, amount)

    def process_chargeback(self, client_accounting, existing_tx, tx_id, client_id):
        record_type = "chargeback"
        if not existing_tx:
            self.error_log("tx not found", tx_id, client_id, record_type)
            return

        if not self.check_tx(existing_tx, self.FLAG_DEPOSIT):
            self.error_log("tx is not a deposit", tx_id, client_id, record_type)
            return

        if not self.check_tx(existing_tx, self.FLAG_DISPUTE):
            self.error_log("tx is not disputed", tx_id, client_id, record_type)
            return

        if self.check_tx(existing_tx, self.FLAG_CHARGEBACK):
            self.error_log("tx is already charged back", tx_id, client_id, record_type)
            return

        if self.check_tx(existing_tx, self.FLAG_RESOLVE):
            self.error_log("tx is resolved", tx_id, client_id, record_type)
            return

        amount = existing_tx[2]
        client_accounting["held"] -= amount
        client_accounting["total"] -= amount
        client_accounting["locked"] = True
        self.add_tx_log(tx_id, client_id, self.FLAG_CHARGEBACK, amount)

    def error_log(self, message, tx_id=None, client_id=None, record_type=None, amount=None):
        if tx_id is not None and client_id is not None and record_type is not None:
            formatted_prefix = f"tx_id {tx_id}, client_id {client_id}, failed to apply {record_type}"
            amount_detail = ""
            if amount:
                amount_detail = f" of ${amount}"
            print(f"{formatted_prefix}{amount_detail}: {message}", file=sys.stderr)
        else:
            print(f"transaction error: {message}", file=sys.stderr)

    def get_tx(self, tx_id):
        return self.tx_log.get(tx_id)

    def check_tx(self, tx, tx_type):
        return tx[0] & tx_type

    def add_tx_log(self, tx_id, client_id, tx_type, amount):
        # we will have an issue if we dont have enough memory for all the tx tracking.
        if tx_id not in self.tx_log and tx_type in {self.FLAG_DEPOSIT, self.FLAG_WITHDRAWAL}:
            self.tx_log[tx_id] = [tx_type, client_id, amount]

        if tx_id not in self.tx_log:
            return

        self.tx_log[tx_id][0] |= tx_type

    def get_normalized_amount(self, record):
        if record[self.type_field_idx] not in {"deposit", "withdrawal"}:
            return None
        if not record[self.amount_field_idx]:
            return None
        return Decimal(record[self.amount_field_idx]).quantize(Decimal('.0001'), rounding=ROUND_DOWN).normalize()

    def attempt_normalize_record(self, record):
        try:
            self.normalize_record(record)
        except (ValueError, InvalidOperation) as e:
            self.error_log(f"field format error: {e} while attempting to normalize row like: {repr(record)}")
            return False
        except Exception as e:
            self.error_log(f"{e} while attempting to normalize row like: {repr(record)}")
            return False

        return True

    def normalize_record(self, record):
        record[self.type_field_idx] = record[self.type_field_idx].strip()
        record[self.client_field_idx] = int(record[self.client_field_idx].strip())
        record[self.tx_field_idx] = int(record[self.tx_field_idx].strip())
        amount = self.get_normalized_amount(record)
        if amount is not None:
            record[self.amount_field_idx] = amount

    def validate_record(self, record):
        record_type = record[self.type_field_idx]
        client_id = record[self.client_field_idx]
        tx_id = record[self.tx_field_idx]

        if record_type not in self.valid_record_types:
            self.error_log("invalid record_type", tx_id, client_id, record_type)
            return False

        if not (1 <= tx_id <= 4294967295):
            self.error_log("invalid tx_id", tx_id, client_id, record_type)
            return False

        if not (1 <= client_id <= 65535):
            self.error_log("invalid client_id", tx_id, client_id, record_type)
            return False

        return True

    def get_account_totals(self):
        self.read_transaction_data()
        return self.account_totals

    def generate_output(self):
        self.read_transaction_data()
        csvwriter = csv.writer(sys.stdout, lineterminator="\n")
        fieldnames = ['client', 'available', 'held', 'total', 'locked']
        csvwriter.writerow(fieldnames)
        for client_id, client_accounting in self.account_totals.items():
            csvwriter.writerow([
                client_id,
                client_accounting["available"],
                client_accounting["held"],
                client_accounting["total"],
                str(client_accounting["locked"]).lower(),
            ])


if __name__ == '__main__':
    PaymentEngine(sys.argv[1]).generate_output()
