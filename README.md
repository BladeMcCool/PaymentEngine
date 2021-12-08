## Run program

`python3 payment_engine.py tests/fixtures/sample3.csv > client_accounts.csv`

## Run tests

`python3 -m unittest discover`

## Notes

The development effort commenced with creating a fixture for sample input and a unit test on the main processing function, capturing the output and comparing it against what was expected. 

Unit testing has primarily focussed on the process_record function which is doing most of the work.

End to end testing is included which has the program read fixture sample files and check the output

Custom field ordering has been allowed for the input by having the program scan the fields of the header row. This is a simple best-effort and if there were redundant fields with the expected names I believe it would just decide to use the column it saw last for a given field. Without specifying fields in the header it will assume the order as defined in the assignment spec.

Because the assumption was made that we must not allow processing of duplicated transaction ids, we must track all transaction ids in memory. This is a hard limit on the program right now. An idea to improve the efficiency, if we could relax needing to check for duplicate transaction ids is to process the input in two passes. The first pass would only look for disputes/resolves/chargebacks and make a note of each tx that will need those applied. Then a rescan of the input file could skip needing to keep track of any transaction ids that arent being disputed/resolved/chargedback.

Additionally, the implementation of a state machine for the transactions themselves should be able to streamline the flag checking code that happens in each type of operation. We logically can only progress deposit->dispute->resolve/chargeback. An attempt may be made on this revision before submission.

Client accounts can end up locked after a chargeback. In the absence of requirements for specific behavior to take with regards to accounts which have become locked, we will continue processing transactions discovered for a given client even after that client has become locked.

Any non fatal errors encountered while processing will be logged to stdout.