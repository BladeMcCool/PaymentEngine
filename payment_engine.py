import csv
import sys
from decimal import Decimal, ROUND_DOWN


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
        with open(self.filename) as file:
            csvreader = csv.reader(file)
            _ = next(csvreader)  # read and discard header -- but maybe we should interpret it for record field order?
            for record in csvreader:
                self.validate_record(record)
                self.process_record(record)

    def process_record(self, record):
        record_type = record[self.type_field_idx].strip()
        client_id = int(record[self.client_field_idx].strip())
        tx_id = int(record[self.tx_field_idx].strip())

        # ownfunc
        if client_id not in self.account_totals:
            self.account_totals[client_id] = {
                "available": Decimal(0),
                "held": Decimal(0),
                "total": Decimal(0),
                "locked": False,
            }

        client_accounting = self.account_totals[client_id]

        if record_type == "deposit":
            amount = self.get_normalized_amount(record)
            client_accounting["available"] += amount
            client_accounting["total"] += amount
            self.add_tx_log(tx_id, self.FLAG_DEPOSIT, amount)
        elif record_type == "withdrawal":
            amount = self.get_normalized_amount(record)
            if client_accounting["available"] >= amount:
                client_accounting["available"] -= amount
                client_accounting["total"] -= amount
                self.add_tx_log(tx_id, self.FLAG_WITHDRAWAL, amount)
            else:
                # log nsf
                pass

    def get_tx(self, tx_id):
        return self.tx_log.get(tx_id)

    def check_tx(self, tx, tx_type):
        return tx[0] & tx_type

    def add_tx_log(self, tx_id, tx_type, amount):
        # we will have an issue if we dont have enough memory for all the tx tracking.
        if tx_id not in self.tx_log and tx_type == self.FLAG_DEPOSIT:
            self.tx_log[tx_id] = [self.FLAG_DEPOSIT, amount]

    def get_normalized_amount(self, record):
        return Decimal(record[self.amount_field_idx]).quantize(Decimal('.0001'), rounding=ROUND_DOWN).normalize()

    def validate_record(self, record):
        if record[self.type_field_idx] not in self.valid_record_types:
            raise ValueError(f"invalid record type: {record[self.type_field_idx]}")

    def get_account_totals(self):
        self.read_transaction_data()
        return self.account_totals

    def generate_output(self):
        self.read_transaction_data()
        csvwriter = csv.writer(sys.stdout)
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
