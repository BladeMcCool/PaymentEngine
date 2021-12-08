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
                self.process_record(record)

    def process_record(self, record):

        self.normalize_record(record)
        self.validate_record(record)

        record_type = record[self.type_field_idx]
        client_id = record[self.client_field_idx]
        tx_id = record[self.tx_field_idx]
        # print("also .. %s" % repr(record))

        existing_tx = self.get_tx(tx_id)

        if existing_tx and existing_tx[1] != client_id:
            self.error_log("tx client_id mismatch", tx_id, client_id, record_type)
            return

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
            amount = record[self.amount_field_idx]
            if not existing_tx:
                client_accounting["available"] += amount
                client_accounting["total"] += amount
                self.add_tx_log(tx_id, client_id, self.FLAG_DEPOSIT, amount)
            else:
                self.error_log("deposit duplicates existing tx_id", tx_id, client_id, record_type, amount)

        elif record_type == "withdrawal":
            amount = record[self.amount_field_idx]

            if client_accounting["available"] >= amount:
                client_accounting["available"] -= amount
                client_accounting["total"] -= amount
                self.add_tx_log(tx_id, client_id, self.FLAG_WITHDRAWAL, amount)
            else:
                # log nsf
                self.error_log("nsf", tx_id, client_id, record_type, amount)

        elif record_type == "dispute":
            if existing_tx:
                if self.check_tx(existing_tx, self.FLAG_DEPOSIT):
                    amount = existing_tx[2]
                    client_accounting["available"] -= amount
                    client_accounting["held"] += amount
                    self.add_tx_log(tx_id, client_id, self.FLAG_DISPUTE, amount)
                else:
                    self.error_log("tx is not a deposit", tx_id, client_id, record_type)

            else:
                self.error_log("tx not found", tx_id, client_id, record_type)

        elif record_type == "resolve":
            if existing_tx:
                if not self.check_tx(existing_tx, self.FLAG_DEPOSIT):
                    self.error_log("tx has no deposit", tx_id, client_id, record_type)
                else:
                    if self.check_tx(existing_tx, self.FLAG_DISPUTE):
                        amount = existing_tx[2]
                        client_accounting["held"] -= amount
                        client_accounting["available"] += amount
                        self.add_tx_log(tx_id, client_id, self.FLAG_RESOLVE, amount)
                    else:
                        self.error_log("tx is not disputed", tx_id, client_id, record_type)

            else:
                self.error_log("tx not found", tx_id, client_id, record_type)


    def error_log(self, message, tx_id, client_id, record_type, amount=None):
        formatted_prefix = f"tx_id {tx_id}, client_id {client_id}, failed to apply {record_type}"
        amount_detail = ""
        if amount:
            amount_detail = f" of ${amount}"
        print(f"{formatted_prefix}{amount_detail}: {message}", file=sys.stderr)

    # def get_tx(self, tx_id, client_id):
    #     tx_record = self.tx_log.get(tx_id)
    #     if tx_record[2] != client_id:
    #         raise ValueError("client id mismatch")
    #     return tx_record

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

    def normalize_record(self, record):
        record[self.type_field_idx] = record[self.type_field_idx].strip()
        record[self.client_field_idx] = int(record[self.client_field_idx].strip())
        record[self.tx_field_idx] = int(record[self.tx_field_idx].strip())
        amount = self.get_normalized_amount(record)
        if amount:
            # print(repr(amount))
            # print(repr(record))
            record[self.amount_field_idx] = amount
        return record

    def validate_record(self, record):
        if record[self.type_field_idx] not in self.valid_record_types:
            print(self.valid_record_types)
            print(record[self.type_field_idx])
            print(record[self.type_field_idx] in self.valid_record_types)
            print(repr(record[self.type_field_idx]))
            raise ValueError(f"invalid record type: {record[self.type_field_idx]}")

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
