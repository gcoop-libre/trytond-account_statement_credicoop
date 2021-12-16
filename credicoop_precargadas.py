# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import io
import csv
from datetime import datetime
from decimal import Decimal


def _date(value):
    v = value.strip()
    return datetime.strptime(v, '%d/%m/%Y').date()


def _string(value):
    return value.strip()


def _card_string(value):
    return value.strip('-')


def _amount(value):
    value = value.replace('.', '')
    return Decimal(value.replace(',', '.'))


RECEIVER = {
    'receiver': (4, _string),
    'card_number': (9, _card_string),
    }

PERIOD = {
    'date_from': (4, _date),
    'date_to': (9, _date),
    }

MOVE = {
    'date': (1, _date),
    'op_number': (2, _string),
    'name': (3, _string),
    'description1': (4, _string),
    'description2': (6, _string),
    'debit': (8, _amount),
    'credit': (12, _amount),
    }


class Precargadas(object):

    def __init__(self, name, encoding='windows-1252'):
        self.statements = []

        if isinstance(name, (bytes, str)):
            with io.open(name, encoding=encoding, mode='r') as f:
                self._parse(f)
        else:
            self._parse(name)

    def _parse(self, f):
        statement = Statement()
        self.statements.append(statement)

        csv_reader = csv.reader(f, delimiter=',')
        line = 0
        debit_total = 0
        credit_total = 0
        for row in csv_reader:
            line += 1
            if line in range(1, 5):
                continue
            elif line == 5:
                self._parse_statement(row, statement, RECEIVER)
            elif line == 6:
                self._parse_statement(row, statement, PERIOD)
            elif line in range(7, 9):
                continue
            else:
                if row[1] == '':
                    continue
                move = Move()
                self._parse_move(row, move, MOVE)
                if row[8]:
                    debit_total += _amount(row[8])
                if row[12]:
                    credit_total += _amount(row[12])
                statement.moves.append(move)
        statement.debit_total = debit_total
        statement.credit_total = credit_total
        return

    def _parse_statement(self, row, statement, desc):
        for name, (col, parser) in desc.items():
            value = parser(row[col])
            setattr(statement, name, value)

    def _parse_move(self, row, move, desc):
        for name, (col, parser) in desc.items():
            value = parser(row[col])
            setattr(move, name, value)


class Statement(object):
    __slots__ = list(RECEIVER.keys()) + list(PERIOD.keys()) + [
        'debit_total', 'credit_total', 'moves']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.moves = []


class Move(object):
    __slots__ = list(MOVE.keys())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
